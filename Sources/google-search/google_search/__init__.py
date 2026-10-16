"""Google Search for Theron – Google's own APIs as process nodes (theron_api 1, Theron ≥ 0.20):

- 🔎 Google Search: the Custom Search JSON API (Google Cloud) – a query from the input, the URLs of the hits on;
- ✦ Google research (Gemini): Grounding with Google Search – Gemini answers with its sources, or only their URLs.

"Test" in the settings checks both (whatever is filled in) and loads the Gemini models for the node."""

from __future__ import annotations

from .api import COST, Client, CseError
from .gemini import COST as GEMINI_COST
from .gemini import Gemini, GeminiError
from .grounding import GroundingNode
from .node import SearchNode


def register(ctx):
    SearchNode(ctx).register()
    grounding = GroundingNode(ctx)
    grounding.register()
    ctx.grounding = grounding   # for the tests

    async def test(values: dict):
        key, cx = (values.get("api_key") or "").strip(), (values.get("cx") or "").strip()
        gkey = grounding.key(values)
        if not gkey and not (key and cx):
            return False, ctx.tr("Enter the API key and the search engine id (cx) – and / or a Gemini API key.")
        lines, ok = [], True
        if key and cx:
            try:
                hits = await Client(ctx.http, key, cx).page("theron", 0)
                lines.append(ctx.tr("Custom Search ✔ · {n} results for a test query (1 of your daily queries) · "
                                    "{cost}", n=len(hits), cost=ctx.tr(COST)))
            except CseError as exc:
                ok = False
                lines.append(ctx.tr("Custom Search ✖ {error}", error=exc))
        if gkey:
            try:
                models = await grounding.refresh_models(gkey)
                lines.append(ctx.tr("Gemini ✔ · {n} models (in the node now) · {cost}", n=len(models),
                                    cost=ctx.tr(GEMINI_COST)))
            except GeminiError as exc:
                ok = False
                lines.append(ctx.tr("Gemini ✖ {error}", error=exc))
        return ok, "\n".join(lines)

    ctx.settings.add_button("Test", test, tooltip="Checks the Custom Search key and search engine id (one query) "
                                                  "and the Gemini key (lists its models, free).")

    @ctx.on_start
    def start():
        if grounding.key() and not ctx.storage.get("models"):
            ctx.spawn(grounding.refresh_models)
