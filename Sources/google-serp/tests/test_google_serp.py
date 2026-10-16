"""Google SERP plugin against a fake SerpApi / Serper and a fake AI – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/google-serp/tests"""
import asyncio
import json
import os
import time
import urllib.parse
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.plugins.http import Response  # noqa: E402
from theron.store import Store  # noqa: E402


def hits(q, start, n=10, total=35):
    return [{"position": i + 1, "title": f"{q} #{i + 1}", "link": f"https://site{i + 1}.example/{q.split()[0]}",
             "snippet": f"about {q}"} for i in range(start, min(start + n, total))]


class FakeSerp:
    def __init__(self):
        self.key = "good"
        self.calls = []
        self.total = 35
        self.left = 240

    async def request(self, method, url, *, params=None, headers=None, json=None, **kw):
        u = urllib.parse.urlparse(url)
        self.calls.append((method, u.netloc + u.path, dict(params or {}), json))

        def answer(status, body):
            return Response(url, status, {}, __import__("json").dumps(body).encode())
        if u.netloc == "serpapi.com":
            if (params or {}).get("api_key") != self.key:
                return answer(401, {"error": "Invalid API key. Your API key should be here: "
                                             "https://serpapi.com/manage-api-key"})
            if u.path == "/account.json":
                return answer(200, {"plan_name": "Free Plan", "searches_per_month": 250,
                                    "total_searches_left": self.left})
            if self.left <= 0:
                return answer(429, {"error": "Your account has run out of searches."})
            self.left -= 1
            found = hits(params["q"], int(params.get("start") or 0), total=self.total)
            if not found:
                return answer(200, {"error": "Google hasn't returned any results for this query."})
            return answer(200, {"organic_results": found})
        if u.netloc == "google.serper.dev":
            if (headers or {}).get("X-API-KEY") != self.key:
                return answer(403, {"message": "Unauthorized.", "statusCode": 403})
            return answer(200, {"organic": hits(json["q"], (json["page"] - 1) * 10, total=self.total)})
        return answer(404, {})


class FakeAi:
    def __init__(self):
        self.prompts = []
        self.count = None

    async def ask(self, prompt, system="", model="haiku"):
        self.prompts.append(prompt)
        return json.dumps({"query": "beste vektordatenbanken 2026", "count": self.count})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "google-serp.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["google-serp"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("google-serp")
    ctx.http = fake = FakeSerp()
    ctx.ai = ai = FakeAi()
    ctx.settings.update({"api_key": "good"})
    return store, pm, ctx, fake, ai, tmp_path


def run_node(store, pm, tmp, cfg=None, text="Finde Vergleiche der besten Vektordatenbanken"):
    node = pm.node("google-serp/search")
    cfg = {**node.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "Recherche", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": {"urls": "n", "empty": "e", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "e", "agent_id": None, "on_success": "end"},
        {"id": "x", "agent_id": None, "on_success": "end"}]})
    proj = store.save("project", {"name": "R", "workspace": str(tmp / "ws"), "process_id": pid})
    ctrl = Engine(store).controller(store.create_run(proj, "Recherche"))
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h1", "from": "Planer", "agent": "Planer", "text": text}]})
    out = asyncio.run(ctrl._execute(0, ""))
    return out, store.run(ctrl.run_id).get("inbox") or {}, ctrl


def test_the_ai_writes_the_query_and_the_urls_go_on(env):
    store, pm, ctx, fake, ai, tmp = env
    out, inbox, ctrl = run_node(store, pm, tmp)
    text = inbox["n"][0]["text"]
    assert "beste vektordatenbanken 2026" in text and "URLS:\n" in text
    urls = text.split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()
    assert len(urls) == 10 and urls[0] == "https://site1.example/beste"
    assert len([c for c in fake.calls if c[1] == "serpapi.com/search.json"]) == 1   # 10 = one search
    q = fake.calls[0][2]
    assert q["gl"] == "de" and q["hl"] == "de" and q["engine"] == "google"
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert said and "[beste vektordatenbanken 2026 #1](https://site1.example/beste)" in said[0]["text"]


def test_count_from_the_input_pages_through_google(env):
    store, pm, ctx, fake, ai, tmp = env
    out, inbox, _ = run_node(store, pm, tmp, {"count_mode": "input", "query_mode": "input"},
                             text="vector database benchmark – gib mir die top 25 URLs")
    urls = inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()
    assert len(urls) == 25 and len(set(urls)) == 25
    starts = [c[2]["start"] for c in fake.calls if c[1] == "serpapi.com/search.json"]
    assert starts == [0, 10, 20]
    assert not ai.prompts   # the input as it is: no AI
    assert fake.calls[0][2]["q"].startswith("vector database benchmark")


