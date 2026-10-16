"""Claude in Chrome: the pages are loaded in the user's own Chrome – the Claude extension, driven by a Claude Code
agent (``ctx.ai.agent(..., chrome=True)``, Theron 0.25+). The tools' answers (the page text, the HTML) are taken
verbatim from the agent's tool calls – the model doesn't retell the page. One page after the other (one browser);
a bot check is never solved by the agent: the user does it in their Chrome, or the page is skipped."""

from __future__ import annotations

import inspect
import json
import re

from .cdp import has_display, in_container

BROWSER_KEY = "claude_browser"   # ctx.storage: the Chrome the user picked when several are connected
MODEL = "haiku"

RULES = ("Rules: never click, type, fill in or submit anything on the page; never log in; never try to solve a "
         "CAPTCHA or a bot check; never open any other URL than the one given; do not describe the page.")


def supported(ctx) -> bool:
    try:
        return "chrome" in inspect.signature(ctx.ai.agent).parameters
    except (TypeError, ValueError, AttributeError):
        return False


def unavailable(ctx) -> str:
    """Why Claude in Chrome can't be used here – "" if it can."""
    tr = ctx.tr
    if not supported(ctx):
        return tr("Claude in Chrome needs Theron 0.25 or newer – update Theron or choose “Own Chrome” in the node.")
    if in_container() or not has_display():
        return tr("Claude in Chrome works on a desktop only (your Chrome with the Claude extension) – on a server, "
                  "choose “Own Chrome” in the node.")
    return ""


def browsers_in(output: str) -> list[dict]:
    """The connected browsers from the answer of ``list_connected_browsers`` (a JSON list, maybe text after it)."""
    start = (output or "").find("[")
    if start < 0:
        return []
    try:
        found, _ = json.JSONDecoder().raw_decode(output[start:])
    except ValueError:
        return []
    return [b for b in found if isinstance(b, dict)] if isinstance(found, list) else []


def label_of(b: dict, ctx) -> str:
    name = str(b.get("name") or "Chrome")
    extra = [str(b["osPlatform"])] if b.get("osPlatform") else []
    if b.get("isLocal"):
        extra.append(ctx.tr("this computer"))
    return f"{name} ({', '.join(extra)})" if extra else name


def tool_out(result, suffix: str) -> tuple[str, bool] | None:
    """The last answer of the tool ``…__<suffix>`` – (output, is_error) – or None."""
    for call in reversed(getattr(result, "tool_calls", None) or []):
        if call.name.endswith("__" + suffix) or call.name == suffix:
            return call.output or "", bool(call.is_error)
    return None


def page_info(output: str) -> dict:
    """The JSON the page script returned (title, url, html)."""
    text = (output or "").strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return {}
    if isinstance(data, str):   # returned as a JSON string inside the tool's text
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    return data if isinstance(data, dict) else {}


