"""Replay official guest extras on Pixel APK libcurl, then get_cpt_ifm.

Official order: ad_reader_check -> auto_reg_v2 -> save_reader_oaid
-> send_client_info(push_type=2, reader_id) -> chapter.

Host after login follows UrlConstants.getURL: reader_id ending 1-5
uses app1.happybooker.cn, otherwise app1.hbooker.com.

Cookie jar lives on device next to oldcurl_post. Does not touch tokens.json.
Does not copy logcat tokens. Does not start Geetest.
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

from client import api, config, protocol  # noqa: E402
from client.api import ApiError  # noqa: E402
from client.guest import (  # noqa: E402
    android_id_to_am,
    build_guest_registration_params,
    build_save_reader_oaid_params,
)

from oldcurl_guest_canary import (  # noqa: E402
    OFFICIAL_CPT_ORDER,
    OFFICIAL_UA,
    REMOTE,
    adb,
    decode_body,
    oldcurl_post,
    pick_free_chapter,
    probe,
    proxy_state,
    push_runtime,
    session_for,
)

OUT = ROOT / "analysis/app-version-2.9.365/evidence/pixel-official-chain-canary.json"
GUEST_PATH = ROOT / "analysis/app-version-2.9.365/work/pixel-chain-guest-tokens.json"
OFFICIAL_CHAPTER_ID = "106129841"
HBOOKER = "https://app1.hbooker.com"
HAPPY = "https://app1.happybooker.cn"

AD_CHECK_ORDER = (
    "app_version",
    "channel",
    "device_token",
    "rand_str",
    "p",
)
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
OAID_ORDER = (
    "account",
    "am",
    "app_version",
    "channel",
    "device_token",
    "login_token",
    "oaid",
    "reader_id",
    "rand_str",
    "p",
)
CLIENT_INFO_ORDER = (
    "account",
    "app_version",
    "device_token",
    "login_token",
    "push_type",
    "reader_id",
    "rand_str",
    "p",
)
CMD_ORDER = (
    "account",
    "app_version",
    "chapter_id",
    "device_token",
    "login_token",
    "rand_str",
    "p",
)


def encode(params: dict, order: tuple[str, ...]) -> str:
    items = [(key, params[key]) for key in order if key in params]
    items.extend((key, value) for key, value in params.items() if key not in order)
    return urlencode(items)


def host_for_reader_id(reader_id: str) -> str:
    last = reader_id[-1:] if reader_id else ""
    return HAPPY if last in "12345" else HBOOKER


def cookie_state() -> dict:
    listed = adb("shell", "ls", "-l", f"{REMOTE}/cookies.txt")
    stdout = (listed.stdout or "").strip()
    size = adb("shell", "stat", "-c", "%s", f"{REMOTE}/cookies.txt")
    raw_size = (size.stdout or "").strip()
    out = {"exists": "No such file" not in (listed.stderr or "") and bool(stdout)}
    if raw_size.isdigit():
        out["bytes"] = int(raw_size)
    return out


def reset_cookies() -> None:
    adb("shell", "rm", "-f", f"{REMOTE}/cookies.txt")


def post_signed(url: str, extra: dict, account: str, order: tuple[str, ...],
                session: api.Session | None = None) -> dict:
    if session is not None:
        params = session._request_params(extra)
    else:
        params = dict(extra)
        params.update(protocol.sign_request(account, config.APP_VERSION))
    body = encode(params, order)
    posted = oldcurl_post(url, body, OFFICIAL_UA)
    meta = posted["meta"]
    raw = posted["raw"].decode("utf-8", errors="replace")
    result = {
        "http_code": meta.get("http_code"),
        "curl_code": meta.get("curl_code"),
        "ssl_verify": meta.get("ssl_verify"),
        "curl_version": meta.get("curl_version"),
    }
    if not raw.strip():
        result.update({"ok": False, "code": "empty"})
        return result
    data = decode_body(raw, config.APP_VERSION)
    code = str(data.get("code", ""))
    result["code"] = code
    result["ok"] = code == "100000"
    if code != "100000":
        result["tip"] = str(data.get("tip") or "")[:80]
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    result["data_keys"] = sorted(payload.keys())[:16]
    result["_data"] = data
    return result


def public_result(result: dict) -> dict:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def pixel_android_id() -> str:
    raw = adb("shell", "settings", "get", "secure", "android_id")
    value = (raw.stdout or "").strip()
    if not value or value == "null":
        raise SystemExit("android_id missing")
    return value


def chapter_by_id(session: api.Session, chapter_id: str, label: str) -> dict:
    out = {"chapter_id_len": len(chapter_id), "label": label}
    cmd = probe(
        session,
        "/chapter/get_chapter_cmd",
        {"chapter_id": chapter_id},
        ua=OFFICIAL_UA,
        order=CMD_ORDER,
        label=f"{label}-cmd",
    )
    out["cmd"] = {key: cmd.get(key) for key in ("ok", "code", "tip")}
    command = ""
    if cmd.get("ok"):
        try:
            command = session.get_chapter_command(chapter_id)
        except ApiError as exc:
            out["cmd_parse"] = {"ok": False, "code": exc.code, "tip": (exc.tip or "")[:80]}
    cpt = probe(
        session,
        "/chapter/get_cpt_ifm",
        {"chapter_id": chapter_id, "chapter_command": command},
        ua=OFFICIAL_UA,
        order=OFFICIAL_CPT_ORDER,
        label=f"{label}-cpt",
    )
    out["cpt"] = {key: cpt.get(key) for key in ("ok", "code", "tip")}
    out["has_command"] = bool(command)
    return out


def search_free_chapter(session: api.Session) -> dict:
    out = {}
    search = probe(
        session,
        "/bookcity/get_filter_search_book_list",
        session._search_params("青春", 0, 1),
        ua=OFFICIAL_UA,
        label="search",
    )
    out["search"] = {key: search.get(key) for key in ("ok", "code", "tip")}
    if not search.get("ok"):
        return out
    listed = session.search_books("青春", page=0, count=1)
    books = listed.get("data", {}).get("book_list", []) or []
    book_id = str((books[0] or {}).get("book_id") or "")
    catalog = session.get_book_catalog(book_id)
    chapter_id = pick_free_chapter(catalog)
    out["has_book_id"] = bool(book_id)
    out["has_chapter_id"] = bool(chapter_id)
    if chapter_id:
        out.update(chapter_by_id(session, chapter_id, "search-free"))
    return out


def main() -> None:
    push_runtime()
    reset_cookies()
    proxy = proxy_state()
    am = android_id_to_am(pixel_android_id())
    checks = {}

    ad_params = {
        "app_version": config.APP_VERSION,
        "channel": config.GUEST_REGISTRATION_CHANNEL,
        "device_token": config.DEVICE_TOKEN_PREFIX,
    }
    ad = post_signed(
        f"{HBOOKER}/setting/ad_reader_check",
        ad_params,
        config.GUEST_REGISTRATION_ACCOUNT,
        AD_CHECK_ORDER,
    )
    checks["ad_reader_check"] = public_result(ad)

    uuid_value = f"android{uuid4()}"
    reg_params = build_guest_registration_params(uuid_value=uuid_value)
    posted = oldcurl_post(
        f"{HBOOKER}/signup/auto_reg_v2",
        encode(reg_params, AUTO_REG_ORDER),
        OFFICIAL_UA,
    )
    raw = posted["raw"].decode("utf-8", errors="replace")
    auto = {
        "http_code": posted["meta"].get("http_code"),
        "curl_code": posted["meta"].get("curl_code"),
        "ssl_verify": posted["meta"].get("ssl_verify"),
        "uuid_len": len(uuid_value),
        "uuid_prefix": "android",
    }
    tokens = None
    if not raw.strip():
        auto.update({"ok": False, "code": "empty"})
    else:
        data = decode_body(raw, config.APP_VERSION)
        code = str(data.get("code", ""))
        auto["code"] = code
        auto["ok"] = code == "100000"
        if code != "100000":
            auto["tip"] = str(data.get("tip") or "")[:80]
        else:
            payload = data.get("data") or {}
            reader = payload.get("reader_info") or {}
            tokens = {
                "login_token": str(payload.get("login_token") or "").strip(),
                "account": str(reader.get("account") or "").strip(),
                "device_token": config.DEVICE_TOKEN_PREFIX,
                "reader_id": str(reader.get("reader_id") or "").strip(),
                "is_bind": str(reader.get("is_bind") or ""),
            }
            auto["has_login_token"] = bool(tokens["login_token"])
            auto["account_len"] = len(tokens["account"])
            auto["reader_id_len"] = len(tokens["reader_id"])
            auto["reader_id_last"] = tokens["reader_id"][-1:] if tokens["reader_id"] else ""
            auto["is_bind"] = tokens["is_bind"]
    checks["auto_reg"] = auto
    checks["cookies_after_reg"] = cookie_state()

    chapter = {}
    if tokens and tokens["login_token"] and tokens["account"]:
        GUEST_PATH.write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        host = host_for_reader_id(tokens["reader_id"])
        auto["chapter_host"] = host.split("://", 1)[-1]
        session = session_for(tokens)
        session.base_url = host
        oaid_extra = build_save_reader_oaid_params(
            reader_id=tokens["reader_id"],
            am=am,
            oaid="",
        )
        oaid = post_signed(
            f"{host}/signup/save_reader_oaid",
            oaid_extra,
            tokens["account"],
            OAID_ORDER,
            session=session,
        )
        checks["save_reader_oaid"] = public_result(oaid)
        checks["save_reader_oaid"]["am_len"] = len(am)
        checks["save_reader_oaid"]["oaid_empty"] = True

        info = post_signed(
            f"{host}/reader/send_client_info",
            {"push_type": "2", "reader_id": tokens["reader_id"]},
            tokens["account"],
            CLIENT_INFO_ORDER,
            session=session,
        )
        checks["send_client_info"] = public_result(info)
        try:
            chapter["official_onboarding"] = chapter_by_id(
                session, OFFICIAL_CHAPTER_ID, "official-onboarding",
            )
            chapter["search_free"] = search_free_chapter(session)
        except ApiError as exc:
            chapter["error"] = {"code": exc.code, "tip": (exc.tip or "")[:80]}
        finally:
            session.close()

    official_ok = bool(
        ((chapter.get("official_onboarding") or {}).get("cpt") or {}).get("ok")
    )
    search_ok = bool(((chapter.get("search_free") or {}).get("cpt") or {}).get("ok"))
    payload = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "action": (
            "ad_reader_check + pixel libcurl auto_reg_v2 + cookie jar + "
            "host-by-reader_id + save_oaid + send_client_info push_type=2 + "
            "get_cpt_ifm official chapter 106129841 and search-free"
        ),
        "proxy": proxy,
        "cookies": cookie_state(),
        "checks": checks,
        "chapter": chapter,
        "ok": official_ok or search_ok,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
