import asyncio

import aiohttp
from phone_pad.settings import PortSettings
from phone_pad.service import PadService

from phone_pad.runtime import Runtime


async def test_close_during_pending_authorization_stops_http_and_session(monkeypatch, tmp_path):
    runtime = Runtime(settings=PortSettings(tmp_path / "settings.json"))
    entered = asyncio.Event()
    closed = []

    async def addresses():
        return [("test · 127.0.0.1", "127.0.0.1")]

    async def authorize():
        entered.set()
        await asyncio.Event().wait()

    async def close():
        closed.append(True)

    monkeypatch.setattr("phone_pad.runtime.discover_addresses", addresses)
    monkeypatch.setattr(runtime.portal, "authorize", authorize)
    monkeypatch.setattr(runtime.portal, "close", close)
    original_start = runtime.service.start

    async def ephemeral_start(**kwargs):
        await original_start(host="127.0.0.1", port=0)

    monkeypatch.setattr(runtime.service, "start", ephemeral_start)
    await runtime.start()
    await entered.wait()
    port = runtime.service.port
    await runtime.stop()
    assert runtime.auth_task.cancelled()
    assert closed == [True]
    assert runtime.service.runner is None
    async with aiohttp.ClientSession() as client:
        try:
            async with client.get(f"http://127.0.0.1:{port}/"):
                raise AssertionError("HTTP service should be stopped")
        except aiohttp.ClientConnectorError:
            pass


async def test_stop_waits_for_an_active_send_before_closing_portal(monkeypatch, tmp_path):
    runtime = Runtime(settings=PortSettings(tmp_path / "settings.json"))
    order = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def paste(text, mode):
        order.append("paste-start")
        entered.set()
        await release.wait()
        order.append("paste-finish")

    async def close():
        order.append("portal-close")

    runtime.portal.ready = True
    monkeypatch.setattr(runtime.backend, "paste", paste)
    monkeypatch.setattr(runtime.portal, "close", close)
    await runtime.service.start(host="127.0.0.1", port=0)
    async with aiohttp.ClientSession() as client:
        paired = await client.post(f"http://127.0.0.1:{runtime.service.port}/api/pair",
            json={"code": runtime.service.pairing_code},
            headers={"Authorization": f"Bearer {runtime.service.token}"})
        owner = (await paired.json())["session_token"]
        task = asyncio.create_task(client.post(f"http://127.0.0.1:{runtime.service.port}/api/send",
            json={"request_id": "closing-test", "text": "test", "mode": "normal"},
            headers={"Authorization": f"Bearer {owner}"}))
        await entered.wait()
        stop = asyncio.create_task(runtime.stop())
        await asyncio.sleep(0.02)
        assert "portal-close" not in order
        release.set()
        response = await task
        assert response.status == 200
        await stop
    assert order == ["paste-start", "paste-finish", "portal-close"]


async def test_start_uses_saved_port_and_saving_does_not_change_running_listener(tmp_path, monkeypatch):
    settings = PortSettings(tmp_path / "settings.json")
    settings.save(45678)
    runtime = Runtime(settings=settings)
    ports = []

    async def addresses():
        return [("test", "127.0.0.1")]

    async def start(*, port):
        ports.append(port)
        runtime.service.port = port

    async def authorize():
        pass

    monkeypatch.setattr("phone_pad.runtime.discover_addresses", addresses)
    monkeypatch.setattr(runtime.service, "start", start)
    monkeypatch.setattr(runtime.portal, "authorize", authorize)
    await runtime.start()
    await runtime.auth_task
    assert ports == [45678]
    assert runtime.save_port("45679")
    assert runtime.service.port == 45678
    assert Runtime(settings=PortSettings(settings.path)).configured_port == 45679
    await runtime.stop()


async def test_occupied_port_reports_error_without_random_fallback(tmp_path, monkeypatch):
    occupying = PadService(object())
    await occupying.start(host="127.0.0.1", port=0)
    settings = PortSettings(tmp_path / "settings.json")
    settings.save(occupying.port)
    runtime = Runtime(settings=settings)

    async def addresses():
        return [("test", "127.0.0.1")]

    monkeypatch.setattr("phone_pad.runtime.discover_addresses", addresses)
    try:
        await runtime.start()
        assert str(occupying.port) in runtime.error
        assert "已被占用" in runtime.error
        assert runtime.service.port is None
        assert runtime.service.runner is None
        assert runtime.auth_task is None
        await runtime.refresh_network()
        assert "已被占用" in runtime.error
    finally:
        await runtime.stop()
        await occupying.stop()


def test_invalid_or_failed_save_does_not_change_configured_port(tmp_path, monkeypatch):
    runtime = Runtime(settings=PortSettings(tmp_path / "settings.json"))
    assert runtime.configured_port == 39945
    assert not runtime.save_port("65536")
    assert runtime.configured_port == 39945

    def fail(port):
        raise OSError("read-only")

    monkeypatch.setattr(runtime.settings, "save", fail)
    assert not runtime.save_port("45678")
    assert runtime.configured_port == 39945
    assert "儲存失敗" in runtime.settings_message