class ClaudeChrome:
    def __init__(self, ctx):
        self.ctx = ctx

    async def _agent(self, prompt: str):
        return await self.ctx.ai.agent(prompt, tools=[], chrome=True, model=MODEL, max_turns=14)

    # ------------------------------------------------------------------ which Chrome
    async def pick_browser(self, node) -> tuple[str, str]:
        """(device id or "" for the only one, error). Several connected: the user picks one (remembered)."""
        tr = self.ctx.tr
        res = await self._agent("Call the tool list_connected_browsers exactly once and nothing else. Do not select "
                                "a browser and do not ask anything. Then answer only: DONE.")
        out = tool_out(res, "list_connected_browsers")
        if out is None or out[1]:
            return "", tr("Claude in Chrome is not available – install the Claude extension in Chrome, sign in with "
                          "your Claude account and keep Chrome open. ({detail})",
                          detail=((out or ("",))[0] or res.text or "?")[:200])
        found = browsers_in(out[0])
        if not found:
            return "", tr("No Chrome with the Claude extension is connected – open Chrome and sign in to the Claude "
                          "extension.")
        ids = [str(b.get("deviceId") or "") for b in found]
        if len(found) == 1:
            return ids[0], ""
        stored = self.ctx.storage.get(BROWSER_KEY) or ""
        if stored and stored in ids:
            return stored, ""
        labels = [label_of(b, self.ctx) for b in found]
        labels = [f"{n}. {lab}" for n, lab in enumerate(labels, 1)] if len(set(labels)) < len(labels) else labels
        answer = (await node.ask(tr("Several Chrome browsers are connected to Claude in Chrome. Which one should load "
                                    "the pages? (Theron remembers it.)"), labels, recommended=0) or "").strip()
        if answer not in labels:
            return "", tr("No Chrome chosen for Claude in Chrome.")
        chosen = ids[labels.index(answer)]
        self.ctx.storage.set(BROWSER_KEY, chosen)
        return chosen, ""

    # ------------------------------------------------------------------ one page
    def _prompt(self, url: str, device: str, html: bool, tab: str = "") -> str:
        script = ("JSON.stringify({title: document.title, url: location.href"
                  + (", html: '<!DOCTYPE html>\\n' + document.documentElement.outerHTML" if html else "") + "})")
        select = f"First call select_browser with deviceId {json.dumps(device)}. " if device else ""
        if tab:
            open_it = f"Use the tab with id {tab} that is already open (tabs_context_mcp to find it). "
        else:
            open_it = (f"Call tabs_context_mcp, open a NEW tab with tabs_create_mcp and navigate that tab to "
                       f"{json.dumps(url)}. Wait until the page has loaded (use the computer tool's wait action for "
                       f"2 seconds if it still loads). ")
        return (select + open_it
                + "If the page shows a CAPTCHA, a bot check, 'verify you are human', 'Just a moment' or an access "
                  "denied page: leave the tab open and answer only 'BLOCKED tab=<tab id>: <what it shows in a few "
                  "words>'. Otherwise call get_page_text for that tab, then call javascript_tool on that tab with "
                  f"exactly this code: {script} – then close the tab with tabs_close_mcp and answer only 'OK'. "
                + RULES)

    async def load(self, url: str, device: str, html: bool, tab: str = "") -> dict:
        tr = self.ctx.tr
        try:
            res = await self._agent(self._prompt(url, device, html, tab))
        except Exception as exc:  # noqa: BLE001 – Claude Code not there, not logged in …
            return {"url": url, "error": tr("Claude in Chrome: {error}", error=str(exc)[:300] or exc.__class__.__name__)}
        answer = (res.text or "").strip()
        m = re.search(r"BLOCKED\s*tab\s*=\s*(\w+)\s*:?\s*(.*)", answer, re.S)
        if m:
            return {"url": url, "blocked": (m.group(2).strip()[:80] or "bot check"), "tab": m.group(1),
                    "error": tr("blocked by bot protection ({name})", name=m.group(2).strip()[:80] or "?")}
        text = tool_out(res, "get_page_text")
        info = tool_out(res, "javascript_tool")
        data = page_info(info[0]) if info and not info[1] else {}
        if (text is None or text[1] or not text[0].strip()) and not data.get("html"):
            why = (text[0] if text else "") or answer or tr("no page text")
            return {"url": url, "error": tr("Claude in Chrome: {error}", error=" ".join(why.split())[:300])}
        body = text[0].strip() if text and not text[1] else ""
        return {"url": url, "title": str(data.get("title") or ""), "final_url": str(data.get("url") or url),
                "markdown": body, "text": body, "raw": str(data.get("html") or ""), "status": None, "mime": ""}

    async def run(self, node, urls: list[str], cfg: dict, done) -> dict[str, dict]:
        """All pages, one after the other – ``done(n)`` reports the progress."""
        tr = self.ctx.tr
        device, err = await self.pick_browser(node)
        if err:
            return {u: {"url": u, "error": err} for u in urls}
        html = (cfg.get("format") or "markdown") in ("html", "both")
        results: dict[str, dict] = {}
        for n, url in enumerate(urls, 1):
            r = await self.load(url, device, html)
            if r.get("blocked") and self.ctx.settings.get("ask_user", True):
                answer = await node.ask(
                    tr("{url} is protected by a bot check ({name}). Please solve it in the tab in your Chrome, then "
                       "answer “Done”.", url=url, name=r["blocked"]),
                    [tr("Done"), tr("Skip")], recommended=1)
                if (answer or "").strip().lower() not in (tr("Skip").lower(), "skip", "überspringen"):
                    r = await self.load(url, device, html, tab=r.get("tab") or "")
            r.pop("tab", None)
            results[url] = r
            done(n)
        return results
