"""Bright Data for Theron – three process nodes and a "Test" button (theron_api 1, Theron ≥ 0.20):

- 🔍 Google search (Bright Data) – SERP API: a query from the input, the URLs of the hits on
- 🛰 Web Unlocker (Bright Data) – web pages past bot protection, as Markdown or raw HTML
- 🖥 Browser API (Bright Data) – web pages in a real Chrome at Bright Data (JavaScript, CAPTCHAs)"""

from __future__ import annotations

from . import browser
from .api import COST, SERP_COST, Client, UnlockError
from .browser import BrowserNode
from .node import ScrapeNode
from .search import SearchNode


def register(ctx):
    SearchNode(ctx).register()
    ScrapeNode(ctx).register()
    BrowserNode(ctx).register()

    async def test(values: dict):
        key = (values.get("api_key") or "").strip()
        zone, serp = (values.get("zone") or "").strip(), (values.get("serp_zone") or "").strip()
        user, password = (values.get("browser_user") or "").strip(), (values.get("browser_password") or "").strip()
        country = (values.get("country") or "").strip()
        if not (key and (zone or serp)) and not (user and password):
            return False, ctx.tr("Enter the API key with a zone, or the Browser API username and password.")
        lines, ok = [], True
        if key and zone:
            try:
                page = await Client(ctx.http, key, zone, timeout=60).unlock("https://example.com/", country=country)
            except UnlockError as exc:
                ok = False
                lines.append(ctx.tr("✖ Web Unlocker: {error}", error=exc))
            else:
                good = page["status"] < 400
                ok &= good
                lines.append(ctx.tr("✔ Web Unlocker · zone {zone} · per 1,000 pages: {cost}", zone=zone,
                                    cost=ctx.tr(COST)) if good else
                             ctx.tr("✖ Web Unlocker: the test page came back with HTTP {status}.",
                                    status=page["status"]))
        if key and serp:
            try:
                hits = await Client(ctx.http, key, serp, timeout=60, what="SERP API zone").serp_page(
                    "theron", country=country, language=(values.get("language") or "").strip())
            except UnlockError as exc:
                ok = False
                lines.append(ctx.tr("✖ SERP API: {error}", error=exc))
            else:
                lines.append(ctx.tr("✔ SERP API · zone {zone} · {n} results · per 1,000 searches: {cost}", zone=serp,
                                    n=len(hits), cost=ctx.tr(SERP_COST)))
        if user and password:
            try:
                page = await browser.fetch("https://example.com/", browser.auth(user, password, country), timeout=60,
                                           wait=0)
            except browser.BrowserError as exc:
                ok = False
                lines.append(ctx.tr("✖ Browser API: {error}", error=exc))
            else:
                lines.append(ctx.tr("✔ Browser API · test page “{title}” · {cost}", title=page["title"],
                                    cost=ctx.tr(browser.COST)))
        return ok, "\n".join(lines)

    ctx.settings.add_button("Test", test, tooltip="Checks every part that is filled in – one billed request each "
                                                  "(example.com, one search, example.com in the browser).")
