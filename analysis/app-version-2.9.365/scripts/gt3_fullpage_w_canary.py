"""GT3 fullpage bind canary：默认本机 Node 黑盒，不依赖 RuyiDOM。

新游客、不写 tokens.json、不走网页章节链。验收只认 get_cpt_ifm=100000。
不打印 gt/challenge/validate/w 原文。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client import api, config, gt3, gt3_w  # noqa: E402
from client.api import ApiError  # noqa: E402
from client.guest import register_guest  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analysis"
    / "app-version-2.9.365"
    / "evidence"
    / "gt3-fullpage-w-canary.json"
)
DEFAULT_CHAPTER_ID = "106129841"


def account_fp(account: str) -> str:
    return hashlib.sha256(str(account).encode("utf-8")).hexdigest()[:12]


def base_url_for_reader_id(reader_id: str) -> str:
    last = str(reader_id or "")[-1:]
    if last.isdigit() and 1 <= int(last) <= 5:
        return config.CURRENT_BASE_URL
    return "https://app1.hbooker.com"


def _chapter_code(session: api.Session, chapter_id: str) -> dict:
    try:
        command = session.get_chapter_command(chapter_id)
    except ApiError as exc:
        return {"ok": False, "code": exc.code, "tip": (exc.tip or "")[:80]}
    try:
        session.get_chapter_content(chapter_id, command)
        return {
            "ok": True,
            "code": "100000",
            "chapter_id_len": len(chapter_id),
            "command": command,
        }
    except ApiError as exc:
        return {
            "ok": exc.code == "100000",
            "code": exc.code,
            "tip": (exc.tip or "")[:80],
            "chapter_id_len": len(chapter_id),
            "command": command if exc.code != "200100" else "",
        }


def _retry_code(session: api.Session, chapter_id: str, command: str,
                triple: gt3.Gt3Triple) -> dict:
    try:
        session.retry_chapter_after_gt3(chapter_id, command, triple)
        return {"ok": True, "code": "100000"}
    except ApiError as exc:
        return {
            "ok": exc.code == "100000",
            "code": exc.code,
            "tip": (exc.tip or "")[:80],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chapter-id", default=DEFAULT_CHAPTER_ID)
    parser.add_argument(
        "--prefer",
        choices=("node", "ruyidom", "aes-rsa", "node-then-ruyidom"),
        default="node",
    )
    args = parser.parse_args()

    payload = {
        "tested_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "hypothesis": (
            "Node black-box initGeetest bind (no RuyiDOM) "
            "can produce a GT3 triple that stamps get_cpt_ifm"
        ),
        "tokens_json_written": False,
        "web_fallback": False,
        "prefer": args.prefer,
        "origin": "pending",
    }
    session = None
    try:
        creds = asyncio.run(register_guest())
        payload["guest"] = {
            "account_fp": account_fp(creds.account),
            "account_len": len(creds.account),
            "login_token_len": len(creds.login_token),
            "reader_id_last": str(creds.reader_id)[-1:],
        }
        host = base_url_for_reader_id(creds.reader_id)
        session = api.Session(
            creds.login_token,
            creds.account,
            creds.device_token,
            base_url=host,
        )
        payload["host"] = host.split("://", 1)[-1]
        before = _chapter_code(session, args.chapter_id)
        command = before.pop("command", "")
        payload["cpt_before"] = before
        api1 = session.first_register_gt3()
        payload["api1"] = gt3.public_shape(api1)
        provider = gt3_w.FullpageWProvider(prefer=args.prefer)
        try:
            triple = provider.complete_bind(api1)
            payload["bind"] = {
                "ok": True,
                "origin": provider.origin,
                "challenge_len": triple.challenge_len,
                "validate_len": triple.validate_len,
                "seccode_len": triple.seccode_len,
            }
            payload["plane"] = provider.last_public
            if command:
                payload["cpt_retry"] = _retry_code(
                    session, args.chapter_id, command, triple)
            else:
                payload["cpt_retry"] = {"ok": False, "code": "no-command"}
            after = _chapter_code(session, args.chapter_id)
            after.pop("command", None)
            payload["cpt_after"] = after
        except gt3.Gt3Error as exc:
            payload["bind"] = {
                "ok": False,
                "class": type(exc).__name__,
                "error": str(exc)[:200],
            }
            payload["plane"] = provider.last_public
            payload["cpt_after"] = before
        payload["origin"] = (payload.get("bind") or {}).get("origin") or (
            (payload.get("plane") or {}).get("origin") or "failed"
        )
        payload["gt3_solved_by_us"] = bool(
            (payload.get("cpt_after") or {}).get("code") == "100000"
            and (payload.get("cpt_before") or {}).get("code") == "310017"
        )
        payload["ok"] = bool(
            (payload.get("cpt_before") or {}).get("code") == "310017"
            and payload.get("api1", {}).get("success")
        )
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = type(exc).__name__
        tip = str(exc)[:120]
        lowered = tip.lower()
        if any(name in lowered for name in (
                "gt", "challenge", "validate", "token", "account", "w=")):
            tip = "redacted"
        payload["error_tip"] = tip
    finally:
        if session is not None:
            session.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": payload.get("ok"),
        "output": str(args.output),
        "cpt_before": (payload.get("cpt_before") or {}).get("code"),
        "api1_success": (payload.get("api1") or {}).get("success"),
        "bind_ok": (payload.get("bind") or {}).get("ok"),
        "origin": payload.get("origin"),
        "cpt_retry": (payload.get("cpt_retry") or {}).get("code"),
        "cpt_after": (payload.get("cpt_after") or {}).get("code"),
        "gt3_solved_by_us": payload.get("gt3_solved_by_us"),
        "tokens_json_written": False,
    }, ensure_ascii=False, indent=2))
    if payload.get("gt3_solved_by_us"):
        return 0
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
