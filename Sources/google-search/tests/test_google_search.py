"""Google Search plugin against a fake Custom Search JSON API and a fake AI – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/google-search/tests"""
import asyncio
import json
import os
import urllib.parse
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.plugins.http import Response  # noqa: E402
from theron.store import Store  # noqa: E402


class FakeGoogle:
    def __init__(self):
        self.key, self.cx = "good", "cx1"
        self.calls = []
        self.total = 35
        self.left = 100
        self.gemini_key = "gem"
        self.gemini_calls = []
        self.grounding_quota = 10

    async def request(self, method, url, *, params=None, headers=None, json=None, **kw):
        u = urllib.parse.urlparse(url)
        p = dict(params or {})
        self.calls.append((method, u.netloc + u.path, p))

        def answer(status, body):
            return Response(url, status, {}, __import__("json").dumps(body).encode())
        if u.netloc == "vertexaisearch.cloud.google.com":   # Google's redirect links of grounding
            target = "https://" + u.path.rsplit("/", 1)[1] + ".example/page"
            return Response(target, 200, {}, b"<html></html>")
        if u.netloc == "generativelanguage.googleapis.com":
            return self.gemini(method, u.path, p, headers or {}, json, answer)
        if u.netloc + u.path != "www.googleapis.com/customsearch/v1":
            return answer(404, {})
        if p.get("key") != self.key:
            return answer(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                          "errors": [{"reason": "badRequest"}], "status": "INVALID_ARGUMENT"}})
        if p.get("cx") != self.cx:
            return answer(400, {"error": {"code": 400, "message": "Request contains an invalid argument.",
                                          "status": "INVALID_ARGUMENT"}})
        if self.left <= 0:
            return answer(429, {"error": {"code": 429, "message": "Quota exceeded for quota metric 'Queries' and "
                                          "limit 'Queries per day'", "status": "RESOURCE_EXHAUSTED"}})
        self.left -= 1
        start = int(p["start"]) - 1
        items = [{"title": f"{p['q']} #{i + 1}", "link": f"https://site{i + 1}.example/{p['q'].split()[0]}",
                  "snippet": f"about\n{p['q']}"} for i in range(start, min(start + int(p["num"]), self.total))]
        return answer(200, {"kind": "customsearch#search", **({"items": items} if items else {})})


    def gemini(self, method, path, params, headers, body, answer):
        self.gemini_calls.append((method, path, body))
        if headers.get("x-goog-api-key") != self.gemini_key:
            return answer(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                          "status": "INVALID_ARGUMENT"}})
        if path == "/v1beta/models":
            return answer(200, {"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
        if path.endswith(":generateContent"):
            if self.grounding_quota <= 0:
                return answer(429, {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).",
                                              "status": "RESOURCE_EXHAUSTED"}})
            self.grounding_quota -= 1
            assert body["tools"] == [{"google_search": {}}]
            redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
            return answer(200, {"candidates": [{"content": {"parts": [{"text": "Qdrant und Milvus führen 2026 [1][2]."}]},
                                                "finishReason": "STOP", "groundingMetadata": {
                "webSearchQueries": ["beste vektordatenbank 2026"],
                "groundingChunks": [{"web": {"uri": redirect + "qdrant", "title": "qdrant.tech"}},
                                    {"web": {"uri": redirect + "milvus", "title": "milvus.io"}},
                                    {"web": {"uri": redirect + "qdrant", "title": "qdrant.tech"}},
                                    {"web": {"uri": "https://direct.example/x", "title": "direct.example"}}]}}]})
        return answer(404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}})


class FakeAi:
    def __init__(self):
        self.prompts, self.count = [], None

    async def ask(self, prompt, system="", model="haiku"):
        self.prompts.append(prompt)
        return json.dumps({"query": "beste vektordatenbanken 2026", "count": self.count})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "google-search.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["google-search"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("google-search")
    ctx.http = fake = FakeGoogle()
    ctx.ai = ai = FakeAi()
    ctx.settings.update({"api_key": "good", "cx": "cx1"})
    return store, pm, ctx, fake, ai, tmp_path


def run_node(store, pm, tmp, cfg=None, text="Finde Vergleiche der besten Vektordatenbanken"):
    node = pm.node("google-search/search")
    cfg = {**node.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "Recherche", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": {"urls": "n", "empty": "e", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "e", "agent_id": None, "on_success": "end"},
        {"id": "x", "agent_id": None, "on_success": "end"}]})
    proj = store.save("project", {"name": "R", "workspace": str(tmp / "ws"), "process_id": pid})
    ctrl = Engine(store).controller(store.create_run(proj, "Recherche"))
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h1", "from": "Planer", "agent": "Planer", "text": text}]})
    asyncio.run(ctrl._execute(0, ""))
    return store.run(ctrl.run_id).get("inbox") or {}, ctrl


def urls(inbox):
    return inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()


def test_the_ai_writes_the_query_and_the_urls_go_on(env):
    store, pm, ctx, fake, ai, tmp = env
    inbox, ctrl = run_node(store, pm, tmp)
    assert "beste vektordatenbanken 2026" in inbox["n"][0]["text"] and len(urls(inbox)) == 10
    p = fake.calls[0][2]
    assert p["cx"] == "cx1" and p["num"] == 10 and p["start"] == 1 and p["gl"] == "de" and p["lr"] == "lang_de"
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert "10 results (1 queries)" in said[0]["text"]


