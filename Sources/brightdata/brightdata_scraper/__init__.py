"""Bright Data for Theron: the process node 🛰 Scrape pages (Bright Data) – web pages through the Web Unlocker,
past bot protection, as Markdown or raw HTML – and a "Test" button for API key and zone (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

from .api import COST, Client, UnlockError
from .node import ScrapeNode


def register(ctx):
    ScrapeNode(ctx).register()

    async def test(values: dict):
        key = (values.get("api_key") or "").strip()
        if not key:
            return False, ctx.tr("Enter the API key first.")
        zone = (values.get("zone") or "").strip()
        if not zone:
            return False, ctx.tr("Enter the name of your Web Unlocker zone.")
        client = Client(ctx.http, key, zone, timeout=60)
        try:
            page = await client.unlock("https://example.com/", markdown=True,
                                       country=(values.get("country") or "").strip())
        except UnlockError as exc:
            return False, ctx.tr("Bright Data says: {error}", error=exc)
        if page["status"] >= 400:
            return False, ctx.tr("Connected, but the test page came back with HTTP {status}.", status=page["status"])
        return True, ctx.tr("Connected · zone {zone} · test page loaded ({chars} characters) · per 1,000 pages: "
                            "{cost}", zone=zone, chars=f"{len(page['body']):,}", cost=ctx.tr(COST))

    ctx.settings.add_button("Test", test, tooltip="Loads example.com once through your zone (one billed request).")
