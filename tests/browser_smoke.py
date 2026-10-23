"""Optional real-browser check: PYTHONPATH=. .venv/bin/python tests/browser_smoke.py.

Uses an in-memory desktop double; never changes the real clipboard or sends keys.
Requires Playwright and a Chromium installation, separately from core dependencies.
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright, expect

from phone_pad.service import PadService


class Backend:
    ready = True
    status = "已授權，可以傳送文字"

    def __init__(self):
        self.calls = []

    async def paste(self, text, mode):
        self.calls.append((text, mode))
        await asyncio.sleep(0.2)


async def main():
    backend = Backend()
    service = PadService(backend)
    await service.start(host="127.0.0.1", port=0)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
            page = await browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(f"http://127.0.0.1:{service.port}/#token={service.token}")
            await expect(page.locator("#pair-panel")).to_be_visible()
            await expect(page.locator("#pad-panel")).to_be_hidden()
            wrong = "000000" if service.pairing_code != "000000" else "111111"
            await page.locator("#code").fill(wrong)
            await page.locator("#pair").click()
            await expect(page.locator("#pair-result")).to_contain_text("驗證碼錯誤")
            await page.locator("#code").fill(service.pairing_code)
            await page.locator("#pair").click()
            await expect(page.locator("#connection")).to_have_text(backend.status)
            other_context = await browser.new_context()
            other = await other_context.new_page()
            await other.goto(f"http://127.0.0.1:{service.port}/#token={service.token}")
            await other.locator("#code").fill(service.pairing_code)
            await other.locator("#pair").click()
            await expect(other.locator("#pair-result")).to_contain_text("已有手機連線")
            await expect(other.locator("#pad-panel")).to_be_hidden()
            assert "token=" not in page.url
            message = "繁體中文 English 😊\n第二行"
            await page.locator("#text").fill(message)
            await expect(page.locator("#send")).to_be_enabled()
            await page.locator("#text").dispatch_event("compositionstart")
            await expect(page.locator("#send")).to_be_disabled()
            await page.locator("#text").dispatch_event("compositionend")
            await page.locator("#send").click()
            await expect(page.locator("#send")).to_be_disabled()
            await expect(page.locator("#result")).to_have_text("已送出貼上指令")
            await expect(page.locator("#text")).to_have_value(message)
            assert backend.calls == [(message, "normal")]
            await page.locator("#mode").select_option("terminal")
            await page.locator("#send").click()
            await expect(page.locator("#result")).to_have_text("已送出貼上指令")
            assert backend.calls[-1] == (message, "terminal")
            # Reload retains only the tab credential, not a persisted text history.
            await page.reload()
            await expect(page.locator("#connection")).to_have_text(backend.status)
            await page.locator("#text").fill(message)
            Path("artifacts").mkdir(exist_ok=True)
            await page.screenshot(path="artifacts/phone.png", full_page=True)
            backend.ready = False
            backend.status = "鍵盤控制授權已撤銷，請在電腦重新授權"
            await expect(page.locator("#connection")).to_have_text(backend.status)
            await expect(page.locator("#send")).to_be_disabled()
            backend.ready = True
            backend.status = "已授權，可以傳送文字"
            await expect(page.locator("#send")).to_be_enabled()
            await page.context.set_offline(True)
            await page.locator("#send").click()
            await expect(page.locator("#result")).to_contain_text("系統不會自動重送")
            await expect(page.locator("#text")).to_have_value(message)
            await asyncio.sleep(2.2)
            assert len(backend.calls) == 2
            await page.context.set_offline(False)
            await expect(page.locator("#send")).to_be_enabled(timeout=15000)
            await page.locator("#clear").click()
            await expect(page.locator("#text")).to_have_value("")
            await page.locator("#text").fill("保留的草稿")
            await service.disconnect()
            await expect(page.locator("#pair-panel")).to_be_visible()
            await expect(page.locator("#text")).to_have_value("保留的草稿")
            await other.locator("#code").fill(service.pairing_code)
            await other.locator("#pair").click()
            await expect(other.locator("#pad-panel")).to_be_visible()
            await other.locator("#disconnect").click()
            await expect(other.locator("#pair-panel")).to_be_visible()
            await other_context.close()
            # A response from a revoked session must not erase a newer pairing.
            for path, button in [("/api/send", "#send"), ("/api/disconnect", "#disconnect")]:
                await page.locator("#code").fill(service.pairing_code)
                await page.locator("#pair").click()
                await expect(page.locator("#send")).to_be_enabled()
                held, release = asyncio.Event(), asyncio.Event()

                async def delayed_response(route):
                    held.set()
                    await release.wait()
                    await route.fulfill(status=401, json={"message": "old session invalid"})

                await page.route(f"**{path}", delayed_response)
                await page.locator(button).click()
                await held.wait()
                await service.disconnect()
                await expect(page.locator("#pair-panel")).to_be_visible()
                await page.locator("#code").fill(service.pairing_code)
                await page.locator("#pair").click()
                await expect(page.locator("#pad-panel")).to_be_visible()
                release.set()
                await expect(page.locator("#send")).to_be_enabled()
                await page.unroute(f"**{path}", delayed_response)
                await service.disconnect()
                await expect(page.locator("#pair-panel")).to_be_visible()
            assert not errors, errors
            await browser.close()
            print("Browser smoke: pairing PIN, second phone blocked, disconnect/switch, normal/terminal, IME, draft retention, revocation, offline/no retry: PASS")
    finally:
        await service.stop()


asyncio.run(main())
