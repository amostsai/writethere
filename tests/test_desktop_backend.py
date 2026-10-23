import pytest

from phone_pad.backend import DesktopBackend


class Portal:
    ready = True
    status = "已授權"
    session = "/test/session"

    def __init__(self):
        self.calls = []

    async def shortcut(self, mode):
        self.calls.append(mode)


async def test_clipboard_must_be_ready_before_shortcut():
    portal = Portal()
    events = []

    async def copy(text):
        assert portal.calls == []
        events.append(text)

    backend = DesktopBackend(portal, copy=copy, settle_seconds=0)
    await backend.paste("  繁體😊\n", "terminal")
    assert events == ["  繁體😊\n"]
    assert portal.calls == ["terminal"]


async def test_clipboard_failure_never_sends_keys():
    portal = Portal()

    async def copy(text):
        raise OSError("clipboard unavailable")

    backend = DesktopBackend(portal, copy=copy, settle_seconds=0)
    with pytest.raises(OSError):
        await backend.paste("test", "normal")
    assert portal.calls == []


async def test_revocation_during_clipboard_copy_never_sends_keys():
    portal = Portal()

    async def copy(text):
        portal.ready = False

    backend = DesktopBackend(portal, copy=copy, settle_seconds=0)
    with pytest.raises(RuntimeError):
        await backend.paste("test", "normal")
    assert portal.calls == []