def test_count_said_to_the_ai_and_fixed_fallback(env):
    store, pm, ctx, fake, ai, tmp = env
    ai.count = 3
    _, inbox, _ = run_node(store, pm, tmp, {"count_mode": "input", "count": 7}, text="Ein paar Quellen bitte")
    assert len(inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()) == 3
    assert "how many results" in ai.prompts[-1]
    ai.count = None
    _, inbox, _ = run_node(store, pm, tmp, {"count_mode": "input", "count": 7}, text="Quellen bitte")
    assert len(inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()) == 7
    _, inbox, _ = run_node(store, pm, tmp, {"count_mode": "fixed", "count": 4}, text="top 20 Quellen")
    assert len(inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()) == 4   # fixed ignores the input


def test_template_country_language_and_excluded_sites(env):
    store, pm, ctx, fake, ai, tmp = env
    _, inbox, _ = run_node(store, pm, tmp, {"query_mode": "template", "template": "{input} site:github.com",
                                            "country": "US", "language": "en", "count": 5,
                                            "exclude": "site1.example, www.site2.example"}, text="rag framework")
    call = fake.calls[0][2]
    assert call["q"] == "rag framework site:github.com" and call["gl"] == "us" and call["hl"] == "en"
    urls = inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()
    assert len(urls) == 5 and not any("site1." in u or "site2." in u for u in urls)


def test_fewer_hits_than_asked_and_none(env):
    store, pm, ctx, fake, ai, tmp = env
    fake.total = 4
    _, inbox, _ = run_node(store, pm, tmp, {"count": 30})
    assert len(inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()) == 4
    assert len([c for c in fake.calls if c[1] == "serpapi.com/search.json"]) == 1   # no pointless pages
    fake.total = 0
    _, inbox, _ = run_node(store, pm, tmp)
    assert "found nothing" in inbox["e"][0]["text"]


def test_errors_go_to_error(env):
    store, pm, ctx, fake, ai, tmp = env
    ctx.settings.update({"api_key": "wrong"})
    _, inbox, _ = run_node(store, pm, tmp)
    assert "Invalid API key" in inbox["x"][0]["text"]
    ctx.settings.update({"api_key": "good"})
    fake.left = 0
    _, inbox, _ = run_node(store, pm, tmp)
    assert "run out of searches" in inbox["x"][0]["text"]
    ctx.settings.update({"api_key": ""})
    _, inbox, _ = run_node(store, pm, tmp)
    assert "No Google SERP API key" in inbox["x"][0]["text"]


def test_serper(env):
    store, pm, ctx, fake, ai, tmp = env
    ctx.settings.update({"provider": "serper"})
    _, inbox, _ = run_node(store, pm, tmp, {"count": 15})
    assert len(inbox["n"][0]["text"].split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()) == 15
    pages = [c[3]["page"] for c in fake.calls if c[1] == "google.serper.dev/search"]
    assert pages == [1, 2]
    ctx.settings.update({"api_key": "wrong"})
    _, inbox, _ = run_node(store, pm, tmp)
    assert "Unauthorized" in inbox["x"][0]["text"]


def test_the_test_button_and_the_costs(env):
    store, pm, ctx, fake, ai, tmp = env
    (button,) = pm.settings_buttons_for("google-serp")
    run = lambda values: asyncio.run(button.run(values))  # noqa: E731
    assert run({"api_key": ""}) == (False, "Enter the API key first.")
    ok, text = run({"api_key": "good", "provider": "serpapi"})
    assert ok and "Free Plan" in text and "240 of 250" in text and "$25" in text
    ok, text = run({"api_key": "wrong", "provider": "serpapi"})
    assert not ok and "Invalid API key" in text
    ok, text = run({"api_key": "good", "provider": "serper"})
    assert ok and "Serper" in text and "$0.30" in text
    info = pm.plugins["google-serp"]
    desc = next(s for s in info.manifest.settings if s.key == "provider").description
    assert "per 1,000 searches" in desc


def test_the_settings_dialog(env):
    from PySide6.QtWidgets import QApplication
    from theron.ui.plugins_ui import PluginSettingsDialog
    app = QApplication.instance() or QApplication([])
    store, pm, ctx, fake, ai, tmp = env
    dlg = PluginSettingsDialog(store, pm.plugins["google-serp"])
    assert [b.text() for b in dlg.button_widgets] == ["Test"]
    dlg.inputs["api_key"][1].setText("good")
    dlg.button_widgets[0].click()
    deadline = time.time() + 5
    while time.time() < deadline and not dlg.result.text().startswith(("✔", "✖")):
        app.processEvents()
        time.sleep(0.02)
    assert dlg.result.text().startswith("✔") and "250" in dlg.result.text()
    dlg.close()


def test_100_results_fit_through_theron(env):
    """Theron passes a hand-over on with at most 12,000 characters – every URL must arrive."""
    store, pm, ctx, fake, ai, tmp = env
    fake.total = 150
    _, inbox, _ = run_node(store, pm, tmp, {"count": 100})
    text = inbox["n"][0]["text"]
    urls = text.split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()
    assert len(urls) == 100 and len(set(urls)) == 100 and len(text) <= 12000
