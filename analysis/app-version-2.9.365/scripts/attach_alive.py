from __future__ import annotations

import sys
import time
from pathlib import Path

import frida

DEVICE = "emulator-5574"
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 2757
AGENT = Path(__file__).with_name("attach_alive_agent.js")


def main() -> int:
    device = frida.get_device(DEVICE, timeout=10)
    print("[*] attach", PID)
    session = device.attach(PID)
    source = AGENT.read_text(encoding="utf-8")
    try:
        script = session.create_script(source, runtime="v8")
    except TypeError:
        script = session.create_script(source)
    script.on("message", lambda message, data: print("[msg]", message))
    script.load()
    time.sleep(8)
    print("[*] attach wait done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
