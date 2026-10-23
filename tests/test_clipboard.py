import asyncio
import os

import pytest
from dbus_next import Message, MessageType, Variant

from phone_pad.clipboard import PortalClipboard


class Portal:
    ready = True
    session = "/session"

    def __init__(self):
        self.calls = []
        self.read_fd, self.write_fd = os.pipe()

    async def _call(self, member, signature, body, **kwargs):
        self.calls.append((member, body))
        if member == "SelectionWrite":
            return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1,
                           signature="h", body=[0], unix_fds=[self.write_fd])
        return []


async def test_advertises_text_and_writes_exact_utf8_to_real_pipe():
    portal = Portal()
    clipboard = PortalClipboard(portal)
    text = "  中文😊\n第二行\n"
    try:
        await clipboard.set_text(text)
        assert portal.calls[0][0] == "SetSelection"
        types = portal.calls[0][1][1]["mime_types"].value
        assert "text/plain;charset=utf-8" in types
        await clipboard.transfer(portal.session, "text/plain;charset=utf-8", 7, clipboard.data)
        assert os.read(portal.read_fd, 4096) == text.encode("utf-8")
        assert portal.calls[-1] == ("SelectionWriteDone", ["/session", 7, True])
    finally:
        os.close(portal.read_fd)


async def test_large_transfer_does_not_block_the_event_loop():
    portal = Portal()
    clipboard = PortalClipboard(portal)
    text = "繁體😊" * 20000
    await clipboard.set_text(text)
    os.set_blocking(portal.read_fd, False)
    received = bytearray()

    async def consume():
        while True:
            try:
                chunk = os.read(portal.read_fd, 4096)
            except BlockingIOError:
                await asyncio.sleep(0)
                continue
            if not chunk:
                break
            received.extend(chunk)

    try:
        await asyncio.wait_for(asyncio.gather(consume(), clipboard.transfer(
            portal.session, "text/plain", 8, clipboard.data)), timeout=3)
        assert received == text.encode()
    finally:
        os.close(portal.read_fd)


async def test_losing_ownership_releases_current_clipboard_data():
    portal = Portal()
    clipboard = PortalClipboard(portal)
    try:
        await clipboard.set_text("private input")
        clipboard.signal(Message.new_signal("/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Clipboard", "SelectionOwnerChanged", "oa{sv}",
            ["/session", {"session_is_owner": Variant("b", False)}]))
        assert clipboard.data is None
    finally:
        os.close(portal.read_fd)
        os.close(portal.write_fd)
