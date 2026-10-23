"""Exercises the Rust-only HTTP fixture with two independent browser profiles."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


async def main():
    fixture = os.environ.get("RUST_FIXTURE_BIN", "/tmp/phone-pad-rust-target/debug/examples/http-fixture")
    process = await asyncio.create_subprocess_exec(fixture, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    info = json.loads(await process.stdout.readline())

    async def command(**data):
        process.stdin.write((json.dumps(data) + "\n").encode())
        await process.stdin.drain()
        info.update(json.loads(await process.stdout.readline()))

    url = f'http://127.0.0.1:{info["port"]}/#token={info["token"]}'
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
            contexts = [await browser.new_context(viewport={"width": 390, "height": 844}) for _ in range(2)]
            page, other = [await context.new_page() for context in contexts]
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(url)
            await expect(page.locator("#pair-panel")).to_be_visible()
            wrong = "000000" if info["code"] != "000000" else "111111"
            await page.locator("#code").fill(wrong)
            await page.locator("#pair").click()
            await expect(page.locator("#pair-result")).to_contain_text("驗證碼錯誤")
            await page.locator("#code").fill(info["code"])
            await page.locator("#pair").click()
            await expect(page.locator("#pad-panel")).to_be_visible()
            await other.goto(url)
            await other.locator("#code").fill(info["code"])
            await other.locator("#pair").click()
            await expect(other.locator("#pair-result")).to_contain_text("已有手機連線")
            sample = "  繁體中文 English 😊\n第二行\n"
            await page.locator("#text").fill(sample)
            await page.locator("#text").dispatch_event("compositionstart")
            await expect(page.locator("#send")).to_be_disabled()
            await page.locator("#text").dispatch_event("compositionend")
            for mode in ["normal", "terminal"]:
                await page.locator("#mode").select_option(mode)
                await page.locator("#send").click()
                await expect(page.locator("#result")).to_have_text("已送出貼上指令")
                await expect(page.locator("#text")).to_have_value(sample)
            await page.reload()
            await expect(page.locator("#pad-panel")).to_be_visible()
            await page.locator("#text").fill(sample)
            await expect(page.locator("#send")).to_be_enabled()
            await command(action="status", ready=False, message="鍵盤控制授權已撤銷")
            await expect(page.locator("#send")).to_be_disabled()
            await command(action="status", ready=True, message="已授權，可以傳送文字")
            await expect(page.locator("#send")).to_be_enabled()
            await page.context.set_offline(True)
            await page.locator("#send").click()
            await expect(page.locator("#result")).to_contain_text("系統不會自動重送")
            await expect(page.locator("#text")).to_have_value(sample)
            await page.context.set_offline(False)
            await expect(page.locator("#send")).to_be_enabled(timeout=15000)
            await command(action="disconnect")
            await expect(page.locator("#pair-panel")).to_be_visible()
            await expect(page.locator("#text")).to_have_value(sample)
            await other.locator("#code").fill(info["code"])
            await other.locator("#pair").click()
            await expect(other.locator("#pad-panel")).to_be_visible()
            await other.locator("#disconnect").click()
            await expect(other.locator("#pair-panel")).to_be_visible()
            assert not errors, errors
            await browser.close()
            print("Rust browser: PIN, exclusive phone, Unicode/modes, IME, reload, revocation, offline, disconnect: PASS")
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), timeout=5)


asyncio.run(main())
