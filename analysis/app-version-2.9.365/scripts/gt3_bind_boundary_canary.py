"""冻结官方 GT3 bind 的只读边界：API1 + gettype/get 键名。

不写 tokens.json，不 POST ajax.php，不提交假三元组，不打印 gt/challenge。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client import api, config, gt3  # noqa: E402
from client.api import ApiError  # noqa: E402
from client.guest import register_guest  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analysis"
    / "app-version-2.9.365"
    / "evidence"
    / "gt3-bind-boundary-canary.json"
)
DEFAULT_CHAPTER_ID = "106129841"
PROBE_HOSTS = (
    "http://103.143.17.166",
    "https://api.geetest.com",
    "https://api.geevisit.com",
)


def account_fp(account: str) -> str:
    return hashlib.sha256(str(account).encode("utf-8")).hexdigest()[:12]


def base_url_for_reader_id(reader_id: str) -> str:
    last = str(reader_id or "")[-1:]
    if last.isdigit() and 1 <= int(last) <= 5:
        return config.CURRENT_BASE_URL
    return "https://app1.hbooker.com"


def _probe_get(host: str, path: str, query: dict) -> dict:
    rec = {
        "host_class": "ip" if host.split("://", 1)[-1][0].isdigit() else "name",
        "scheme": host.split(":", 1)[0],
        "path": path,
        "query_keys": sorted(query),
    }
    url = f"{host.rstrip('/')}{path}?{urlencode(query)}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "*/*", "User-Agent": config.USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            rec["http_code"] = int(resp.status)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        rec["http_code"] = int(exc.code)
        rec["error"] = "http-error"
    except URLError as exc:
        rec["ok"] = False
        rec["error"] = type(exc.reason).__name__ if exc.reason else "URLError"
        return rec
    except Exception as exc:
        rec["ok"] = False
        rec["error"] = type(exc).__name__
        return rec
    rec["ok"] = rec.get("http_code") == 200
    rec["resp_len"] = len(raw)
    stripped = raw.strip()
    rec["resp_class"] = (
        "jsonp" if stripped.startswith("geetest_")
        else "json" if stripped.startswith("{")
        else "other"
    )
    try:
        data = gt3.parse_geetest_jsonp(raw)
        rec["response"] = gt3.public_json_shape(data)
    except Exception as exc:
        rec["parse"] = type(exc).__name__
    return rec


def _chapter_code(session: api.Session, chapter_id: str) -> dict:
    try:
        command = session.get_chapter_command(chapter_id)
    except ApiError as exc:
        return {"ok": False, "code": exc.code, "tip": (exc.tip or "")[:80]}
    try:
        session.get_chapter_content(chapter_id, command)
        return {"ok": True, "code": "100000", "chapter_id_len": len(chapter_id)}
    except ApiError as exc:
        return {
            "ok": exc.code == "100000",
            "code": exc.code,
            "tip": (exc.tip or "")[:80],
            "chapter_id_len": len(chapter_id),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chapter-id", default=DEFAULT_CHAPTER_ID)
    args = parser.parse_args()

    payload = {
        "tested_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "hypothesis": (
            "Python first_register plus gettype/get key shapes can be frozen "
            "without ajax.php or official App oracle"
        ),
        "tokens_json_written": False,
        "ajax_posted": False,
        "web_fallback": False,
        "gt3_solved_by_us": False,
        "origin": "algorithmic-pending",
        "api1_path": gt3.API1_PATH,
        "retry_keys": list(gt3.RETRY_KEYS),
        "gt3_paths": list(gt3.GT3_PATHS),
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
        payload["cpt_before"] = _chapter_code(session, args.chapter_id)
        api1 = session.first_register_gt3()
        payload["api1"] = gt3.public_shape(api1)
        try:
            session.bind_gt3()
            payload["bind"] = {"raised": False}
        except gt3.Gt3BindNotReady:
            payload["bind"] = {"raised": True, "class": "Gt3BindNotReady"}
        probes = []
        if api1.success:
            # get.php 会消耗 challenge，先冻 gettype，再只打一次 get。
            for host_url in PROBE_HOSTS:
                probes.append(_probe_get(host_url, "/gettype.php", {
                    "gt": api1.gt,
                    "callback": "geetest_1",
                }))
            probes.append(_probe_get(
                "https://api.geetest.com",
                "/get.php",
                {
                    "gt": api1.gt,
                    "challenge": api1.challenge,
                    "lang": "zh-cn",
                    "pt": "0",
                    "client_type": "native",
                    "callback": "geetest_1",
                },
            ))
        payload["probes"] = probes
        payload["ok"] = bool(
            payload["cpt_before"].get("code") == "310017"
            and payload["api1"].get("success")
            and payload["bind"].get("raised")
        )
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = type(exc).__name__
        payload["error_tip"] = str(exc)[:120]
        if any(name in payload["error_tip"].lower() for name in (
                "gt", "challenge", "validate", "token", "account")):
            payload["error_tip"] = "redacted"
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
        "cpt_before": payload.get("cpt_before", {}).get("code"),
        "api1_success": (payload.get("api1") or {}).get("success"),
        "bind_not_ready": (payload.get("bind") or {}).get("raised"),
        "probe_count": len(payload.get("probes") or []),
        "tokens_json_written": False,
        "ajax_posted": False,
    }, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
