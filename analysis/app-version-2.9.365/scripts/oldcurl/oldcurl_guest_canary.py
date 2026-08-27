"""Guest chapter canary over APK libcurl 7.56.1 + OpenSSL 1.1.0f on Pixel 6.

Python only signs and decrypts. TLS is the official so. Does not touch tokens.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import api, config, crypto  # noqa: E402
from client.api import ApiError  # noqa: E402
from client.guest import GuestRegistrationError, register_guest  # noqa: E402

ADB = r"D:\reverse_ENV\tools\adb\adb.exe"
SERIAL = "18251FDF6000N9"
PKG_LIBS = ROOT / (
    "analysis/app-version-2.9.365/work/apk-static/apktool/lib/arm64-v8a"
)
OLD = ROOT / "analysis/app-version-2.9.365/work/oldcurl"
REMOTE = "/data/local/tmp/ciweimao-oldcurl"
GUEST_PATH = ROOT / "analysis/app-version-2.9.365/work/guest-canary-tokens.json"
OUT_PATH = ROOT / "analysis/app-version-2.9.365/evidence/oldcurl-guest-canary.json"
BIN = OLD / "oldcurl_post"


def adb(*args: str, timeout: int = 40) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ADB, "-s", SERIAL, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def proxy_state() -> dict:
    host = (adb("shell", "settings", "get", "global", "global_http_proxy_host").stdout or "").strip()
    port = (adb("shell", "settings", "get", "global", "global_http_proxy_port").stdout or "").strip()
    http = (adb("shell", "settings", "get", "global", "http_proxy").stdout or "").strip()
    return {"http_proxy": http, "host": host, "port": port}


def push_runtime() -> None:
    adb("shell", "mkdir", "-p", REMOTE)
    for name in ("libcurl.so", "libssl.so", "libcrypto.so"):
        src = PKG_LIBS / name
        if not src.exists():
            raise SystemExit(f"missing {src}")
        pushed = adb("push", str(src), f"{REMOTE}/{name}")
        if pushed.returncode != 0:
            raise SystemExit(pushed.stderr or f"push {name} failed")
    pushed = adb("push", str(BIN), f"{REMOTE}/oldcurl_post")
    if pushed.returncode != 0:
        raise SystemExit(pushed.stderr or "push binary failed")
    adb("shell", "chmod", "755", f"{REMOTE}/oldcurl_post")


def load_guest() -> dict:
    if GUEST_PATH.exists():
        raw = json.loads(GUEST_PATH.read_text(encoding="utf-8"))
        if raw.get("login_token") and raw.get("account"):
            return {
                "login_token": raw["login_token"],
                "account": raw["account"],
                "device_token": raw.get("device_token") or "ciweimao_",
                "source": "guest-canary-tokens.json",
            }
    creds = asyncio.run(register_guest())
    payload = {
        "login_token": creds.login_token,
        "account": creds.account,
        "device_token": creds.device_token,
    }
    GUEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "source": "register_guest"}


def session_for(tokens: dict) -> api.Session:
    return api.Session(
        login_token=tokens["login_token"],
        account=tokens["account"],
        device_token=tokens["device_token"],
        app_version=config.APP_VERSION,
        timeout=20,
        max_retries=1,
        transient_api_retries=0,
    )


def decode_body(raw: str, app_version: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("empty-response")
    if text.startswith("{"):
        return json.loads(text)
    plaintext = crypto.decrypt_response_for_version(text, app_version)
    return json.loads(plaintext)


def oldcurl_post(url: str, body: str, ua: str) -> dict:
    local = OLD / "run"
    local.mkdir(parents=True, exist_ok=True)
    (local / "url.txt").write_text(url + "\n", encoding="ascii")
    (local / "ua.txt").write_text(ua + "\n", encoding="ascii")
    (local / "body.txt").write_bytes(body.encode("ascii"))
    for name in ("url.txt", "ua.txt", "body.txt"):
        adb("push", str(local / name), f"{REMOTE}/{name}")
    cmd = (
        f"LD_LIBRARY_PATH={REMOTE} {REMOTE}/oldcurl_post "
        f"{REMOTE}/url.txt {REMOTE}/body.txt {REMOTE}/out.bin {REMOTE}/ua.txt"
    )
    ran = adb("shell", cmd, timeout=45)
    pulled = adb("pull", f"{REMOTE}/out.bin", str(local / "out.bin"))
    raw = b""
    if (local / "out.bin").exists():
        raw = (local / "out.bin").read_bytes()
    meta = {}
    err = (ran.stderr or "").strip()
    for line in reversed(err.splitlines() or []):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                meta = json.loads(line)
            except json.JSONDecodeError:
                meta = {"raw_stderr": line[:200]}
            break
    if not meta:
        meta = {"raw_stderr": err[:200], "stdout": (ran.stdout or "")[:200]}
    meta["adb_rc"] = ran.returncode
    meta["pull_rc"] = pulled.returncode
    meta["raw_len"] = len(raw)
    return {"meta": meta, "raw": raw}


OFFICIAL_UA = "Android  com.kuangxiangciweimao.novel.c  "
OFFICIAL_CPT_ORDER = (
    "account",
    "app_version",
    "chapter_command",
    "chapter_id",
    "device_token",
    "login_token",
    "rand_str",
    "p",
)


def _encode(params: dict, order: tuple[str, ...] | None = None) -> str:
    if not order:
        return urlencode(params)
    items = [(key, params[key]) for key in order if key in params]
    items.extend((key, value) for key, value in params.items() if key not in order)
    return urlencode(items)


def probe(
    session: api.Session,
    path: str,
    extra: dict | None = None,
    *,
    ua: str | None = None,
    order: tuple[str, ...] | None = None,
    label: str | None = None,
) -> dict:
    started = datetime.now(timezone.utc)
    params = session._request_params(extra)
    body = _encode(params, order)
    url = f"{session.base_url}{path}"
    posted = oldcurl_post(url, body, ua or session.headers["User-Agent"])
    meta = posted["meta"]
    raw = posted["raw"]
    result = {
        "path": path,
        "label": label or path,
        "http_code": meta.get("http_code"),
        "curl_version": meta.get("curl_version"),
        "curl_code": meta.get("curl_code"),
        "ssl_verify": meta.get("ssl_verify"),
        "http_version_setopt": meta.get("http_version_setopt"),
        "http_version": meta.get("http_version"),
        "headers": meta.get("headers"),
        "curl_error": (meta.get("curl_error") or "")[:80],
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }
    if not raw:
        result["ok"] = False
        result["code"] = "empty"
        result["meta_ok"] = meta.get("ok")
        return result
    try:
        data = decode_body(raw.decode("utf-8", errors="replace"), session.app_version)
        code = str(data.get("code", ""))
        result["code"] = code
        result["ok"] = code == "100000"
        if code != "100000":
            result["tip"] = str(data.get("tip") or "")[:80]
        else:
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            result["data_keys"] = sorted(payload.keys())
    except Exception as exc:
        result["ok"] = False
        result["code"] = "decode-failed"
        result["error_type"] = type(exc).__name__
        result["tip"] = str(exc)[:80]
    return result


def pick_free_chapter(catalog: dict) -> str:
    for division in catalog.get("data", {}).get("chapter_list", []) or []:
        for chapter in division.get("chapter_list", []) or []:
            if str(chapter.get("is_paid")) == "0" and str(chapter.get("auth_access")) == "1":
                cid = str(chapter.get("chapter_id") or "")
                if cid:
                    return cid
    return ""


def main() -> None:
    if not BIN.exists():
        raise SystemExit(f"missing binary {BIN}")
    proxy = proxy_state()
    push_runtime()
    tokens = load_guest()
    session = session_for(tokens)
    checks = []
    search = probe(session, "/bookcity/get_filter_search_book_list", session._search_params("青春", 0, 1))
    if search.get("code") in ("200100", "empty", "decode-failed"):
        session.close()
        GUEST_PATH.unlink(missing_ok=True)
        tokens = load_guest()
        session = session_for(tokens)
        search = probe(session, "/bookcity/get_filter_search_book_list", session._search_params("青春", 0, 1))
    checks.append(search)
    book_id = ""
    chapter_id = ""
    command_len = 0
    if search.get("ok"):
        # Need book_id: search via curl_cffi only to parse list, then chapter still old-curl.
        try:
            listed = session.search_books("青春", page=0, count=1)
            books = listed.get("data", {}).get("book_list", []) or []
            book_id = str((books[0] or {}).get("book_id") or "")
        except ApiError:
            book_id = ""
        except GuestRegistrationError:
            book_id = ""
    catalog = {"ok": False, "code": "skipped"}
    cmd = {"ok": False, "code": "skipped"}
    chapter = {"ok": False, "code": "skipped"}
    if book_id:
        catalog = probe(
            session,
            "/chapter/get_updated_chapter_by_division_new",
            {"book_id": book_id, "division_id": "0"},
        )
        checks.append(catalog)
        try:
            cat = session.get_book_catalog(book_id)
            chapter_id = pick_free_chapter(cat)
        except Exception:
            chapter_id = ""
    if chapter_id:
        cmd = probe(session, "/chapter/get_chapter_cmd", {"chapter_id": chapter_id})
        checks.append(cmd)
        try:
            command = session.get_chapter_command(chapter_id)
            command_len = len(command or "")
        except Exception:
            command = ""
        if command:
            extra = {"chapter_id": chapter_id, "chapter_command": command}
            chapter = probe(session, "/chapter/get_cpt_ifm", extra)
            checks.append(chapter)
            shaped = probe(
                session,
                "/chapter/get_cpt_ifm",
                extra,
                ua=OFFICIAL_UA,
                order=OFFICIAL_CPT_ORDER,
                label="get_cpt_ifm official-ua-order",
            )
            checks.append(shaped)
            prelude = probe(session, "/reader/send_client_info", {})
            checks.append(prelude)
            after = probe(
                session,
                "/chapter/get_cpt_ifm",
                extra,
                ua=OFFICIAL_UA,
                order=OFFICIAL_CPT_ORDER,
                label="get_cpt_ifm after-send_client_info",
            )
            checks.append(after)
    payload = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "stack": "apk-libcurl-7.56.1 + openssl-1.1.0f on pixel6",
        "binary": "analysis/app-version-2.9.365/work/oldcurl/oldcurl_post",
        "guest_source": tokens["source"],
        "proxy": proxy,
        "curl_version": next((c.get("curl_version") for c in checks if c.get("curl_version")), ""),
        "has_book_id": bool(book_id),
        "has_chapter_id": bool(chapter_id),
        "command_len": command_len,
        "checks": checks,
        "ok": bool(chapter.get("ok")),
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    session.close()


if __name__ == "__main__":
    main()
