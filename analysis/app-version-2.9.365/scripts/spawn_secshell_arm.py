"""Spawn the App with the SecShell ARM redirect agent and wait."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import frida
import frida_tools

ROOT = Path(__file__).resolve().parent
AGENT = ROOT / "secshell_arm_frida_agent.js"
BRIDGES = Path(frida_tools.__file__).resolve().parent / "bridges"


def _post_bridge(script: frida.core.Script, payload: dict) -> None:
    stem = str(payload.get("name", "")).lower()
    bridge = next(p for p in BRIDGES.glob("*.js") if p.stem == stem)
    script.post(
        {
            "type": "frida:bridge-loaded",
            "filename": bridge.name,
            "source": bridge.read_text(encoding="utf-8"),
        }
    )
    print("[*] loaded bridge", bridge.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="emulator-5574")
    parser.add_argument("--package", default="com.kuangxiangciweimao.novel")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    source = AGENT.read_text(encoding="utf-8")
    device = frida.get_device(args.device, timeout=10)
    print("[*] spawn", args.package, "on", device.id)
    pid = device.spawn([args.package])
    print("[*] pid", pid)
    session = device.attach(pid)
    script_holder: dict = {}

    def on_message(message, data):
        del data
        payload = message.get("payload") if isinstance(message, dict) else None
        if isinstance(payload, dict) and payload.get("type") == "frida:load-bridge":
            _post_bridge(script_holder["script"], payload)
            return
        print("[msg]", message)

    try:
        script = session.create_script(source, runtime="v8")
    except TypeError:
        script = session.create_script(source)
    script_holder["script"] = script
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            session._impl
        except Exception:
            print("[!] session lost")
            break
    print("[*] wait done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
