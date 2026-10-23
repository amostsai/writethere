import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from phone_pad.service import PadService


class Backend:
    ready = True
    status = "ready"

    def __init__(self):
        self.calls = []

    async def paste(self, text, mode):
        self.calls.append(text)


@pytest.fixture
async def unpaired():
    service = PadService(Backend(), token="invitation")
    async with TestClient(TestServer(service.app)) as client:
        yield client, service


async def pair(client, code):
    return await client.post("/api/pair", json={"code": code},
                             headers={"Authorization": "Bearer invitation"})


async def test_code_is_six_digits_and_never_exposed_to_phone(unpaired):
    client, service = unpaired
    assert len(service.pairing_code) == 6 and service.pairing_code.isascii() and service.pairing_code.isdigit()
    assert service.pairing_code not in await (await client.get("/")).text()
    response = await pair(client, service.pairing_code)
    assert response.status == 200
    token = (await response.json())["session_token"]
    assert token != "invitation"
    assert (await client.get("/api/status", headers={"Authorization": f"Bearer {token}"})).status == 200


async def test_qr_token_alone_cannot_send_or_see_status(unpaired):
    client, service = unpaired
    assert (await client.get("/api/status", headers={"Authorization": "Bearer invitation"})).status == 401
    response = await client.post("/api/send", json={"request_id": "x", "text": "no", "mode": "normal"},
                                 headers={"Authorization": "Bearer invitation"})
    assert response.status == 401
    assert service.backend.calls == []


async def test_wrong_code_and_brute_force_cooldown(unpaired):
    client, service = unpaired
    wrong = "000000" if service.pairing_code != "000000" else "111111"
    for _ in range(5):
        assert (await pair(client, wrong)).status == 401
    assert (await pair(client, service.pairing_code)).status == 429


async def test_simultaneous_phones_only_one_can_claim(unpaired):
    client, service = unpaired
    responses = await asyncio.gather(*(pair(client, service.pairing_code) for _ in range(5)))
    assert sorted(response.status for response in responses) == [200, 409, 409, 409, 409]


async def test_disconnect_revokes_owner_and_rotates_code(unpaired):
    client, service = unpaired
    old_code = service.pairing_code
    owner = (await (await pair(client, old_code)).json())["session_token"]
    await service.disconnect()
    assert service.pairing_code != old_code
    assert (await client.get("/api/status", headers={"Authorization": f"Bearer {owner}"})).status == 401
    assert (await pair(client, old_code)).status == 401
    assert (await pair(client, service.pairing_code)).status == 200


async def test_idle_timeout_frees_slot_and_old_phone_cannot_take_it_back(unpaired):
    client, service = unpaired
    now = [100.0]
    service.clock = lambda: now[0]
    owner = (await (await pair(client, service.pairing_code)).json())["session_token"]
    now[0] += 31
    response = await pair(client, service.pairing_code)
    assert response.status == 200
    new_owner = (await response.json())["session_token"]
    assert owner != new_owner
    assert (await client.get("/api/status", headers={"Authorization": f"Bearer {owner}"})).status == 401


async def test_owner_heartbeat_renews_slot_and_phone_can_release_it(unpaired):
    client, service = unpaired
    now = [100.0]
    service.clock = lambda: now[0]
    owner = (await (await pair(client, service.pairing_code)).json())["session_token"]
    headers = {"Authorization": f"Bearer {owner}"}
    now[0] += 25
    assert (await client.get("/api/status", headers=headers)).status == 200
    now[0] += 25
    assert (await pair(client, service.pairing_code)).status == 409
    assert (await client.post("/api/disconnect", headers=headers)).status == 200
    assert (await pair(client, service.pairing_code)).status == 200


async def test_leading_zero_code_requires_all_six_digits(unpaired):
    client, service = unpaired
    service._pairing_code = "012345"
    assert (await pair(client, "12345")).status == 400
    assert (await pair(client, "012345")).status == 200


async def test_cooldown_expires_after_thirty_seconds(unpaired):
    client, service = unpaired
    now = [100.0]
    service.clock = lambda: now[0]
    wrong = "000000" if service.pairing_code != "000000" else "111111"
    for _ in range(5):
        await pair(client, wrong)
    now[0] += 30
    assert (await pair(client, service.pairing_code)).status == 200


async def test_expired_phone_cannot_finish_a_slow_request_after_new_phone_pairs(unpaired):
    client, service = unpaired
    now = [100.0]
    service.clock = lambda: now[0]
    owner = (await (await pair(client, service.pairing_code)).json())["session_token"]
    accepted = asyncio.Event()
    finish_body = asyncio.Event()
    service.on_change = accepted.set

    async def body():
        yield b'{"request_id":"slow","mode":"normal","text":"'
        await finish_body.wait()
        yield b'old phone"}'

    task = asyncio.create_task(client.post("/api/send", data=body(), headers={
        "Authorization": f"Bearer {owner}", "Content-Type": "application/json"}))
    await accepted.wait()
    now[0] += 31
    assert (await pair(client, service.pairing_code)).status == 200
    finish_body.set()
    assert (await task).status == 401
    assert service.backend.calls == []


async def test_active_paste_keeps_slot_until_it_finishes(unpaired):
    client, service = unpaired
    now = [100.0]
    service.clock = lambda: now[0]
    owner = (await (await pair(client, service.pairing_code)).json())["session_token"]
    started, finish = asyncio.Event(), asyncio.Event()

    async def paste(text, mode):
        started.set()
        await finish.wait()

    service.backend.paste = paste
    task = asyncio.create_task(client.post("/api/send", json={
        "request_id": "active", "mode": "normal", "text": "test"},
        headers={"Authorization": f"Bearer {owner}"}))
    await started.wait()
    now[0] += 31
    assert (await pair(client, service.pairing_code)).status == 409
    finish.set()
    assert (await task).status == 200
    assert service.session_active
