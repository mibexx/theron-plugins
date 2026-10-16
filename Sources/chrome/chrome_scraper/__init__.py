"""Chrome for Theron: the process node 🌐 Scrape pages – the user's own Chrome, driven over the DevTools protocol
and behaving like a person, hands on the content of web pages as Markdown or raw HTML (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

import subprocess

from .cdp import Browser, CdpError, find_browser, has_display
from .node import Pool, ScrapeNode
from .scraper import Page


def register(ctx):
    pool = Pool(ctx)
    ScrapeNode(ctx, pool).register()
    ctx.pool = pool   # for the tests

    async def test(values: dict):
        path = find_browser(values.get("browser") or "")
        if not path:
            return False, ctx.tr("No Chrome found – install Google Chrome (or Chromium / Edge / Brave) or enter its "
                                 "path.")
        await pool.shutdown()
        try:
            browser = await pool.acquire("headless")
        except CdpError as exc:
            return False, ctx.tr("Chrome doesn't start: {error}", error=exc)
        try:
            page = await Page.open(browser, pool.lang())
            try:
                await page.load("https://example.com/")
                seen = await page.s.eval("({ua: navigator.userAgent, wd: navigator.webdriver, "
                                         "langs: navigator.languages.join(', ')})") or {}
            finally:
                await page.close()
        except CdpError as exc:
            return False, ctx.tr("Chrome starts, but can't load a page: {error}", error=exc)
        finally:
            await pool.release()
        tell = "Headless" in (seen.get("ua") or "") or seen.get("wd")
        return (not tell), ctx.tr("{browser} · {path} · looks like a normal browser: {ok} · languages {langs}",
                                  browser=browser.version.get("product", "?"), path=path,
                                  ok=ctx.tr("no") if tell else ctx.tr("yes"), langs=seen.get("langs") or "?")

    async def open_profile(values: dict):
        """A normal Chrome window with the plugin's profile – log in to sites, accept cookie banners."""
        if not has_display():
            return False, ctx.tr("There is no screen here (server) – this works on a desktop only.")
        path = find_browser(values.get("browser") or "")
        if not path:
            return False, ctx.tr("No Chrome found.")
        await pool.shutdown()
        b = Browser(path, pool.profile(), headless=False, window="normal")
        args = [a for a in b.args(pool.profile()) if not a.startswith("--remote-debugging")]
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True, ctx.tr("Chrome is open with the plugin's profile – log in where you need to, then close the "
                            "window (scraping waits until then).")

    ctx.settings.add_button("Test", test, tooltip="Starts Chrome invisibly, loads example.com and checks that it "
                                                  "looks like a normal browser.")
    ctx.settings.add_button("Open browser", open_profile, id="profile",
                            tooltip="Opens Chrome with the plugin's own profile: log in to sites or accept cookies "
                                    "once – the scraper keeps them.")

    @ctx.on_stop
    def stop():
        if pool.browser and pool.browser.proc and pool.browser.proc.poll() is None:
            pool.browser.proc.kill()
