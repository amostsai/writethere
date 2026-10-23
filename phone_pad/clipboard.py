"""Portal selection ownership: no temporary surface or keyboard focus needed."""

import asyncio
from contextlib import suppress
import os

from dbus_next import Variant

INTERFACE = "org.freedesktop.portal.Clipboard"
MIME_TYPES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"]


async def write_fd(fd, data):
    os.set_blocking(fd, False)
    view = memoryview(data)
    loop = asyncio.get_running_loop()
    while view:
        try:
            count = os.write(fd, view)
            view = view[count:]
        except BlockingIOError:
            writable = loop.create_future()

            def wake():
                if not writable.done():
                    writable.set_result(None)

            loop.add_writer(fd, wake)
            try:
                await writable
            finally:
                loop.remove_writer(fd)


class PortalClipboard:
    def __init__(self, portal):
        self.portal = portal
        # Only the current clipboard selection is retained, never text history.
        self.data = None
        self.tasks = set()

    async def set_text(self, text):
        if not self.portal.ready:
            raise RuntimeError("尚未取得剪貼簿授權")
        self.data = text.encode("utf-8")
        try:
            await self.portal._call("SetSelection", "oa{sv}", [self.portal.session,
                {"mime_types": Variant("as", MIME_TYPES)}], interface=INTERFACE)
        except BaseException:
            self.data = None
            raise

    def signal(self, message):
        if message.interface != INTERFACE or not message.body or message.body[0] != self.portal.session:
            return
        if message.member == "SelectionOwnerChanged":
            owner = message.body[1].get("session_is_owner")
            if owner is not None and not owner.value:
                self.data = None
        elif message.member == "SelectionTransfer":
            session, mime, serial = message.body
            # Capture the bytes now, before a later selection replaces them.
            task = asyncio.create_task(self.transfer(session, mime, serial, self.data))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def transfer(self, session, mime, serial, data):
        success = False
        fd = None
        try:
            if data is not None and mime in MIME_TYPES:
                reply = await self.portal._call("SelectionWrite", "ou", [session, serial],
                    interface=INTERFACE, return_message=True)
                fd = reply.unix_fds[reply.body[0]]
                await asyncio.wait_for(write_fd(fd, data), timeout=5)
                success = True
        except Exception:
            pass  # Failure is returned through SelectionWriteDone; never log text.
        finally:
            if fd is not None:
                os.close(fd)
            with suppress(Exception):
                await self.portal._call("SelectionWriteDone", "oub", [session, serial, success],
                                        interface=INTERFACE)

    def reset(self):
        self.data = None
        for task in list(self.tasks):
            task.cancel()

    async def close(self):
        tasks = list(self.tasks)
        self.reset()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
