"""Run under a private Xvfb session; no real desktop control is requested."""
from pathlib import Path
import subprocess
from types import SimpleNamespace

from phone_pad.desktop import GLib, PadApplication


class Runtime:
    def __init__(self):
        self.addresses = [("wlan0 · 192.168.1.5", "192.168.1.5"),
                          ("eth0 · 10.0.0.5", "10.0.0.5")]
        self.service = SimpleNamespace(port=8765, token="smoke-test-credential", last_seen=0,
                                       pairing_code="123456", session_active=False)
        self.portal = SimpleNamespace(status="已授權，可以傳送文字")
        self.error = ""
        self.network_error = ""
        self.auth_task = None
        self.stopping = False
        self.stopped = False
        self.configured_port = 39945
        self.settings_message = ""

    async def start(self):
        pass

    async def refresh_network(self):
        pass

    def authorize(self):
        pass

    def save_port(self, value):
        self.configured_port = int(value)
        self.settings_message = f"已儲存連接埠 {value}，下次啟動套用"
        return True

    async def stop(self):
        self.stopped = True


app = PadApplication()
app.set_application_id("tw.local.PhonePadDesktopSmoke")
runtime = Runtime()
app.runtime = runtime
failures = []


def check():
    try:
        app.refresh()
        assert "192.168.1.5" in app.window.current_url
        assert app.window.qr.get_paintable() is not None
        assert "123456" in app.window.code_label.get_text()
        assert app.window.port_entry.get_text() == "39945"
        app.window.port_entry.set_text("45678")
        app.window.save_port.emit("clicked")
        app.refresh()
        assert "45678" in app.window.settings_label.get_text()
        assert ":8765/" in app.window.current_url
        app.window.address.set_selected(1)
        assert "10.0.0.5" in app.window.current_url
        app.window.address.set_selected(0)
    except BaseException as error:
        failures.append(error)
    GLib.timeout_add(500, capture_and_close)
    return GLib.SOURCE_REMOVE


def capture_and_close():
    try:
        Path("artifacts").mkdir(exist_ok=True)
        crop = f"{app.window.get_width()}x{app.window.get_height()}+0+0"
        subprocess.run(["import", "-window", "root", "-crop", crop,
                        "artifacts/desktop.png"], check=True, timeout=10)
        runtime.portal.status = "鍵盤控制授權已撤銷"
        app.refresh()
        assert app.window.auth_label.get_text() == runtime.portal.status
    except BaseException as error:
        failures.append(error)
    app.stop()
    return GLib.SOURCE_REMOVE


GLib.timeout_add(1200, check)
try:
    app.run([])
finally:
    app.dispose_loop()
assert not failures, failures
assert runtime.stopped
print("GTK smoke: QR rendering, IP switching, status updates, graceful close: PASS")
