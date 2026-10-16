"""Bright Data plugin against a fake Web Unlocker – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/brightdata/tests"""
import asyncio
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.plugins.http import Response  # noqa: E402
from theron.store import Store  # noqa: E402


class FakeUnlocker:
    def __init__(self):
        self.key, self.zone = "good", "web_unlocker1"
        self.calls = []
        self.pages = {}       # url → (status, body)
        self.refuse = {}      # url → (status, error) from Bright Data itself

    async def request(self, method, url, *, json=None, headers=None, timeout=None, **kw):
        self.calls.append((method, url, dict(json or {}), dict(headers or {}), timeout))

        def answer(status, body, head=None):
            raw = body.encode() if isinstance(body, str) else __import__("json").dumps(body).encode()
            return Response(url, status, head or {}, raw)
        if url != "https://api.brightdata.com/request":
            return answer(404, {})
        if (headers or {}).get("Authorization") != f"Bearer {self.key}":
            return answer(401, {"error": "User authentication is required"})
        if json.get("zone") != self.zone:
            return answer(400, "", {"x-brd-error": f"zone '{json.get('zone')}' not found"})
        target = json["url"]
        if target in self.refuse:
            status, why = self.refuse[target]
            return answer(status, "", {"x-brd-error": why})
        status, page = self.pages.get(target, (200, None))
        if page is None:
            name = target.rstrip("/").rsplit("/", 1)[-1]
            page = (f"# Produkt {name}\n\nPreis: 19,99 €\n\n" + "Text " * 50) if json.get("data_format") == "markdown" \
                else f"<html><head><title>Produkt {name}</title></head><body><p>Preis: 19,99 €</p></body></html>"
        return answer(200, {"status_code": status, "headers": {"content-type": "text/html"}, "body": page})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "brightdata.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["brightdata"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("brightdata")
    ctx.http = fake = FakeUnlocker()
    ctx.settings.update({"api_key": "good", "zone": "web_unlocker1"})
    return store, pm, ctx, fake, tmp_path


