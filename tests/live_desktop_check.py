"""Interactive GNOME check: requires the human to allow the system portal dialog.

Only this test's own GTK, Chrome and raw terminal receiver get fixed text.
Run: PYTHONPATH=. .venv/bin/python tests/live_desktop_check.py
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

from gi.repository import GLib
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from phone_pad.backend import DesktopBackend
from phone_pad.portal import DesktopPortal


class Check(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="tw.local.PhonePadVerification")
        self.loop = asyncio.new_event_loop()
        self.portal = DesktopPortal()
        original_call = self.portal._call

        async def trace_call(member, *args, **kwargs):
            print(f"Portal call: {member}", flush=True)
            try:
                reply = await original_call(member, *args, **kwargs)
            except BaseException as error:
                print(f"Portal error: {member}: {type(error).__name__}", flush=True)
                raise
            print(f"Portal returned: {member}", flush=True)
            return reply

        self.portal._call = trace_call
        self.backend = DesktopBackend(self.portal)
        self.ok = False

    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self, title="手機手寫板：實機貼上驗證")
        self.window.set_default_size(540, 300)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        self.window.set_child(box)
        self.label = Gtk.Label(label="請在系統對話框允許控制。只會在此測試框貼入測試文字。", wrap=True)
        box.append(self.label)
        self.text = Gtk.TextView()
        self.text.set_vexpand(True)
        box.append(self.text)
        self.window.present()
        self.window.connect("close-request", self.cancel)
        self.tick = GLib.timeout_add(10, self.pump)
        self.task = self.loop.create_task(self.check())

    def cancel(self, *_):
        self.task.cancel()
        return True

    def pump(self):
        self.loop.call_soon(self.loop.stop)
        self.loop.run_forever()
        return GLib.SOURCE_CONTINUE

    async def check(self):
        try:
            await self.portal.authorize()
            print("Live check: keyboard + clipboard permission granted", flush=True)
            self.window.present()
            self.text.grab_focus()
            self.label.set_text("正在測試 Unicode、多行文字與連續貼上…")
            # Wait for the compositor to grant this test window actual focus.
            for _ in range(100):
                if self.window.is_active() and self.text.has_focus():
                    break
                await asyncio.sleep(0.05)
            if not self.window.is_active() or not self.text.has_focus():
                raise RuntimeError("測試視窗未取得焦點；未送出任何按鍵")
            sample = "繁體中文 English 😊\n第二行\n"
            for _ in range(2):
                await self.backend.paste(sample, "normal")
            await asyncio.sleep(0.5)
            buffer = self.text.get_buffer()
            actual = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            assert actual == sample * 2, f"fixed sample mismatch: {actual!r}; active={self.window.is_active()}, focus={self.text.has_focus()}"
            assert self.window.is_active() and self.text.has_focus(), "test window lost focus"
            self.ok = True
            print("Live GNOME GTK paste: Unicode/newlines, consecutive sends, focus retained: PASS", flush=True)
            await self.check_browser()
            await self.check_terminal()
        except (Exception, asyncio.CancelledError) as error:
            self.ok = False
            print(f"Live GNOME GTK paste NOT VERIFIED: {type(error).__name__}: {error}", flush=True)
        finally:
            await self.portal.close()
            GLib.idle_add(self.quit)

    async def check_browser(self):
        from playwright.async_api import async_playwright, expect
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path="/usr/bin/google-chrome",
                headless=False, args=["--ozone-platform=wayland"])
            try:
                page = await browser.new_page()
                await page.set_content('<title>手機手寫板：瀏覽器貼上驗證</title>'
                    '<h1>手機手寫板：瀏覽器貼上驗證</h1><textarea id="target" autofocus rows="10" cols="50"></textarea>')
                await page.bring_to_front()
                await page.locator("#target").focus()
                await page.wait_for_function("document.hasFocus() && document.activeElement.id === 'target'", timeout=15000)
                sample = "瀏覽器 繁體😊\nEnglish\n"
                await self.backend.paste(sample, "normal")
                await expect(page.locator("#target")).to_have_value(sample)
                assert await page.evaluate("document.hasFocus() && document.activeElement.id === 'target'")
                print("Live Chrome paste: Unicode/newlines, focus retained: PASS", flush=True)
            finally:
                await browser.close()

    async def check_terminal(self):
        with tempfile.TemporaryDirectory(prefix="phone-pad-terminal-") as directory:
            output = Path(directory) / "received.json"
            sample = "終端機 繁體😊\nEnglish\n"
            process = await asyncio.create_subprocess_exec("gnome-terminal", "--wait", "--window",
                "--title=手機手寫板：終端機貼上驗證", "--", sys.executable,
                str(Path(__file__).with_name("terminal_receiver.py").resolve()), str(output),
                str(len(sample.encode("utf-8"))), stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            try:
                focus_file = output.with_suffix(".focus")
                print("Terminal check: click the dedicated test terminal if it is not focused", flush=True)
                for _ in range(600):
                    if focus_file.exists() and focus_file.read_text() == "active":
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise RuntimeError("終端機測試視窗未確認取得焦點；未送出文字")
                await self.backend.paste(sample, "terminal")
                for _ in range(100):
                    if output.exists():
                        break
                    await asyncio.sleep(0.05)
                assert output.exists(), "terminal did not receive sample"
                actual = json.loads(output.read_text())["text"]
                # VTE maps pasted line feeds to CR in the terminal stream.
                assert actual.replace("\r\n", "\n").replace("\r", "\n") == sample, repr(actual)
                print("Live GNOME Terminal paste: Ctrl+Shift+V, Unicode/newlines, no extra Enter: PASS", flush=True)
            finally:
                output.with_suffix(".stop").touch()
                if process.returncode is None:
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except TimeoutError:
                        process.terminate()
                        await process.wait()


if __name__ == "__main__":
    app = Check()
    try:
        app.run([])
    finally:
        GLib.source_remove(app.tick)
        app.loop.run_until_complete(app.loop.shutdown_asyncgens())
        app.loop.close()
    raise SystemExit(0 if app.ok else 1)
