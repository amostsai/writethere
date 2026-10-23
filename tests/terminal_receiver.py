"""Raw terminal receiver for fixed integration-test text; never runs commands."""
import json
import os
from pathlib import Path
import select
import sys
import termios
import time
import tty

output = Path(sys.argv[1])
expected_size = int(sys.argv[2])
focus_file = output.with_suffix(".focus")
fd = sys.stdin.fileno()
previous = termios.tcgetattr(fd)
wire = b""
try:
    print("手機手寫板：終端機貼上驗證\r\n請點選此測試視窗。只接收固定範例，不會執行指令。", flush=True)
    tty.setraw(fd)
    sys.stdout.write("\x1b[?1004h\x1b[?2004h")
    sys.stdout.flush()
    output.with_suffix(".ready").write_text("ready")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not output.with_suffix(".stop").exists():
        if not select.select([fd], [], [], 0.1)[0]:
            continue
        data = os.read(fd, 4096)
        if not data:
            break
        wire += data
        focus_in, focus_out = wire.rfind(b"\x1b[I"), wire.rfind(b"\x1b[O")
        if max(focus_in, focus_out) >= 0:
            focus_file.write_text("active" if focus_in > focus_out else "inactive")
        clean = wire
        for marker in [b"\x1b[I", b"\x1b[O", b"\x1b[200~", b"\x1b[201~"]:
            clean = clean.replace(marker, b"")
        if len(clean) >= expected_size:
            output.write_text(json.dumps({"text": clean.decode("utf-8")}, ensure_ascii=False))
            break
finally:
    sys.stdout.write("\x1b[?1004l\x1b[?2004l")
    sys.stdout.flush()
    termios.tcsetattr(fd, termios.TCSANOW, previous)
