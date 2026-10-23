import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from phone_pad.service import PadService


class Backend:
    def __init__(self):
        self.ready = True
        self.status = "已授權"
        self.calls = []
        self.fail = False

    async def paste(self, text, mode):
        self.calls.append((text, mode))
        await asyncio.sleep(0.01)
        if self.fail:
            raise RuntimeError("simulated desktop failure")


@pytest.fixture
async def pad():
    backend = Backend()
    service = PadService(backend, token="test-secret")
    async with TestClient(TestServer(service.app)) as client:
        response = await client.post("/api/pair", json={"code": service.pairing_code},
                                     headers={"Authorization": "Bearer test-secret"})
        owner = (await response.json())["session_token"]
        client.session.headers["Authorization"] = f"Bearer {owner}"
        yield client, backend, service


def payload(request_id="req-1", text="繁體中文 English 😊\n第二行", mode="normal"):
    return {"request_id": request_id, "text": text, "mode": mode}


async def send(client, data, token=None):
    return await client.post("/api/send", json=data,
                             headers={"Authorization": f"Bearer {token}"} if token else {})


async def test_preserves_unicode_whitespace_and_newlines(pad):
    client, backend, _ = pad
    response = await send(client, payload(text="  中文 😊\n第二行\n"))
    assert response.status == 200
    assert (await response.json())["message"] == "已送出貼上指令"
    assert backend.calls == [("  中文 😊\n第二行\n", "normal")]


async def test_concurrent_duplicate_is_pasted_once(pad):
    client, backend, _ = pad
    responses = await asyncio.gather(*(send(client, payload()) for _ in range(5)))
    assert [r.status for r in responses] == [200] * 5
    assert len(backend.calls) == 1


async def test_request_id_cannot_be_reused_for_different_text(pad):
    client, backend, _ = pad
    await send(client, payload())
    response = await send(client, payload(text="different"))
    assert response.status == 409
    assert len(backend.calls) == 1


async def test_terminal_mode_and_sequential_messages(pad):
    client, backend, _ = pad
    for n in range(3):
        assert (await send(client, payload(f"r{n}", mode="terminal"))).status == 200
    assert backend.calls == [(payload()["text"], "terminal")] * 3


async def test_no_permission_and_revocation_disable_send(pad):
    client, backend, _ = pad
    backend.ready = False
    assert (await send(client, payload())).status == 503
    assert backend.calls == []
    response = await client.get("/api/status")
    assert (await response.json())["ready"] is False


async def test_failure_is_not_automatically_retried(pad):
    client, backend, _ = pad
    backend.fail = True
    assert (await send(client, payload())).status == 502
    backend.fail = False
    assert (await send(client, payload())).status == 502
    assert len(backend.calls) == 1


@pytest.mark.parametrize("data", [[], {}, payload(text=""), payload(mode="bad"),
                                      payload(text="a\x00b"), payload(request_id=""),
                                      payload(text="a" * 20001)])
async def test_invalid_payload_never_pastes(pad, data):
    client, backend, _ = pad
    assert (await send(client, data)).status == 400
    assert backend.calls == []


async def test_invalid_token_and_cross_origin_requests_rejected(pad):
    client, backend, _ = pad
    assert (await send(client, payload(), token="wrong")).status == 401
    response = await client.post("/api/send", json=payload(), headers={
        "Authorization": "Bearer test-secret", "Origin": "http://untrusted.example"})
    assert response.status == 403
    assert backend.calls == []


async def test_page_does_not_expose_token_and_has_no_cache(pad):
    client, _, _ = pad
    response = await client.get("/")
    assert response.status == 200
    assert "test-secret" not in await response.text()
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


async def test_full_ledger_refuses_new_requests_without_forgetting_old_ids(pad):
    client, backend, service = pad
    service.max_requests = 1
    assert (await send(client, payload())).status == 200
    assert (await send(client, payload("new-id"))).status == 503
    assert (await send(client, payload())).status == 200
    assert len(backend.calls) == 1