def test_count_from_the_input_pages_and_stops_at_100(env):
    store, pm, ctx, fake, ai, tmp = env
    inbox, _ = run_node(store, pm, tmp, {"count_mode": "input", "query_mode": "input"},
                        text="vector db benchmark – top 25 URLs")
    assert len(urls(inbox)) == 25 and [c[2]["start"] for c in fake.calls] == [1, 11, 21]
    fake.calls.clear()
    fake.total = 500
    inbox, _ = run_node(store, pm, tmp, {"count": 100})
    assert len(urls(inbox)) == 100 and fake.calls[-1][2]["start"] == 91   # Google's limit


def test_few_or_no_hits_and_errors(env):
    store, pm, ctx, fake, ai, tmp = env
    fake.total = 4
    inbox, _ = run_node(store, pm, tmp, {"count": 30})
    assert len(urls(inbox)) == 4 and len(fake.calls) == 1
    fake.total = 0
    inbox, _ = run_node(store, pm, tmp)
    assert "found nothing" in inbox["e"][0]["text"]
    fake.total = 10
    ctx.settings.update({"api_key": "wrong"})
    inbox, _ = run_node(store, pm, tmp)
    assert "API key not valid" in inbox["x"][0]["text"]
    ctx.settings.update({"api_key": "good", "cx": ""})
    inbox, _ = run_node(store, pm, tmp)
    assert "search engine id (cx)" in inbox["x"][0]["text"]
    ctx.settings.update({"cx": "cx1"})
    fake.left = 0
    inbox, _ = run_node(store, pm, tmp)
    assert "Quota exceeded" in inbox["x"][0]["text"]


def test_the_test_button_and_the_costs(env):
    store, pm, ctx, fake, ai, tmp = env
    (button,) = pm.settings_buttons_for("google-search")
    run = lambda values: asyncio.run(button.run(values))  # noqa: E731
    assert run({"api_key": "good"})[0] is False
    ok, text = run({"api_key": "good", "cx": "cx1", "gemini_key": "gem"})
    assert ok and "Custom Search ✔ · 10 results" in text and "$5 per 1,000" in text and "Gemini ✔ · 3 models" in text
    assert ctx.storage.get("models")["models"][0] == "gemini-flash-latest"   # aliases first, no embedding model
    ok, text = run({"api_key": "wrong", "cx": "cx1", "gemini_key": "gem"})
    assert not ok and "Custom Search ✖ API key not valid" in text and "Gemini ✔" in text
    ok, text = run({"gemini_key": "wrong"})
    assert not ok and "Gemini ✖" in text and "Custom Search" not in text
    key = next(s for s in pm.plugins["google-search"].manifest.settings if s.key == "api_key")
    assert "$5 per 1,000" in key.description and "2027" in key.description


def run_research(store, pm, tmp, cfg=None, text="Welche Vektordatenbank ist 2026 die beste?"):
    node = pm.node("google-search/research")
    cfg = {**node.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "Recherche", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": {"answer": "n", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "x", "agent_id": None, "on_success": "end"}]})
    proj = store.save("project", {"name": "R", "workspace": str(tmp / "ws"), "process_id": pid})
    ctrl = Engine(store).controller(store.create_run(proj, "Recherche"))
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h1", "from": "Planer", "agent": "Planer", "text": text}]})
    asyncio.run(ctrl._execute(0, ""))
    return store.run(ctrl.run_id).get("inbox") or {}, ctrl


def test_research_answers_with_real_source_urls(env):
    store, pm, ctx, fake, ai, tmp = env
    ctx.settings.update({"gemini_key": "gem"})
    inbox, ctrl = run_research(store, pm, tmp)
    text = inbox["n"][0]["text"]
    urls = text.split("URLS:\n")[1].split("\n\n")[0].splitlines()
    assert urls == ["https://qdrant.example/page", "https://milvus.example/page", "https://direct.example/x"]
    assert "ANSWER:\nQdrant und Milvus führen 2026 [1][2]." in text and "[1] qdrant.tech – https://qdrant.example/page" in text
    assert "beste vektordatenbank 2026" in text
    method, path, body = fake.gemini_calls[-1]
    assert path == "/v1beta/models/gemini-flash-latest:generateContent" and "Welche Vektordatenbank" in \
        body["contents"][0]["parts"][0]["text"]
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"][0]["text"]
    assert "Qdrant und Milvus" in said and "(https://www.google.com/search?q=beste+vektordatenbank+2026)" in said


def test_research_only_urls_and_the_api_key_as_fallback(env):
    store, pm, ctx, fake, ai, tmp = env
    fake.gemini_key = "good"   # one Google Cloud key for both APIs
    inbox, _ = run_research(store, pm, tmp, {"result": "urls", "max_sources": 2, "resolve": False})
    text = inbox["n"][0]["text"]
    assert "ANSWER:" not in text
    assert text.split("URLS:\n")[1].split("\n\n")[0].splitlines() == [
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/qdrant",
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/milvus"]


def test_research_errors(env):
    store, pm, ctx, fake, ai, tmp = env
    ctx.settings.update({"api_key": "", "gemini_key": ""})
    inbox, _ = run_research(store, pm, tmp)
    assert "No Gemini API key" in inbox["x"][0]["text"]
    ctx.settings.update({"gemini_key": "gem"})
    fake.grounding_quota = 0
    inbox, _ = run_research(store, pm, tmp)
    assert "Resource has been exhausted" in inbox["x"][0]["text"]
