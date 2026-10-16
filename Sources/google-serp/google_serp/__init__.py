"""Google SERP for Theron: the process node 🔎 Google search – a query from the input, the URLs of the hits on – via
SerpApi or Serper, and a "Test" button for the API key (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

from .api import PROVIDERS, Client, SerpError
from .node import SearchNode


def register(ctx):
    SearchNode(ctx).register()

    async def test(values: dict):
        key = (values.get("api_key") or "").strip()
        if not key:
            return False, ctx.tr("Enter the API key first.")
        client = Client(ctx.http, key, values.get("provider") or "serpapi")
        try:
            acc = await client.account()
        except SerpError as exc:
            return False, ctx.tr("{provider} says: {error}", provider=client.name, error=exc)
        cost = ctx.tr(PROVIDERS[client.provider]["cost"])
        if acc.get("left") is not None:
            return True, ctx.tr("Connected to {provider} · plan {plan} · {left} of {per_month} searches left this "
                                "month · per 1,000 searches: {cost}", provider=client.name, plan=acc["plan"] or "?",
                                left=f"{int(acc['left']):,}", per_month=f"{int(acc.get('per_month') or 0):,}",
                                cost=cost)
        return True, ctx.tr("Connected to {provider} (one test search) · per 1,000 searches: {cost}",
                            provider=client.name, cost=cost)

    ctx.settings.add_button("Test", test, tooltip="Checks the API key with the provider.")
