"""GTK remains on the main thread; GLib ticks the asyncio loop without blocking."""

import asyncio
import shutil
import signal
import sys
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk
import qrcode

from .runtime import Runtime


def qr_texture(url):
    code = qrcode.QRCode(box_size=4, border=4)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = 4
    width = len(matrix) * scale
    pixels = b"".join(b"".join((b"\0\0\0" if dark else b"\xff\xff\xff") * scale
                              for dark in row) * scale for row in matrix)
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixels),
        GdkPixbuf.Colorspace.RGB, False, 8, width, width, width * 3)
    return Gdk.Texture.new_for_pixbuf(pixbuf)


class PadWindow(Gtk.ApplicationWindow):
    def __init__(self, app, runtime):
        super().__init__(application=app, title="手機手寫板")
        self.runtime = runtime
        self.options = []
        self.current_url = ""
        self.set_default_size(420, 680)
        self.set_resizable(False)
        self.set_icon_name("input-tablet-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for prop in ("margin-top", "margin-bottom", "margin-start", "margin-end"):
            box.set_property(prop, 20)
        self.set_child(box)
        title = Gtk.Label(label="手機手寫板", xalign=0)
        title.add_css_class("title-1")
        box.append(title)
        subtitle = Gtk.Label(label="手機掃碼，寫好後傳到電腦游標所在的位置。", xalign=0, wrap=True)
        subtitle.add_css_class("dim-label")
        box.append(subtitle)
        self.service_label = Gtk.Label(label="正在啟動區網服務…", xalign=0, wrap=True)
        box.append(self.service_label)
        port_row = Gtk.Box(spacing=8)
        self.port_entry = Gtk.Entry(text=str(runtime.configured_port), max_length=5,
                                    input_purpose=Gtk.InputPurpose.DIGITS)
        self.port_entry.set_hexpand(True)
        port_label = Gtk.Label(label="連接埠")
        port_label.set_mnemonic_widget(self.port_entry)
        port_row.append(port_label)
        port_row.append(self.port_entry)
        self.save_port = Gtk.Button(label="儲存")
        self.save_port.connect("clicked", self._save_port)
        self.port_entry.connect("activate", self._save_port)
        port_row.append(self.save_port)
        box.append(port_row)
        self.settings_label = Gtk.Label(label="", xalign=0, wrap=True)
        self.settings_label.add_css_class("caption")
        box.append(self.settings_label)
        row = Gtk.Box(spacing=8)
        self.address = Gtk.DropDown(model=Gtk.StringList.new([]))
        self.address.set_hexpand(True)
        self.address.connect("notify::selected", self._address_changed)
        row.append(self.address)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="重新偵測區網位址")
        refresh.connect("clicked", lambda _: app.schedule(runtime.refresh_network()))
        row.append(refresh)
        box.append(row)
        self.qr = Gtk.Picture()
        self.qr.set_size_request(210, 210)
        self.qr.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.qr.set_can_shrink(True)
        box.append(self.qr)
        self.url_label = Gtk.Label(label="", selectable=True, wrap=True)
        self.url_label.set_max_width_chars(44)
        self.url_label.add_css_class("caption")
        box.append(self.url_label)
        self.code_label = Gtk.Label(label="")
        self.code_label.add_css_class("title-2")
        self.code_label.set_selectable(True)
        box.append(self.code_label)
        self.auth_label = Gtk.Label(label="", xalign=0, wrap=True)
        box.append(self.auth_label)
        self.phone_label = Gtk.Label(label="等待手機連線", xalign=0)
        self.phone_label.add_css_class("dim-label")
        box.append(self.phone_label)
        self.disconnect_phone = Gtk.Button(label="中斷手機連線／更新驗證碼")
        self.disconnect_phone.connect("clicked", lambda _: app.schedule(runtime.service.disconnect()))
        box.append(self.disconnect_phone)
        note = Gtk.Label(label="傳送會取代剪貼簿內容。手機與電腦須在同一區網。\n請保持此視窗開啟；接收文字時不會搶走焦點。", xalign=0, wrap=True)
        note.add_css_class("caption")
        box.append(note)
        buttons = Gtk.Box(spacing=10, homogeneous=True)
        self.retry = Gtk.Button(label="重新授權")
        self.retry.connect("clicked", lambda _: runtime.authorize())
        buttons.append(self.retry)
        stop = Gtk.Button(label="停止並關閉")
        stop.add_css_class("destructive-action")
        stop.connect("clicked", lambda _: app.stop())
        buttons.append(stop)
        box.append(buttons)
        self.connect("close-request", lambda _: app.stop())

    def _save_port(self, *_):
        if self.runtime.save_port(self.port_entry.get_text()):
            self.port_entry.set_text(str(self.runtime.configured_port))

    def _address_changed(self, *_):
        selected = self.address.get_selected()
        if selected >= len(self.options) or not self.runtime.service.port:
            url = ""
        else:
            ip = self.options[selected][1]
            url = f"http://{ip}:{self.runtime.service.port}/#token={self.runtime.service.token}"
        if url != self.current_url:
            self.current_url = url
            self.qr.set_paintable(qr_texture(url) if url else None)
            self.url_label.set_text(url)

    def refresh(self):
        runtime = self.runtime
        if runtime.addresses != self.options:
            previous = self.options[self.address.get_selected()][1] if self.address.get_selected() < len(self.options) else None
            self.options = list(runtime.addresses)
            self.address.set_model(Gtk.StringList.new([label for label, _ in self.options]))
            selected = next((i for i, (_, ip) in enumerate(self.options) if ip == previous), 0)
            self.address.set_selected(selected)
        self._address_changed()
        message = runtime.error or runtime.network_error or ("區網服務已啟動" if runtime.service.port else "正在啟動區網服務…")
        if not self.options and not runtime.error and not runtime.network_error:
            message = "尚未找到區網 IPv4 位址，連上 Wi-Fi 或有線網路後按重新偵測"
        self.service_label.set_text(message)
        self.settings_label.set_text(runtime.settings_message or "儲存後於下次啟動套用")
        self.auth_label.set_text(runtime.portal.status)
        self.retry.set_sensitive(not runtime.stopping and runtime.service.port is not None and
            (runtime.auth_task is None or runtime.auth_task.done()))
        active = runtime.service.session_active
        self.code_label.set_text(f"配對驗證碼：{runtime.service.pairing_code}")
        self.disconnect_phone.set_sensitive(active and not runtime.stopping)
        seen = runtime.service.last_seen
        age = int(time.monotonic() - seen) if seen else None
        self.phone_label.set_text("手機已連線（限一支）" if active and age is not None and age < 15 else
            "手機暫時離線，30 秒後釋放連線" if active else "等待手機輸入驗證碼配對")


class PadApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="tw.local.PhoneHandwritingPad",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.loop = asyncio.new_event_loop()
        self.runtime = Runtime(on_change=self.refresh)
        self.window = None
        self.tasks = set()
        self.closing = False
        self.tick_id = None
        self.status_id = None

    def schedule(self, coroutine):
        task = self.loop.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception():
            self.runtime.error = "工具發生錯誤，請關閉後重新啟動"
            self.refresh()

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        self.window = PadWindow(self, self.runtime)
        self.window.present()
        self.tick_id = GLib.timeout_add(10, self._tick)
        self.status_id = GLib.timeout_add_seconds(2, self.refresh)
        self.schedule(self.runtime.start())

    def _tick(self):
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        if self.window and not self.closing:
            self.window.refresh()
        return GLib.SOURCE_CONTINUE

    def stop(self):
        if not self.closing:
            self.closing = True
            self.window.set_sensitive(False)
            self.schedule(self._stop())
        return True

    async def _stop(self):
        try:
            for task in list(self.tasks):
                if task is not asyncio.current_task():
                    task.cancel()
            await self.runtime.stop()
        finally:
            GLib.idle_add(self.quit)

    def dispose_loop(self):
        for source in (self.tick_id, self.status_id):
            if source:
                GLib.source_remove(source)
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.close()


def main():
    if not shutil.which("ip"):
        print("缺少 ip；請先安裝 iproute2。", file=sys.stderr)
        return 1
    app = PadApplication()
    signal.signal(signal.SIGINT, lambda *_: app.stop() if app.window else app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.stop() if app.window else app.quit())
    try:
        return app.run(sys.argv)
    finally:
        app.dispose_loop()
