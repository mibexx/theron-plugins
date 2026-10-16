"""The process node ✦ Google research: Gemini answers with Google Search behind it ("Grounding with Google Search")
and hands on the answer with its sources – or only the source URLs, like a search."""

from __future__ import annotations

import time
from urllib.parse import quote_plus

from .gemini import ALIASES, DEFAULT_MODEL, Gemini, GeminiError
from .node import HANDOVER, material_of

SYSTEM = ("You research with Google Search and answer from what you find – precise, factual, current. Name numbers, "
          "dates and names exactly. If the sources disagree or say nothing, say so. No speculation.")


class GroundingNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def key(self, values: dict | None = None) -> str:
        v = values if values is not None else self.ctx.settings.all()
        return (v.get("gemini_key") or v.get("api_key") or "").strip()

    def model_options(self, cfg: dict) -> list:
        cached = (self.ctx.storage.get("models") or {}).get("models") or []
        names = list(dict.fromkeys(ALIASES + cached))
        if cfg.get("model") and cfg["model"] not in names:
            names.append(cfg["model"])
        return names

    async def refresh_models(self, key: str | None = None) -> list[str]:
        models = await Gemini(self.ctx.http, key or self.key()).models()
        self.ctx.storage.set("models", {"models": models, "at": time.time()})
        return models

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "research", label="Google research (Gemini)", icon="✦", run=self.run,
            description="Gemini researches the question of the input with Google Search and answers with its sources "
                        "(Grounding with Google Search) – or hands on only the source URLs, like a search.",
            ai_hint="Research a question on the web with Google Search through Gemini (grounding): hands on a sourced "
                    "answer plus the source URLs (URLS: block) – or only the URLs. Outputs: answer, error.",
            outputs=[{"id": "answer", "label": tr("Answer"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "result", "type": "choice", "label": "Hand on", "default": "answer",
                 "options": [{"value": "answer", "label": "The answer with its sources"},
                             {"value": "urls", "label": "Only the source URLs (like a search)"}]},
                {"key": "model", "type": "choice", "label": "Model", "default": DEFAULT_MODEL,
                 "options": self.model_options,
                 "description": "“…-latest” follows Google's newest model. The list fills itself after “Test” in "
                                "the settings."},
                {"key": "max_sources", "type": "number", "label": "At most sources", "default": 10,
                 "description": "Gemini decides how many sources it uses (often 3–10) – this only caps them."},
                {"key": "resolve", "type": "bool", "label": "Real page addresses", "default": True,
                 "description": "Follows Google's redirect links to the pages (needed e.g. for the Chrome Scraper)."},
                {"key": "language", "type": "text", "label": "Answer language (optional)",
                 "description": "e.g. German or en – empty: the language of the question."},
            ])

    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        try:
            gem = Gemini(self.ctx.http, self.key())
        except GeminiError as exc:
            return node.route("error", str(exc))
        question = material_of(node)
        if not question.strip():
            return node.route("error", tr("Nothing to research – the input is empty."))
        lang = (cfg.get("language") or "").strip()
        prompt = ((f"INSTRUCTIONS:\n{node.instructions}\n\n" if node.instructions else "")
                  + f"RESEARCH THIS:\n{question[:20000]}"
                  + (f"\n\nAnswer in {lang}." if lang else ""))
        node.progress(tr("researches with Google …"))
        try:
            res = await gem.ask(prompt, model=cfg.get("model") or DEFAULT_MODEL, system=SYSTEM)
        except GeminiError as exc:
            return node.route("error", tr("Gemini: {error}", error=exc))
        sources = res["sources"][:max(1, int(cfg.get("max_sources") or 10))]
        if cfg.get("resolve", True) and sources:
            node.progress(tr("opens {n} sources …", n=len(sources)))
            sources = await gem.resolve(sources)
        if not res["text"] and not sources:
            return node.route("error", tr("Gemini found nothing ({why}).", why=res["finish"] or "?"))
        seen, unique = set(), []
        for s in sources:
            if s["url"].rstrip("/") not in seen:
                seen.add(s["url"].rstrip("/"))
                unique.append(s)
        links = [f"{i}. [{(s['title'] or s['url']).replace('[', '(').replace(']', ')')}]({s['url']})"
                 for i, s in enumerate(unique, 1)]
        # Google's terms: show the search suggestions with grounded results – as links to Google
        suggest = " · ".join(f"[{q}](https://www.google.com/search?q={quote_plus(q)})" for q in res["queries"])
        node.say(text=(res["text"] if cfg.get("result") != "urls" else tr("✦ {n} sources", n=len(unique)))
                 + ("\n\n**" + tr("Sources") + "**\n" + "\n".join(links) if links else "")
                 + ("\n\n" + tr("Google searches: {q}", q=suggest) if suggest else ""))
        node.progress(tr("✦ {n} sources", n=len(unique)))
        text = tr("Google research with Gemini – {n} sources:", n=len(unique))
        if unique:
            text += "\n\nURLS:\n" + "\n".join(s["url"] for s in unique)
        if res["queries"]:
            text += "\n\n" + tr("Searched for: {q}", q="; ".join(res["queries"]))
        if cfg.get("result") != "urls":
            sources_text = "\n\nSOURCES:\n" + "\n".join(f"[{i}] {s['title']} – {s['url']}"
                                                       for i, s in enumerate(unique, 1))
            room = HANDOVER - len(text) - len(sources_text) - 20
            answer = res["text"] if len(res["text"]) <= room else res["text"][:max(room, 500)].rstrip() + " …"
            text += "\n\nANSWER:\n" + answer + sources_text
        return node.route("answer", text[:HANDOVER])
