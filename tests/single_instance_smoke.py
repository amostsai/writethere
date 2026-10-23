"""Run with xvfb-run; exercises real desktop processes using isolated user data."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(process, port, log):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read().decode())
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.2) as response:
                assert response.status == 200
            if "application initialized; entering event loop" in log.read_text():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Desktop startup timed out")


def main():
    binary = Path(os.environ.get("WRITETHERE_BIN", "dist/writethere")).resolve()
    with tempfile.TemporaryDirectory(prefix="writethere-single-instance-") as folder:
        root = Path(folder)
        config = root / "config/phone-pad"
        config.mkdir(parents=True)
        settings = config / "settings.json"
        log = root / "state/phone-pad/startup.log"
        copied = root / "copy-writethere"
        shutil.copy2(binary, copied)
        first_port = free_port()
        other_port = free_port()
        while other_port == first_port:
            other_port = free_port()
        env = os.environ.copy()
        env.pop("WAYLAND_DISPLAY", None)
        env.update(
            WINIT_UNIX_BACKEND="x11",
            XDG_SESSION_TYPE="x11",
            DBUS_SESSION_BUS_ADDRESS="unix:path=/tmp/writethere-no-test-bus",
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        processes = []
        try:
            settings.write_text(json.dumps({"port": first_port}))
            first = subprocess.Popen([binary], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            processes.append(first)
            wait_ready(first, first_port, log)
            before = log.read_bytes()
            # A different executable path and changed port must not bypass the lock.
            settings.write_text(json.dumps({"port": other_port}))
            for _ in range(3):
                result = subprocess.run([copied], env=env, capture_output=True, timeout=5)
                assert result.returncode == 0, result.stderr.decode()
                assert log.read_bytes() == before
                assert first.poll() is None
            with socket.socket() as sock:
                assert sock.connect_ex(("127.0.0.1", other_port)) != 0
            # SIGKILL skips Rust destructors: the OS must still release the lock.
            first.kill()
            first.wait(timeout=5)
            restarted = subprocess.Popen([copied], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            processes.append(restarted)
            wait_ready(restarted, other_port, log)
            print("Single instance: 3 duplicates blocked, changed port/copy blocked, log preserved, restart after SIGKILL: PASS")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
