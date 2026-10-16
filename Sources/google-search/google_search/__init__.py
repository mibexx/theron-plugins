"""Google Search for Theron: the process node 🔎 Google Search – a query from the input, the URLs of the
hits on – via Google's Custom Search JSON API (Google Cloud), with a "Test" button (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

from .api import COST, Client, CseError
from .node import SearchNode


def register(ctx):
    SearchNode(ctx).register()

    async def test(values: dict):
        key, cx = (values.get("api_key") or "").strip(), (values.get("cx") or "").strip()
        if not key or not cx:
            return False, ctx.tr("Enter the API key and the search engine id (cx) first.")
        try:
            hits = await Client(ctx.http, key, cx).page("theron", 0)
        except CseError as exc:
            return False, ctx.tr("Google says: {error}", error=exc)
        return True, ctx.tr("Connected · {n} results for a test query (1 of your daily queries) · cost: {cost}",
                            n=len(hits), cost=ctx.tr(COST))

    ctx.settings.add_button("Test", test, tooltip="Makes one test query with the key and the search engine id.")
