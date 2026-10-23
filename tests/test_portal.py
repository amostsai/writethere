import asyncio

import pytest
from dbus_next import Message, MessageType, Variant

from phone_pad.portal import DesktopPortal, PortalError


class Bus:
    unique_name = ":1.99"

    def __init__(self, denied=False, devices=1):
        self.handler = None
        self.messages = []
        self.denied = denied
        self.devices = devices
        self.disconnected = False

    def add_message_handler(self, handler):
        self.handler = handler

    def disconnect(self):
        self.disconnected = True

    async def call(self, message):
        self.messages.append(message)
        if message.member in ("CreateSession", "SelectDevices", "Start"):
            options = message.body[-1]
            path = "/org/freedesktop/portal/desktop/request/1_99/" + options["handle_token"].value
            result = {}
            if message.member == "CreateSession":
                result["session_handle"] = Variant("s", "/org/freedesktop/portal/desktop/session/1_99/test")
            if message.member == "Start":
                result["devices"] = Variant("u", self.devices)
                result["clipboard_enabled"] = Variant("b", True)
            # Deliver before the method reply to exercise the real portal race.
            self.handler(Message.new_signal(path, "org.freedesktop.portal.Request", "Response",
                                            "ua{sv}", [1 if self.denied else 0, result]))
            return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1,
                           signature="o", body=[path])
        return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1)


async def test_authorize_requests_keyboard_only_and_handles_early_response():
    bus = Bus()
    portal = DesktopPortal(bus=bus)
    await portal.authorize()
    assert portal.ready
    selected = next(m for m in bus.messages if m.member == "SelectDevices")
    assert selected.body[1]["types"].value == 1
    assert any(m.member == "RequestClipboard" for m in bus.messages)
    assert not any(m.interface == "org.freedesktop.portal.ScreenCast" for m in bus.messages)
    await portal.close()
    assert not portal.ready
    assert bus.disconnected


@pytest.mark.parametrize("mode,keys", [("normal", [0xFFE3, 0x76]),
                                        ("terminal", [0xFFE3, 0xFFE1, 0x76])])
async def test_shortcut_press_release_without_enter(mode, keys):
    bus = Bus()
    portal = DesktopPortal(bus=bus)
    await portal.authorize()
    await portal.shortcut(mode)
    events = [(m.body[2], m.body[3]) for m in bus.messages if m.member == "NotifyKeyboardKeysym"]
    assert events == [(k, 1) for k in keys] + [(k, 0) for k in reversed(keys)]


async def test_denied_permission_never_becomes_ready():
    portal = DesktopPortal(bus=Bus(denied=True))
    with pytest.raises(PortalError):
        await portal.authorize()
    assert not portal.ready


async def test_keyboard_must_actually_be_granted():
    portal = DesktopPortal(bus=Bus(devices=0))
    with pytest.raises(PortalError):
        await portal.authorize()
    assert not portal.ready


async def test_revocation_disables_keys_and_notifies():
    states = []
    bus = Bus()
    portal = DesktopPortal(bus=bus, on_change=lambda: states.append(portal.ready))
    await portal.authorize()
    bus.handler(Message.new_signal(portal.session, "org.freedesktop.portal.Session", "Closed", "a{sv}", [{}]))
    assert not portal.ready
    assert states[-1] is False
    with pytest.raises(PortalError):
        await portal.shortcut("normal")


async def test_bus_disconnect_fails_pending_authorization_immediately():
    class DisconnectingBus(Bus):
        async def wait_for_disconnect(self):
            await asyncio.sleep(0)

    portal = DesktopPortal(bus=DisconnectingBus())
    pending = asyncio.get_running_loop().create_future()
    portal.pending["/pending"] = pending
    await portal._watch_disconnect()
    assert pending.done()
    with pytest.raises(PortalError):
        pending.result()


async def test_portal_service_restart_revokes_keyboard_state():
    bus = Bus()
    portal = DesktopPortal(bus=bus)
    await portal.authorize()
    bus.handler(Message.new_signal("/org/freedesktop/DBus", "org.freedesktop.DBus",
        "NameOwnerChanged", "sss", ["org.freedesktop.portal.Desktop", ":1.10", ""]))
    assert not portal.ready
    assert portal.session is None


async def test_denial_can_be_retried_on_same_connection():
    bus = Bus(denied=True)
    portal = DesktopPortal(bus=bus)
    with pytest.raises(PortalError):
        await portal.authorize()
    bus.denied = False
    await portal.authorize()
    assert portal.ready


async def test_initial_portal_owner_acquisition_does_not_abort_request():
    bus = Bus()
    portal = DesktopPortal(bus=bus)
    pending = asyncio.get_running_loop().create_future()
    portal.pending["/pending"] = pending
    portal._signal(Message.new_signal("/org/freedesktop/DBus", "org.freedesktop.DBus",
        "NameOwnerChanged", "sss", ["org.freedesktop.portal.Desktop", "", ":1.10"]))
    assert not pending.done()
    pending.cancel()


async def test_key_failure_releases_all_possibly_pressed_modifiers():
    class FailingBus(Bus):
        async def call(self, message):
            if message.member == "NotifyKeyboardKeysym" and message.body[2:] == [0x76, 1]:
                self.messages.append(message)
                raise OSError("lost key reply")
            return await super().call(message)

    bus = FailingBus()
    portal = DesktopPortal(bus=bus)
    await portal.authorize()
    with pytest.raises(OSError):
        await portal.shortcut("terminal")
    releases = [m.body[2] for m in bus.messages if m.member == "NotifyKeyboardKeysym" and m.body[3] == 0]
    assert releases == [0x76, 0xFFE1, 0xFFE3]
    assert not portal.ready
