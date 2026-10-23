"""Reuses dedicated receiver windows, but all authorization/paste is Rust HTTP."""
import asyncio
import json
import os
import secrets
import aiohttp
from live_desktop_check import Check, GLib


class RustBackend:
    async def authorize(self):
        path = os.environ.get("RUST_LIVE_BIN", "/tmp/phone-pad-rust-target/debug/examples/live-backend")
        self.process = await asyncio.create_subprocess_exec(path, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        self.info = json.loads(await self.process.stdout.readline())
        result = json.loads(await self.process.stdout.readline())
        if not result["ready"]:
            raise RuntimeError(result["error"])
        self.client = aiohttp.ClientSession()
        response = await self.client.post(f'http://127.0.0.1:{self.info["port"]}/api/pair',
            json={"code": self.info["code"]}, headers={"Authorization": f'Bearer {self.info["token"]}'})
        assert response.status == 200
        self.token = (await response.json())["session_token"]

    async def paste(self, text, mode):
        response = await self.client.post(f'http://127.0.0.1:{self.info["port"]}/api/send',
            json={"request_id": secrets.token_hex(16), "text": text, "mode": mode},
            headers={"Authorization": f"Bearer {self.token}"})
        data = await response.json()
        assert response.status == 200, data

    async def close(self):
        if hasattr(self, "client"):
            await self.client.close()
        if hasattr(self, "process"):
            self.process.stdin.close()
            await asyncio.wait_for(self.process.wait(), timeout=10)


app = Check()
app.set_application_id("tw.local.PhonePadRustVerification")
app.portal = app.backend = RustBackend()
try:
    app.run([])
finally:
    GLib.source_remove(app.tick)
    app.loop.run_until_complete(app.loop.shutdown_asyncgens())
    app.loop.close()
raise SystemExit(0 if app.ok else 1)