def run_node(store, pm, tmp, cfg=None, text=None):
    node = pm.node("brightdata/scrape")
    cfg = {**node.defaults(), **(cfg or {})}
    text = text if text is not None else ("Produkt 915\nhttps://noise.example/x\n\nURLS:\nhttps://shop.example/a\n"
                                          "https://shop.example/b\nhttps://other.example/c\n")
    pid = store.save("process", {"name": "Preise", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": {"pages": "n", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "x", "agent_id": None, "on_success": "end"}]})
    proj = store.save("project", {"name": "P", "workspace": str(tmp / "ws"), "process_id": pid})
    ctrl = Engine(store).controller(store.create_run(proj, "Preise"))
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h1", "from": "URL-Bauer", "agent": "URL-Bauer", "text": text}]})
    asyncio.run(ctrl._execute(0, ""))
    return store.run(ctrl.run_id).get("inbox") or {}, ctrl


def test_markdown_pages_from_the_urls_block_with_files(env):
    store, pm, ctx, fake, tmp = env
    inbox, ctrl = run_node(store, pm, tmp)
    text = inbox["n"][0]["text"]
    assert [c[2]["url"] for c in fake.calls] == ["https://shop.example/a", "https://shop.example/b",
                                                 "https://other.example/c"]   # the URLS: block, not the noise
    body = fake.calls[0][2]
    assert body == {"zone": "web_unlocker1", "url": "https://shop.example/a", "format": "json",
                    "data_format": "markdown", "country": "de"}
    assert fake.calls[0][4] == 120
    assert text.startswith("3 of 3 pages loaded (Markdown):\n\nFILES:\n")
    files = text.split("FILES:\n")[1].split("\n\n")[0].splitlines()
    assert len(files) == 3 and all(Path(f).exists() and "/ws/scraped/" in f for f in files)
    assert "Preis: 19,99 €" in Path(files[0]).read_text() and "Source: https://shop.example/a" in Path(files[0]).read_text()
    assert "## 1. Produkt a" in text
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert "3 of 3 pages" in said[0]["text"] and "[Produkt a](https://shop.example/a)" in said[0]["text"]


def test_html_country_render_and_the_node_list(env):
    store, pm, ctx, fake, tmp = env
    ctx.settings.update({"render": True})
    inbox, _ = run_node(store, pm, tmp, {"format": "html", "country": "AT",
                                         "urls": "https://x.example/eins\nhttps://x.example/eins/"})
    body = fake.calls[0][2]
    assert "data_format" not in body and body["country"] == "at" and body["render"] == "true"
    assert len(fake.calls) == 1   # same URL twice = once
    text = inbox["n"][0]["text"]
    assert "(HTML)" in text and "## 1. Produkt eins" in text and "<p>Preis: 19,99 €</p>" in text
    assert text.split("FILES:\n")[1].split("\n")[0].endswith(".html")


def test_single_failures_are_listed_all_failing_goes_to_error(env):
    store, pm, ctx, fake, tmp = env
    fake.pages["https://shop.example/b"] = (404, "# Not found")
    fake.refuse["https://other.example/c"] = (502, "target site unreachable")
    inbox, _ = run_node(store, pm, tmp)
    text = inbox["n"][0]["text"]
    assert text.startswith("1 of 3 pages loaded")
    assert "- https://shop.example/b – HTTP 404" in text and "target site unreachable" in text
    fake.pages["https://shop.example/a"] = (200, "   ")
    inbox, _ = run_node(store, pm, tmp)
    assert "No page could be loaded" in inbox["x"][0]["text"] and "empty page" in inbox["x"][0]["text"]


def test_wrong_key_or_zone_stops_early(env):
    store, pm, ctx, fake, tmp = env
    ctx.settings.update({"api_key": "wrong", "parallel": 1})
    inbox, _ = run_node(store, pm, tmp)
    assert "User authentication is required" in inbox["x"][0]["text"] and len(fake.calls) == 1
    fake.calls.clear()
    ctx.settings.update({"api_key": "good", "zone": "falsch"})
    inbox, _ = run_node(store, pm, tmp)
    assert "zone 'falsch' not found" in inbox["x"][0]["text"] and len(fake.calls) == 1
    ctx.settings.update({"api_key": ""})
    inbox, _ = run_node(store, pm, tmp)
    assert "No Bright Data API key" in inbox["x"][0]["text"]
    inbox, _ = run_node(store, pm, tmp, text="nichts zu laden")
    assert "No URLs in the input" in inbox["x"][0]["text"]


def test_limit_and_the_handover_budget(env):
    store, pm, ctx, fake, tmp = env
    urls = [f"https://shop{i}.example/p{i}" for i in range(12)]
    for u in urls:
        fake.pages[u] = (200, f"# Seite {u}\n\n" + "Langer Text mit Preisen. " * 2000)
    inbox, _ = run_node(store, pm, tmp, {"max_pages": 8}, text="URLS:\n" + "\n".join(urls))
    text = inbox["n"][0]["text"]
    assert len(fake.calls) == 8 and len(text) <= 11_800
    assert text.count("## ") == 8 and "the whole page is in the file" in text
    assert text.count("over the limit of the node") == 4
    files = text.split("FILES:\n")[1].split("\n\n")[0].splitlines()
    assert len(Path(files[0]).read_text()) > 40_000   # the file has everything
    inbox, _ = run_node(store, pm, tmp, {"max_pages": 2, "handover": "files"}, text="URLS:\n" + "\n".join(urls))
    assert "Langer Text mit Preisen." in inbox["n"][0]["text"] and len(inbox["n"][0]["text"]) < 3_000


def test_the_test_button_and_the_costs(env):
    store, pm, ctx, fake, tmp = env
    (button,) = pm.settings_buttons_for("brightdata")
    run = lambda values: asyncio.run(button.run(values))  # noqa: E731
    assert run({"api_key": ""}) == (False, "Enter the API key first.")
    assert run({"api_key": "good", "zone": ""})[0] is False
    ok, text = run({"api_key": "good", "zone": "web_unlocker1", "country": "de"})
    assert ok and "web_unlocker1" in text and "$1.50" in text
    ok, text = run({"api_key": "wrong", "zone": "web_unlocker1"})
    assert not ok and "User authentication is required" in text
    assert json.loads(json.dumps(fake.calls[-1][2]))["url"] == "https://example.com/"
