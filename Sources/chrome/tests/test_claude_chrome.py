"""Claude in Chrome (node field Browser → claude) with a fake Claude Code agent – no Chrome, no Claude needed:
    python -m pytest Sources/chrome/tests/test_claude_chrome.py   (with Theron 0.25+ on the path)"""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

from chrome_scraper import claude_chrome as C  # noqa: E402
from theron.plugins.context import AgentResult, ToolCall  # noqa: E402

PAGE = "Pahlen Elektroheizer 3 kW\n\nPreis: 679,95 €\nIn den Warenkorb"


def browsers(*names):
    return json.dumps([{"name": n, "osPlatform": "macOS", "deviceId": f"id-{i}", "isLocal": True}
                       for i, n in enumerate(names)]) + "2 browsers are connected …"


class FakeAgent:
    """Answers like Claude in Chrome would: the browser list, then per page get_page_text + javascript_tool."""

    def __init__(self, listing, blocked=()):
        self.listing, self.blocked, self.prompts = listing, set(blocked), []

    async def __call__(self, prompt, *, cwd=None, system="", model="", tools=None, max_turns=30, session_id="",
                       on_text=None, chrome=False):
        assert chrome and tools == [] and model == "haiku"
        self.prompts.append(prompt)
        if "list_connected_browsers" in prompt:
            return AgentResult(text="DONE", tool_calls=[ToolCall("mcp__claude-in-chrome__list_connected_browsers",
                                                                 {}, self.listing)])
        url = next(u for u in ("https://a.de/x", "https://b.de/y") if u in prompt or "tab with id" in prompt)
        if url in self.blocked and "tab with id" not in prompt:
            return AgentResult(text="BLOCKED tab=42: Cloudflare check")
        info = json.dumps({"title": f"Titel {url[-1]}", "url": url, **({"html": "<html>x</html>"}
                                                                      if "outerHTML" in prompt else {})})
        return AgentResult(text="OK", tool_calls=[
            ToolCall("mcp__claude-in-chrome__navigate", {"url": url}, "ok"),
            ToolCall("mcp__claude-in-chrome__get_page_text", {"tabId": 1}, PAGE),
            ToolCall("mcp__claude-in-chrome__javascript_tool", {"tabId": 1}, info)])


class FakeNode:
    def __init__(self, answers=()):
        self.answers, self.asked = list(answers), []

    async def ask(self, question, options, recommended=None):
        self.asked.append((question, options))
        return self.answers.pop(0)


def ctx_with(agent, store=None):
    store = {} if store is None else store
    return SimpleNamespace(ai=SimpleNamespace(agent=agent), tr=lambda s, **kw: s.format(**kw) if kw else s,
                           settings={"ask_user": True},
                           storage=SimpleNamespace(get=lambda k, d=None: store.get(k, d),
                                                   set=lambda k, v: store.__setitem__(k, v)))


def run(cc, node, urls, cfg=None):
    seen = []
    res = asyncio.run(cc.run(node, urls, cfg or {"format": "markdown"}, seen.append))
    return res, seen


def test_pages_come_verbatim_from_the_tools():
    agent = FakeAgent(browsers("MacBook"))
    res, seen = run(C.ClaudeChrome(ctx_with(agent)), FakeNode(), ["https://a.de/x", "https://b.de/y"],
                    {"format": "both"})
    assert seen == [1, 2]
    a = res["https://a.de/x"]
    assert a["markdown"] == PAGE and a["title"] == "Titel x" and a["raw"] == "<html>x</html>" and not a.get("error")
    assert 'select_browser with deviceId "id-0"' in agent.prompts[1] and "never try to solve a CAPTCHA" in agent.prompts[1]


def test_several_browsers_the_user_picks_once():
    store = {}
    agent = FakeAgent(browsers("Browser 1", "Browser 2"))
    node = FakeNode(["Browser 2 (macOS, this computer)"])
    res, _ = run(C.ClaudeChrome(ctx_with(agent, store)), node, ["https://a.de/x"])
    assert len(node.asked) == 1 and node.asked[0][1] == ["Browser 1 (macOS, this computer)",
                                                         "Browser 2 (macOS, this computer)"]
    assert store[C.BROWSER_KEY] == "id-1" and '"id-1"' in agent.prompts[-1]
    node2 = FakeNode()
    run(C.ClaudeChrome(ctx_with(FakeAgent(browsers("Browser 1", "Browser 2")), store)), node2, ["https://a.de/x"])
    assert node2.asked == []   # remembered


def test_no_extension_and_a_bot_check():
    res, _ = run(C.ClaudeChrome(ctx_with(FakeAgent("[]"))), FakeNode(), ["https://a.de/x"])
    assert "No Chrome with the Claude extension" in res["https://a.de/x"]["error"]
    agent = FakeAgent(browsers("One"), blocked={"https://a.de/x"})
    node = FakeNode(["Done"])
    res, _ = run(C.ClaudeChrome(ctx_with(agent)), node, ["https://a.de/x"])
    assert "Cloudflare" in node.asked[0][0] and res["https://a.de/x"]["markdown"] == PAGE   # read after the user
    assert "tab with id 42" in agent.prompts[-1]
    node = FakeNode(["Skip"])
    res, _ = run(C.ClaudeChrome(ctx_with(FakeAgent(browsers("One"), blocked={"https://a.de/x"}))), node,
                 ["https://a.de/x"])
    assert res["https://a.de/x"]["blocked"] and res["https://a.de/x"]["error"]


def test_older_theron_or_a_server():
    async def old_agent(prompt, *, cwd=None, system="", model="", tools=None, max_turns=30, session_id="",
                        on_text=None):
        return AgentResult()
    assert "0.25" in C.unavailable(ctx_with(old_agent))
    assert C.unavailable(ctx_with(FakeAgent("[]"))) == "" or not C.has_display()


# ------------------------------------------------------------------ the node, through Theron
from test_chrome import env, run_node  # noqa: E402,F401


def test_the_node_with_claude_in_chrome(env, monkeypatch):
    store, pm, ctx, tmp = env
    agent = FakeAgent(browsers("MacBook"))
    monkeypatch.setattr(ctx.ai, "agent", agent)
    monkeypatch.setattr(C, "has_display", lambda: True)
    monkeypatch.setattr(C, "in_container", lambda: False)
    inbox, _ = run_node(store, pm, tmp, {"browser": "claude"}, "URLS:\nhttps://a.de/x\nhttps://b.de/y\n")
    text = inbox["n"][0]["text"]
    assert "2 of 2 pages" in text and "FILES:" in text and "679,95 €" in text
    md = sorted((tmp / "ws" / "scraped").glob("*.md"))
    assert len(md) == 2 and PAGE in md[0].read_text()
