"""Clipboard ownership is established before sending paste key events."""

import asyncio

from .portal import PortalError


class DesktopBackend:
    def __init__(self, portal, copy=None, settle_seconds=0.25):
        self.portal = portal
        self.copy = copy or portal.clipboard.set_text
        self.settle_seconds = settle_seconds

    @property
    def ready(self):
        return self.portal.ready

    @property
    def status(self):
        return self.portal.status

    async def paste(self, text, mode):
        if not self.ready:
            raise PortalError(self.status)
        session = self.portal.session
        await self.copy(text)
        if not self.ready or self.portal.session != session:
            raise PortalError("剪貼簿準備期間授權已變更，未送出按鍵")
        await self.portal.shortcut(mode)
        # Space consecutive clipboard replacements so ordinary applications can
        # consume the selection. This is not proof the target accepted the paste.
        await asyncio.sleep(self.settle_seconds)
