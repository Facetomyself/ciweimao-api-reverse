"""对照 fullpage 9.2.0 官方 w 外形，试三种 packing。只打 ajax，不写 tokens。"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client import api, config, gt3, gt3_w  # noqa: E402
from client.guest import register_guest  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analysis"
    / "app-version-2.9.365"
    / "evidence"
    / "gt3-w-pack-canary.json"
)


def base_url_for_reader_id(reader_id: str) -> str:
    last = str(reader_id or "")[-1:]
    if last.isdigit() and 1 <= int(last) <= 5:
        return config.CURRENT_BASE_URL
    return "https://app1.hbooker.com"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = {
        "tested_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "hypothesis": (
            "9.2.0 official w is GeeTest-alphabet throughout; "
            "b64-hex RSA tail causes error_03"
        ),
        "tokens_json_written": False,
        "official_w_shape": {
            "len": 1240,
            "body_len": 984,
            "rsa_hex_ok": False,
            "alphabet_ok": True,
            "has_paren": True,
            "source": "gt3-w-shape-canary.json",
        },
        "modes": [],
    }
    session = None
    try:
        creds = asyncio.run(register_guest())
        host = base_url_for_reader_id(creds.reader_id)
        session = api.Session(
            creds.login_token, creds.account, creds.device_token, base_url=host)
        for mode in gt3_w.PACK_MODES:
            api1 = session.first_register_gt3()
            api_host = gt3_w.DEFAULT_API_HOSTS[0]
            _type_plane, type_data = gt3_w.fetch_jsonp(
                api_host, "/gettype.php", gt3_w.gettype_query(api1))
            get_plane, get_data = gt3_w.fetch_jsonp(
                api_host, "/get.php",
                gt3_w.getphp_query(api1, client_type="native"))
            ajax_host = gt3_w.pick_api_host(get_data, type_data)
            w_value = gt3_w.pack_w(
                gt3_w.fullpage_ajax_plaintext(api1, client_type="native"),
                mode=mode,
            )
            ajax_plane, _ajax = gt3_w.fetch_jsonp(
                ajax_host, "/ajax.php",
                gt3_w.ajax_query(api1, w_value, client_type="native"))
            payload["modes"].append({
                "mode": mode,
                "w": gt3_w.w_public_shape(w_value),
                "get_ok": get_plane.ok,
                "ajax_host": ajax_host.split("://", 1)[-1],
                "ajax": gt3_w.plane_public(ajax_plane),
            })
        payload["ok"] = True
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = type(exc).__name__
        tip = str(exc)[:80]
        if any(name in tip.lower() for name in ("gt", "challenge", "w=", "token")):
            tip = "redacted"
        payload["error_tip"] = tip
    finally:
        if session is not None:
            session.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": payload.get("ok"),
        "output": str(args.output),
        "modes": [
            {
                "mode": item["mode"],
                "w_len": item["w"]["len"],
                "rsa_hex_ok": item["w"]["rsa_hex_ok"],
                "ajax_label": item["ajax"].get("label"),
            }
            for item in payload.get("modes", [])
        ],
        "tokens_json_written": False,
    }, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
