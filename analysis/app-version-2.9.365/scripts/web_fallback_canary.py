"""验证公开 Web 章节回退链，并写入脱敏 evidence。

脚本只使用公开章节 ID，不读取 ``tokens.json``，也不会把 Cookie、访问密钥、
密文或正文写入 evidence。它证明的是 Web fallback 的 ``localReproduced`` /
``serverAccepted``，不改变 App ``get_cpt_ifm`` 的 310017 结论。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.web import WebChapterSession  # noqa: E402


DEFAULT_CHAPTER_ID = "112001971"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analysis"
    / "app-version-2.9.365"
    / "evidence"
    / "web-fallback-canary.json"
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(chapter_id: str, output: Path, *, proxy: str | None,
        min_interval: float, impersonate: str | None) -> int:
    started = datetime.now(timezone.utc)
    session = WebChapterSession(
        proxy=proxy,
        min_interval=min_interval,
        impersonate=impersonate,
    )
    try:
        result = session.fetch_chapter(chapter_id)
        payload = {
            "schema": "ciweimao-web-fallback-canary.v1",
            "captured_at": started.isoformat(timespec="seconds"),
            "ok": True,
            "source": "public_web",
            "chapter_id": str(chapter_id),
            "app_protocol_gate": {
                "status": "separate",
                "known_code": "310017",
                "note": "Web success does not promote App get_cpt_ifm to serverAccepted",
            },
            "request_log": session.request_log,
            "access_key_length": len(result.access_key),
            "encrypted_html_length": len(result.html),
            "normalized_text_length": len(result.text),
            "normalized_text_sha256": _sha256(result.text),
            "cookie_names": sorted(str(key) for key in result.cookies),
            "cookie_change_names": sorted({
                str(name)
                for change in session.cookie_changes
                for name in change
            }),
            "redaction": {
                "sensitive_values_written": False,
                "omitted": [
                    "chapter_access_key",
                    "Cookie",
                    "Set-Cookie values",
                    "chapter_content",
                    "decrypted HTML/body",
                ],
            },
        }
    except Exception as exc:  # pragma: no cover - exercised by live canary
        payload = {
            "schema": "ciweimao-web-fallback-canary.v1",
            "captured_at": started.isoformat(timespec="seconds"),
            "ok": False,
            "source": "public_web",
            "chapter_id": str(chapter_id),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc)[:240],
                "stage": getattr(exc, "stage", ""),
                "code": getattr(exc, "code", None),
                "status_code": getattr(exc, "status_code", None),
            },
            "request_log": session.request_log,
            "redaction": {"sensitive_values_written": False},
        }
    finally:
        session.close()

    _write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ciweimao Web fallback canary")
    parser.add_argument("--chapter-id", default=DEFAULT_CHAPTER_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default=os.getenv("CIWEIMAO_WEB_PROXY") or None)
    parser.add_argument("--min-interval", type=float, default=0.0)
    parser.add_argument("--impersonate", default="chrome136")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    return run(
        str(args.chapter_id),
        output,
        proxy=args.proxy,
        min_interval=max(0.0, args.min_interval),
        impersonate=args.impersonate or None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
