"""LAN HTTP API. Text exists only while a request is being delivered."""

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import time

from aiohttp import web

from .settings import DEFAULT_PORT

WEB = Path(__file__).parent / "web"


class PadService:
    def __init__(self, backend, token=None, on_change=lambda: None):
        self.backend = backend
        self.token = token or secrets.token_urlsafe(32)
        self.on_change = on_change
        self.clock = time.monotonic
        self._pairing_code = f"{secrets.randbelow(1000000):06d}"
        self.session_token = None
        self.lease_seconds = 30
        self.pair_failures = []
        self.sending = False
        self.max_requests = 10000
        self.records = {}
        self.lock = asyncio.Lock()
        self.last_seen = 0.0
        self.runner = None
        self.port = None
        self.accepting = True
        self.app = web.Application(client_max_size=128 * 1024,
                                   middlewares=[self._security])
        self.app.add_routes([
            web.get("/", self.index),
            web.get("/app.js", self.asset),
            web.get("/style.css", self.asset),
            web.post("/api/pair", self.pair),
            web.post("/api/disconnect", self.phone_disconnect),
            web.get("/api/status", self.status),
            web.post("/api/send", self.send),
        ])

    @web.middleware
    async def _security(self, request, handler):
        try:
            origin = request.headers.get("Origin")
            if origin and origin != f"http://{request.host}":
                raise web.HTTPForbidden(text="不允許跨網站請求")
            if request.path.startswith("/api/"):
                if request.path == "/api/pair":
                    if not self._matches(request, self.token):
                        raise web.HTTPUnauthorized(text="連線憑證無效，請重新掃碼")
                elif not self._owner_matches(request):
                    return self._headers(web.json_response({"message": "連線已釋放，請輸入電腦目前的驗證碼重新配對"}, status=401))
                else:
                    self.last_seen = self.clock()
                    self.on_change()
            response = await handler(request)
        except web.HTTPException as error:
            response = web.Response(status=error.status, text=error.text,
                                    headers=error.headers)
        return self._headers(response)

    @staticmethod
    def _headers(response):
        response.headers.update({
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "connect-src 'self'; frame-ancestors 'none'; "
                                       "base-uri 'none'; form-action 'none'",
        })
        return response

    @staticmethod
    def _matches(request, token):
        return token is not None and hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), f"Bearer {token}".encode())

    def _release(self):
        self.session_token = None
        self.last_seen = 0.0
        previous = self._pairing_code
        while self._pairing_code == previous:
            self._pairing_code = f"{secrets.randbelow(1000000):06d}"
        self.pair_failures.clear()

    def _expire(self):
        if self.session_token and not self.sending and self.clock() - self.last_seen >= self.lease_seconds:
            self._release()

    @property
    def pairing_code(self):
        self._expire()
        return self._pairing_code

    @property
    def session_active(self):
        self._expire()
        return self.session_token is not None

    def _owner_matches(self, request):
        self._expire()
        return self._matches(request, self.session_token)

    async def pair(self, request):
        try:
            data = await request.json()
            code = data["code"]
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return web.json_response({"message": "請輸入 6 位數驗證碼"}, status=400)
        self._expire()
        if not self.accepting:
            return web.json_response({"message": "服務已停止"}, status=503)
        # No awaits between checking and claiming the slot: concurrent pairs
        # cannot both succeed on this single event loop.
        if self.session_token:
            return web.json_response({"message": "已有手機連線，請先在電腦中斷連線或等待其斷線 30 秒"}, status=409)
        now = self.clock()
        self.pair_failures = [stamp for stamp in self.pair_failures if now - stamp < 30]
        if len(self.pair_failures) >= 5:
            return web.json_response({"message": "驗證嘗試過多，請於 30 秒後重試"},
                                     status=429, headers={"Retry-After": "30"})
        if not hmac.compare_digest(code, self._pairing_code):
            self.pair_failures.append(now)
            return web.json_response({"message": "驗證碼錯誤，請查看電腦目前顯示的 6 位數字"}, status=401)
        self.session_token = secrets.token_urlsafe(32)
        self.last_seen = now
        self.pair_failures.clear()
        self.on_change()
        return web.json_response({"session_token": self.session_token, "message": "配對成功"})

    async def disconnect(self):
        async with self.lock:
            self._release()
            self.on_change()

    async def phone_disconnect(self, request):
        async with self.lock:
            if not self._owner_matches(request):
                return web.json_response({"message": "連線已釋放"}, status=401)
            self._release()
            self.on_change()
        return web.json_response({"message": "已中斷連線；請查看電腦更新後的驗證碼"})

    async def index(self, request):
        return web.Response(text=(WEB / "index.html").read_text(), content_type="text/html")

    async def asset(self, request):
        name = request.path[1:]
        kind = "text/javascript" if name.endswith(".js") else "text/css"
        return web.Response(text=(WEB / name).read_text(), content_type=kind)

    async def status(self, request):
        return web.json_response({"ready": self.accepting and self.backend.ready,
                                  "message": self.backend.status})

    async def send(self, request):
        try:
            if request.content_type != "application/json":
                raise ValueError()
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            text, mode, request_id = data["text"], data["mode"], data["request_id"]
            if not isinstance(text, str) or not 1 <= len(text) <= 20000 or "\x00" in text:
                raise ValueError()
            if mode not in ("normal", "terminal"):
                raise ValueError()
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
                raise ValueError()
            fingerprint = hashlib.sha256((mode + "\0" + text).encode("utf-8")).digest()
        except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
            return web.json_response({"message": "文字需為 1–20,000 字，且傳送格式必須正確"}, status=400)

        async with self.lock:
            # Recheck after reading the body / waiting for an earlier send:
            # a disconnected phone must not paste into a new owner's session.
            if not self._owner_matches(request):
                return web.json_response({"message": "連線已釋放，請重新配對"}, status=401)
            if request_id in self.records:
                previous, code, message = self.records[request_id]
                if previous != fingerprint:
                    return web.json_response({"message": "請求識別碼已使用"}, status=409)
                return web.json_response({"message": message}, status=code)
            if not self.accepting or not self.backend.ready:
                return web.json_response({"message": self.backend.status}, status=503)
            if len(self.records) >= self.max_requests:
                return web.json_response({"message": "本次工作階段已達上限，請重新啟動電腦工具並掃碼"}, status=503)
            # Reserve BEFORE any desktop side effect, including partial failure/cancellation.
            failure = (fingerprint, 502, "無法確認貼上結果；請先查看電腦，避免重複傳送")
            self.records[request_id] = failure
            self.sending = True
            try:
                await self.backend.paste(text, mode)
            except Exception:
                return web.json_response({"message": failure[2]}, status=502)
            finally:
                self.sending = False
                self.last_seen = self.clock()
            self.records[request_id] = (fingerprint, 200, "已送出貼上指令")
            return web.json_response({"message": "已送出貼上指令"})

    async def start(self, host="0.0.0.0", port=DEFAULT_PORT):
        self.runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=5)
        try:
            await self.runner.setup()
            site = web.TCPSite(self.runner, host, port)
            await site.start()
            self.port = self.runner.addresses[0][1]
        except BaseException:
            await self.runner.cleanup()
            self.runner = None
            self.port = None
            raise

    async def stop(self):
        self.accepting = False
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        self.port = None
