"""The process node 🔎 Google search: a query from the input → the URLs of the hits."""

from __future__ import annotations

import json
import re

from .api import MAX_RESULTS, Client, SerpError

COUNT_IN_TEXT = re.compile(
    r"(?:\b(?:top|die|the|first|ersten?)\s+(\d{1,3})\b)"
    r"|(?:\b(\d{1,3})\s*(?:urls?|treffer|ergebnisse|results|hits|links|seiten|websites?|quellen|sources)\b)"
    r"|(?:\b(?:count|anzahl)\s*[:=]\s*(\d{1,3})\b)", re.I)


def material_of(node) -> str:
    """The orchestrator's assignment for this step and what the steps before handed over."""
    task, given = (node.task or "").strip(), (node.input or "").strip()
    if not given or task in given:
        return task or given
    if not task or given in task:
        return given
    return f"ASSIGNMENT FOR THIS STEP:\n{task}\n\nHAND-OVERS FROM THE STEPS BEFORE:\n{given}"


def raw_input(node) -> str:
    """The plain text for “as it is” / templates: the newest hand-over itself (without Theron's headings),
    else the orchestrator's assignment for this step."""
    for h in reversed(node.handovers or []):
        if (h.get("text") or "").strip():
            return h["text"].strip()
    return (node.task or node.input or "").strip()


def count_in(text: str) -> int | None:
    """“top 20”, “30 URLs”, “Anzahl: 5” … – the last one named wins (the newest hand-over is at the end)."""
    found = [int(next(g for g in m.groups() if g)) for m in COUNT_IN_TEXT.finditer(text or "")]
    found = [n for n in found if 1 <= n <= MAX_RESULTS]
    return found[-1] if found else None


def json_in(text: str):
    text = re.sub(r"```(?:json)?", "", text or "")
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            return None
    return None


def sites(text: str) -> list[str]:
    return [s.lower().removeprefix("www.").strip("/ ") for s in re.split(r"[,;\s]+", text or "")
            if "." in s]


class SearchNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "search", label="Google search", icon="🔎", run=self.run,
            description="Asks Google – the query comes from the input (written by the AI, taken as it is, or a "
                        "template) – and hands on the URLs of the hits; how many is set here or read from the input.",
            ai_hint="Google search via SERP API: turns the incoming text into a query and hands on the URLs of the "
                    "top results (count fixed in the node or from the text, e.g. 'top 20'). Outputs: urls, empty "
                    "(no hits), error (no API key, no searches left).",
            outputs=[{"id": "urls", "label": tr("URLs"), "color": "success"},
                     {"id": "empty", "label": tr("No results"), "color": "neutral"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "query_mode", "type": "choice", "label": "Query", "default": "ai",
                 "options": [{"value": "ai", "label": "AI writes it from the input"},
                             {"value": "input", "label": "The input as it is"},
                             {"value": "template", "label": "Template below"}]},
                {"key": "template", "type": "text", "label": "Template", "default": "{input}",
                 "show_if": {"query_mode": "template"},
                 "description": "The query – {input} is replaced by the incoming text, e.g. "
                                "“{input} site:github.com”."},
                {"key": "count_mode", "type": "choice", "label": "Number of results", "default": "fixed",
                 "options": [{"value": "fixed", "label": "Fixed – the number below"},
                             {"value": "input", "label": "From the input (e.g. “top 20”), else the number below"}]},
                {"key": "count", "type": "number", "label": "Results", "default": 10,
                 "description": "1–100. Google gives 10 per page: every started 10 is one search on your plan."},
                {"key": "country", "type": "text", "label": "Country (optional)",
                 "description": "Two letters like de, us, ch – Google of that country. Empty: the setting."},
                {"key": "language", "type": "text", "label": "Language (optional)",
                 "description": "Two letters like de or en. Empty: the setting."},
                {"key": "exclude", "type": "text", "label": "Leave out sites (optional)",
                 "description": "e.g. “pinterest.com, youtube.com” – hits from these sites are skipped."},
            ])

    async def plan(self, node) -> tuple[str, int]:
        """The query and how many results."""
        cfg = node.config
        material = material_of(node)
        try:
            fixed = int(cfg.get("count") or 10)
        except (TypeError, ValueError):
            fixed = 10
        fixed = max(1, min(fixed, MAX_RESULTS))
        from_input = cfg.get("count_mode") == "input"
        count = (count_in(material) if from_input else None)
        mode = cfg.get("query_mode") or "ai"
        if mode == "template":
            query = (cfg.get("template") or "{input}").replace("{input}", _one_line(raw_input(node)))
        elif mode == "input":
            query = _one_line(raw_input(node))
        else:
            query, said = await self.ask_ai(node, material, from_input and count is None)
            count = count or said
        return query.strip()[:400], count or fixed

    async def ask_ai(self, node, material: str, want_count: bool) -> tuple[str, int | None]:
        prompt = ("Write the ONE Google search query that finds what this step is looking for – the words a good "
                  "researcher would type into Google (operators like site:, quotes or - are fine), in the language "
                  "the results should be in. No explanation.\n"
                  + ("Also say how many results the text asks for (a number), or null if it doesn't say.\n"
                     if want_count else "")
                  + (f"\nINSTRUCTIONS FROM THE USER:\n{node.instructions}\n" if node.instructions else "")
                  + f"\nTEXT:\n{material[:8000]}\n\n"
                  + ('Answer only JSON: {"query": "…", "count": N or null}' if want_count
                     else 'Answer only JSON: {"query": "…"}'))
        try:
            data = json_in(await self.ctx.ai.ask(prompt, system="You write Google search queries.",
                                                 model="haiku")) or {}
        except Exception as exc:  # noqa: BLE001 – no AI: the text itself
            self.ctx.log.error(f"query: {exc}")
            data = {}
        query = str(data.get("query") or "").strip() or _one_line(material)
        try:
            count = int(data.get("count")) if data.get("count") is not None else None
        except (TypeError, ValueError):
            count = None
        return query, count if count and 1 <= count <= MAX_RESULTS else None

    async def run(self, node):
        tr = self.ctx.tr
        s = self.ctx.settings
        try:
            client = Client(self.ctx.http, s.get("api_key") or "", s.get("provider") or "serpapi")
        except SerpError as exc:
            return node.route("error", str(exc))
        node.progress(tr("writes the query …"))
        query, count = await self.plan(node)
        if not query:
            return node.route("error", tr("Nothing to search for – the input is empty."))
        cfg = node.config
        country = (cfg.get("country") or s.get("country") or "").strip().lower()
        language = (cfg.get("language") or s.get("language") or "").strip().lower()
        node.progress(tr("🔎 {query}", query=query[:120]))
        try:
            results, pages = await client.search(query, count, country=country, language=language,
                                                 exclude=sites(cfg.get("exclude") or ""))
        except SerpError as exc:
            return node.route("error", tr("{provider}: {error}", provider=client.name, error=exc))
        if not results:
            node.say(text=tr("🔎 **{query}** – Google found nothing.", query=query))
            return node.route("empty", tr("Google found nothing for “{query}”.", query=query))
        lines = "\n".join(f"{i}. [{_md(r['title'] or r['url'])}]({r['url']})" for i, r in enumerate(results, 1))
        node.say(text=tr("🔎 **{query}** – {n} results ({pages} searches)", query=query, n=len(results),
                         pages=pages) + "\n\n" + lines)
        node.progress(tr("🔎 {n} URLs", n=len(results)))
        listing = "\n".join(f"{i}. {r['title']} – {r['url']}" + (f"\n   {r['snippet']}" if r["snippet"] else "")
                            for i, r in enumerate(results, 1))
        return node.route("urls", tr("Google search “{query}” – {n} results:", query=query, n=len(results))
                          + f"\n{listing}\n\nURLS:\n" + "\n".join(r["url"] for r in results))


def _one_line(text: str) -> str:
    return " ".join((text or "").split())[:400]


def _md(text: str) -> str:
    return re.sub(r"([\[\]])", r"\\\1", text)
