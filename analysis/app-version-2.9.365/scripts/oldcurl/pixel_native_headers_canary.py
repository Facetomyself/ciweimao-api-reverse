"""Register and read chapter via APK libcurl with native getHead0 UA,
charsets/Expect headers, and CURLOPT_HTTP_VERSION=3.

Does not read Pixel INSTALLATION. Does not touch tokens.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from client import api, config  # noqa: E402
from client.api import ApiError  # noqa: E402
from client.guest import build_guest_registration_params  # noqa: E402

from oldcurl_guest_canary import (  # noqa: E402
    adb,
    decode_body,
    oldcurl_post,
    pick_free_chapter,
    probe,
    proxy_state,
    push_runtime,
    session_for,
)

OUT = ROOT / "analysis/app-version-2.9.365/evidence/pixel-native-headers-canary.json"
GUEST_PATH = ROOT / "analysis/app-version-2.9.365/work/pixel-native-headers-guest-tokens.json"
AUTO_REG_ORDER = (
    "app_version",
    "channel",
    "device_token",
    "gender",
    "oauth_open_id",
    "oauth_type",
    "oauth_union_id",
    "uuid",
    "rand_str",
    "p",
)


def getprop(name: str) -> str:
    return (adb("shell", "getprop", name).stdout or "").strip()


def get_head0_ua(app_version: str = config.APP_VERSION) -> dict:
    brand = getprop("ro.product.brand") or "unknown"
    model = getprop("ro.product.model") or "unknown"
    sdk = getprop("ro.build.version.sdk") or "unknown"
    release = getprop("ro.build.version.release") or "unknown"
    ua = (
        "Android  com.kuangxiangciweimao.novel.c  "
        f"{app_version}, {brand}, {model}, {sdk}, {release}"
    )
    return {
        "ua": ua,
        "app_version": app_version,
        "brand": brand,
        "model": model,
        "sdk": sdk,
        "release": release,
    }


def encode(params: dict, order: tuple[str, ...]) -> str:
    items = [(key, params[key]) for key in order if key in params]
    items.extend((key, value) for key, value in params.items() if key not in order)
    return urlencode(items)


def register_on_pixel(ua: str) -> dict:
    uuid_value = f"android{uuid4()}"
    params = build_guest_registration_params(uuid_value=uuid_value)
    body = encode(params, AUTO_REG_ORDER)
    url = f"{config.GUEST_REGISTRATION_BASE_URL.rstrip('/')}/signup/auto_reg_v2"
    posted = oldcurl_post(url, body, ua)
    meta = posted["meta"]
    raw = posted["raw"].decode("utf-8", errors="replace")
    result = {
        "http_code": meta.get("http_code"),
        "curl_version": meta.get("curl_version"),
        "curl_code": meta.get("curl_code"),
        "ssl_verify": meta.get("ssl_verify"),
        "http_version_setopt": meta.get("http_version_setopt"),
        "http_version": meta.get("http_version"),
        "headers": meta.get("headers"),
        "uuid_len": len(uuid_value),
        "uuid_prefix": "android",
    }
    if not raw.strip():
        result.update({"ok": False, "code": "empty", "curl_error": (meta.get("curl_error") or "")[:80]})
        return {"result": result, "tokens": None}
    data = decode_body(raw, config.APP_VERSION)
    code = str(data.get("code", ""))
    result["code"] = code
    result["ok"] = code == "100000"
    if code != "100000":
        result["tip"] = str(data.get("tip") or "")[:80]
        return {"result": result, "tokens": None}
    payload = data.get("data") or {}
    reader = payload.get("reader_info") or {}
    tokens = {
        "login_token": str(payload.get("login_token") or "").strip(),
        "account": str(reader.get("account") or "").strip(),
        "device_token": config.DEVICE_TOKEN_PREFIX,
        "reader_id": str(reader.get("reader_id") or "").strip(),
        "is_bind": str(reader.get("is_bind") or ""),
    }
    result["has_login_token"] = bool(tokens["login_token"])
    result["account_len"] = len(tokens["account"])
    result["reader_id_len"] = len(tokens["reader_id"])
    result["is_bind"] = tokens["is_bind"]
    return {"result": result, "tokens": tokens}


def chapter_on_pixel(tokens: dict, ua: str) -> dict:
    session = session_for(tokens)
    session.base_url = config.CURRENT_BASE_URL
    out = {}
    try:
        search = probe(
            session,
            "/bookcity/get_filter_search_book_list",
            session._search_params("青春", 0, 1),
            ua=ua,
            label="search",
        )
        out["search"] = {
            key: search.get(key)
            for key in (
                "ok", "code", "tip", "http_version_setopt", "http_version", "headers",
            )
            if key in search or key in ("ok", "code", "tip")
        }
        out["search"]["http_version_setopt"] = search.get("http_version_setopt")
        out["search"]["http_version"] = search.get("http_version")
        if not search.get("ok"):
            return out
        listed = session.search_books("青春", page=0, count=1)
        books = listed.get("data", {}).get("book_list", []) or []
        book_id = str((books[0] or {}).get("book_id") or "")
        catalog = session.get_book_catalog(book_id)
        chapter_id = pick_free_chapter(catalog)
        command = session.get_chapter_command(chapter_id) if chapter_id else ""
        cmd = probe(
            session,
            "/chapter/get_chapter_cmd",
            {"chapter_id": chapter_id},
            ua=ua,
            label="cmd",
        )
        out["cmd"] = {key: cmd.get(key) for key in ("ok", "code", "tip")}
        cpt = probe(
            session,
            "/chapter/get_cpt_ifm",
            {"chapter_id": chapter_id, "chapter_command": command},
            ua=ua,
            label="cpt",
        )
        out["cpt"] = {key: cpt.get(key) for key in ("ok", "code", "tip")}
        out["cpt"]["http_version"] = cpt.get("http_version")
    except ApiError as exc:
        out["error"] = {"code": exc.code, "tip": (exc.tip or "")[:80]}
    finally:
        session.close()
    return out


def main() -> None:
    proxy = proxy_state()
    head0 = get_head0_ua()
    push_runtime()
    registered = register_on_pixel(head0["ua"])
    tokens = registered["tokens"]
    chapter = {}
    if tokens and tokens["login_token"] and tokens["account"]:
        GUEST_PATH.write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        chapter = chapter_on_pixel(tokens, head0["ua"])
    payload = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "action": (
            "auto_reg_v2 + get_cpt_ifm via apk libcurl with getHead0 UA, "
            "charsets/Expect, CURLOPT_HTTP_VERSION=3"
        ),
        "uuid_source": "generated android+uuid4, not Pixel INSTALLATION",
        "proxy": proxy,
        "head0": head0,
        "auto_reg": registered["result"],
        "chapter": chapter,
        "ok": bool((chapter.get("cpt") or {}).get("ok")),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
