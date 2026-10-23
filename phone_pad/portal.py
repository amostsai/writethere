"""Keyboard-only RemoteDesktop portal, using a persistent D-Bus connection."""

import asyncio
from contextlib import suppress
import secrets

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

from .clipboard import PortalClipboard

DEST = "org.freedesktop.portal.Desktop"
ROOT = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"


class PortalError(RuntimeError):
    pass


class DesktopPortal:
    def __init__(self, bus=None, on_change=lambda: None):
        self.bus = bus
        self.on_change = on_change
        self.ready = False
        self.status = "尚未取得鍵盤控制授權"
        self.session = None
        self.pending = {}
        self.initialized = False
        self.disconnect_task = None
        self.auth_lock = asyncio.Lock()
        self.clipboard = PortalClipboard(self)

    def _state(self, ready, message):
        self.ready, self.status = ready, message
        self.on_change()

    async def _call(self, member, signature="", body=None, interface=REMOTE, path=ROOT,
                    return_message=False):
        reply = await asyncio.wait_for(self.bus.call(Message(
            destination=DEST, path=path, interface=interface, member=member,
            signature=signature, body=body or [])), timeout=15)
        if reply is None or reply.message_type == MessageType.ERROR:
            raise PortalError("桌面控制介面呼叫失敗")
        return reply if return_message else reply.body

    def _signal(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        self.clipboard.signal(message)
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future and not future.done():
                future.set_result(message.body)
        elif (message.interface == "org.freedesktop.portal.Session" and
              message.member == "Closed" and message.path == self.session):
            self._invalidate("鍵盤控制授權已撤銷，請在電腦重新授權")
        elif (message.interface == "org.freedesktop.DBus" and
              message.member == "NameOwnerChanged" and message.body[0] == DEST and message.body[1]):
            self._invalidate("桌面控制服務已重新啟動或中斷，請重新授權")

    def _invalidate(self, message):
        self.clipboard.reset()
        self.session = None
        self._state(False, message)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(PortalError(message))

    async def _watch_disconnect(self):
        try:
            await self.bus.wait_for_disconnect()
        except Exception:
            pass
        finally:
            self.initialized = False
            self._invalidate("桌面連線已中斷，請重新授權")

    async def _connect(self):
        if self.initialized:
            return
        if self.bus is None or getattr(self.bus, "connected", True) is False:
            self.bus = await MessageBus(negotiate_unix_fd=True).connect()
        self.bus.add_message_handler(self._signal)
        rules = [f"type='signal',sender='{DEST}',path_namespace='{ROOT}'",
                 "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
                 f"member='NameOwnerChanged',arg0='{DEST}'"]
        for rule in rules:
            reply = await self.bus.call(Message(destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus", interface="org.freedesktop.DBus",
                member="AddMatch", signature="s", body=[rule]))
            if reply.message_type == MessageType.ERROR:
                raise PortalError("無法監聽桌面授權狀態")
        self.initialized = True
        if hasattr(self.bus, "wait_for_disconnect"):
            self.disconnect_task = asyncio.create_task(self._watch_disconnect())

    async def _request(self, member, signature, body, options):
        token = "pad_" + secrets.token_hex(12)
        sender = self.bus.unique_name[1:].replace(".", "_")
        path = f"{ROOT}/request/{sender}/{token}"
        future = asyncio.get_running_loop().create_future()
        self.pending[path] = future
        returned_path = path
        options = {**options, "handle_token": Variant("s", token)}
        try:
            returned_path = (await self._call(member, signature, [*body, options]))[0]
            if returned_path != path:
                self.pending[returned_path] = future
            code, results = await asyncio.wait_for(future, timeout=120)
            if code != 0:
                raise PortalError("鍵盤控制未授權，請按「重新授權」再試一次")
            return {key: value.value for key, value in results.items()}
        except (TimeoutError, asyncio.CancelledError):
            with suppress(Exception):
                await self._call("Close", interface="org.freedesktop.portal.Request", path=returned_path)
            raise
        finally:
            self.pending.pop(path, None)
            self.pending.pop(returned_path, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # Consume errors if the method call failed first.

    async def authorize(self):
        async with self.auth_lock:
            self._state(False, "等待桌面授權，請在電腦確認系統對話框")
            try:
                await self._connect()
                await self._close_session()
                result = await self._request("CreateSession", "a{sv}", [], {
                    "session_handle_token": Variant("s", "pad_" + secrets.token_hex(12))})
                self.session = result["session_handle"]
                await self._request("SelectDevices", "oa{sv}", [self.session], {"types": Variant("u", 1)})
                await self._call("RequestClipboard", "oa{sv}", [self.session, {}],
                                 interface="org.freedesktop.portal.Clipboard")
                result = await self._request("Start", "osa{sv}", [self.session, ""], {})
                if not result.get("devices", 0) & 1 or self.session is None:
                    raise PortalError("系統未授予鍵盤控制權限")
                if not result.get("clipboard_enabled", False):
                    raise PortalError("系統未授予剪貼簿權限，請重新授權")
                self._state(True, "已授權，可以傳送文字")
            except Exception as error:
                await self._close_session()
                message = str(error) if isinstance(error, PortalError) else "無法取得桌面授權，請確認 GNOME Portal 正常運作後重試"
                self._state(False, message)
                raise PortalError(message) from error

    async def shortcut(self, mode):
        if not self.ready or not self.session:
            raise PortalError("尚未取得鍵盤控制授權")
        if mode not in ("normal", "terminal"):
            raise ValueError("unknown paste mode")
        session = self.session
        keys = [0xFFE3] + ([0xFFE1] if mode == "terminal" else []) + [0x76]
        pressed = []
        failed = False
        try:
            for key in keys:
                # Track before awaiting: a lost reply may still have delivered the press.
                pressed.append(key)
                await self._call("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, key, 1])
        except Exception:
            failed = True
            raise
        finally:
            for key in reversed(pressed):
                try:
                    await self._call("NotifyKeyboardKeysym", "oa{sv}iu", [session, {}, key, 0])
                except Exception:
                    failed = True
            if failed:
                self._state(False, "鍵盤控制失敗，請重新授權；先查看電腦的貼上結果")
        if failed:
            raise PortalError(self.status)

    async def _close_session(self):
        await self.clipboard.close()
        session, self.session = self.session, None
        if session and self.bus:
            with suppress(Exception):
                await self._call("Close", interface="org.freedesktop.portal.Session", path=session)

    async def close(self):
        self._state(False, "服務已停止")
        await self._close_session()
        if self.disconnect_task:
            self.disconnect_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.disconnect_task
        if self.bus:
            self.bus.disconnect()
