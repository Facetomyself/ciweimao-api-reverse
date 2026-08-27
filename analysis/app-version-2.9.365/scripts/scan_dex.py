from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import frida

DEVICE = "emulator-5574"
AGENT = Path(__file__).with_name("scan_dex_agent.js")
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "dumps" / "dex-scan.json"


def main() -> int:
    pid = int(sys.argv[1])
    hits = []

    def on_message(message, data):
        del data
        print("[msg]", message.get("type"), message.get("payload") if message.get("type") == "send" else message)
        if message.get("type") == "send" and isinstance(message.get("payload"), dict):
            hits.extend(message["payload"].get("hits") or [])

    device = frida.get_device(DEVICE, timeout=10)
    session = device.attach(pid)
    script = session.create_script(AGENT.read_text(encoding="utf-8"))
    script.on("message", on_message)
    script.load()
    time.sleep(6)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"pid": pid, "hits": hits}, indent=2) + "\n", encoding="utf-8")
    print("[*] wrote", OUT, "hits", len(hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
