"""Own the web service and portal lifecycle on one asyncio loop."""

import asyncio
import errno
from contextlib import suppress

from .backend import DesktopBackend
from .network import discover_addresses
from .portal import DesktopPortal, PortalError
from .service import PadService
from .settings import PortSettings, parse_port


class Runtime:
    def __init__(self, on_change=lambda: None, settings=None):
        self.on_change = on_change
        self.portal = DesktopPortal(on_change=on_change)
        self.backend = DesktopBackend(self.portal)
        self.service = PadService(self.backend, on_change=on_change)
        self.addresses = []
        self.error = ""
        self.network_error = ""
        self.auth_task = None
        self.stopping = False
        self.settings = settings if settings is not None else PortSettings()
        self.configured_port = self.settings.load()
        self.settings_message = self.settings.warning

    async def start(self):
        try:
            self.addresses = await discover_addresses()
            await self.service.start(port=self.configured_port)
        except Exception as error:
            if isinstance(error, OSError) and error.errno == errno.EADDRINUSE:
                self.error = f"連接埠 {self.configured_port} 已被占用，請修改並儲存後重新啟動"
            else:
                self.error = f"無法啟動連接埠 {self.configured_port}，請確認網路與權限，或修改並儲存後重新啟動"
            await self.service.stop()
            self.on_change()
            return
        self.on_change()
        self.authorize()

    def save_port(self, value):
        try:
            port = parse_port(value)
            self.settings.save(port)
        except ValueError as error:
            self.settings_message = str(error)
            saved = False
        except OSError:
            self.settings_message = "儲存失敗，請確認設定資料夾的權限與可用空間；原設定未變更"
            saved = False
        else:
            self.configured_port = port
            self.settings_message = f"已儲存連接埠 {port}，下次啟動套用"
            saved = True
        self.on_change()
        return saved

    def authorize(self):
        if self.stopping or (self.auth_task and not self.auth_task.done()):
            return
        self.auth_task = asyncio.create_task(self._authorize())
        self.on_change()

    async def _authorize(self):
        # Wait for any current paste before replacing the authorized session.
        try:
            async with self.service.lock:
                await self.portal.authorize()
        except PortalError:
            pass  # Portal status carries a user-facing explanation.
        finally:
            # Run after this task is marked done so the retry button re-enables.
            asyncio.get_running_loop().call_soon(self.on_change)

    async def refresh_network(self):
        try:
            self.addresses = await discover_addresses()
        except Exception:
            self.network_error = "無法讀取網路介面，請確認已連上區網"
        else:
            self.network_error = ""
        self.on_change()

    async def stop(self):
        self.stopping = True
        self.service.accepting = False
        if self.auth_task and not self.auth_task.done():
            self.auth_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.auth_task
        await self.service.stop()
        await self.portal.close()
