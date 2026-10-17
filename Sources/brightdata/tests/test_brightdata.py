"""Bright Data plugin against a fake Web Unlocker – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/brightdata/tests"""
import asyncio
import json
import os
import sys
import urllib.parse
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
        self.key, self.zone, self.serp_zone = "good", "web_unlocker1", "serp_api1"
        self.serp_empty = False
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
        if json.get("zone") not in (self.zone, self.serp_zone):
            return answer(400, "", {"x-brd-error": f"zone '{json.get('zone')}' not found"})
        target = json["url"]
        if json["zone"] == self.serp_zone:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
            if json.get("data_format") != "parsed" or "brd_json" in q or self.serp_empty:   # the real zone: empty body
                return answer(200, {"status_code": 200, "headers": {}, "body": ""})
            start = int(q.get("start", ["0"])[0])
            found = [{"link": f"https://site{i + 1}.example/{q['q'][0].split()[0]}", "title": f"{q['q'][0]} #{i + 1}",
                      "description": f"about {q['q'][0]}", "rank": i + 1} for i in range(start, min(start + 10, 35))]
            if start == 0:   # Google's own redirect now and then
                found[1]["link"] = "https://www.google.com/url?q=" + urllib.parse.quote(found[1]["link"], safe="")
            page = {"general": {"search_engine": "google", "query": q["q"][0]}, "organic": found}
            if q["q"][0] == "leer":
                page = {"general": {"search_engine": "google", "query": "leer"}}   # a page without hits
            return answer(200, {"status_code": 200, "headers": {}, "body": __import__("json").dumps(page)})
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


def run_node(store, pm, tmp, cfg=None, text=None, kind="scrape", routes=None):
    node = pm.node(f"brightdata/{kind}")
    cfg = {**node.defaults(), **(cfg or {})}
    text = text if text is not None else ("Produkt 915\nhttps://noise.example/x\n\nURLS:\nhttps://shop.example/a\n"
                                          "https://shop.example/b\nhttps://other.example/c\n")
    pid = store.save("process", {"name": "Preise", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": routes or {"pages": "n", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "e", "agent_id": None, "on_success": "end"},
        {"id": "x", "agent_id": None, "on_success": "end"}]})
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
    assert run({"api_key": ""})[0] is False and run({"api_key": "good", "zone": "", "serp_zone": ""})[0] is False
    ok, text = run({"api_key": "good", "zone": "web_unlocker1", "country": "de"})
    assert ok and "web_unlocker1" in text and "$1.50" in text and "SERP" not in text
    ok, text = run({"api_key": "wrong", "zone": "web_unlocker1"})
    assert not ok and "User authentication is required" in text
    assert json.loads(json.dumps(fake.calls[-1][2]))["url"] == "https://example.com/"


# ------------------------------------------------------------------ SERP API
class FakeAi:
    def __init__(self):
        self.prompts = []

    async def ask(self, prompt, system="", model="haiku"):
        self.prompts.append(prompt)
        return json.dumps({"query": "lego 42115 preis", "count": None})


def serp_urls(text):
    return text.split("URLS:\n")[1].split("\n\n")[0].strip().splitlines()


def test_serp_search_hands_on_the_urls_block(env):
    store, pm, ctx, fake, tmp = env
    ctx.ai = ai = FakeAi()
    routes = {"urls": "n", "empty": "e", "error": "x"}
    inbox, ctrl = run_node(store, pm, tmp, {"count": 25}, text="Lego 42115 – günstigster Preis", kind="search",
                           routes=routes)
    text = inbox["n"][0]["text"]
    urls = serp_urls(text)
    assert len(urls) == 25 and urls[0] == "https://site1.example/lego" and ai.prompts
    sent = [c[2] for c in fake.calls]
    assert all(b["zone"] == "serp_api1" and b["format"] == "json" and b["data_format"] == "parsed" for b in sent)
    assert len(sent) == 3 and urls[1] == "https://site2.example/lego"                 # 3 pages; Google's redirect resolved
    q = urllib.parse.parse_qs(urllib.parse.urlparse(sent[1]["url"]).query)
    assert q["q"] == ["lego 42115 preis"] and q["gl"] == ["de"] and q["hl"] == ["de"] and q["start"] == ["10"]
    assert "brd_json" not in q
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert "25 results (3 searches through Bright Data)" in said[0]["text"]
    # the Web Unlocker reads exactly that block
    fake.calls.clear()
    inbox, _ = run_node(store, pm, tmp, {"max_pages": 3}, text=text)
    assert [c[2]["url"] for c in fake.calls] == urls[:3]


def test_serp_template_exclude_and_errors(env):
    store, pm, ctx, fake, tmp = env
    routes = {"urls": "n", "empty": "e", "error": "x"}
    inbox, _ = run_node(store, pm, tmp, {"query_mode": "template", "template": "{input} site:geizhals.de",
                                         "count": 5, "exclude": "site2.example"}, text="Lego 42115", kind="search",
                        routes=routes)
    urls = serp_urls(inbox["n"][0]["text"])
    assert len(urls) == 5 and not any("site2." in u for u in urls)
    assert "Lego 42115 site:geizhals.de" in urllib.parse.unquote_plus(fake.calls[0][2]["url"])
    inbox, _ = run_node(store, pm, tmp, {"query_mode": "input"}, text="leer", kind="search", routes=routes)
    assert "Google found nothing" in inbox["e"][0]["text"]                     # really no hits: “No results”
    fake.serp_empty = True                                                     # a zone that answers with nothing
    inbox, _ = run_node(store, pm, tmp, {"query_mode": "input"}, text="Pahlen", kind="search", routes=routes)
    assert any("didn't answer with parsed Google results" in e["text"] for e in inbox["x"])   # an error, not “nothing found”
    fake.serp_empty = False
    ctx.settings.update({"serp_zone": ""})
    inbox, _ = run_node(store, pm, tmp, text="x", kind="search", routes=routes)
    assert "No SERP API zone" in inbox["x"][0]["text"]
    ctx.settings.update({"serp_zone": "serp_api1", "api_key": "wrong"})
    inbox, _ = run_node(store, pm, tmp, {"query_mode": "input"}, text="x", kind="search", routes=routes)
    assert "User authentication is required" in inbox["x"][0]["text"]


# ------------------------------------------------------------------ Browser API
class FakeBrowser:
    """The Browser API's CDP endpoint: one connection per page."""

    def __init__(self):
        self.user, self.password = "brd-customer-1-zone-browser1", "pw"
        self.headers, self.commands = [], []
        self.fail = {}        # url → errorText of Page.navigate
        self.text = {}        # url → visible text

    async def connect(self, url, headers, timeout):
        import base64
        self.headers.append(headers)
        user, _, password = base64.b64decode(headers["Authorization"].split()[1]).decode().partition(":")
        if user.split("-country-")[0] != self.user or password != self.password:
            class Refused(Exception):
                response = type("R", (), {"status_code": 407, "headers": {"x-brd-error": "Auth failed"}})()
            raise Refused("HTTP 407")
        return FakeSocket(self, url)


class FakeSocket:
    def __init__(self, browser, url):
        self.browser, self.queue, self.page = browser, asyncio.Queue(), ""
        assert url == "wss://brd.superproxy.io:9222"

    async def send(self, raw):
        msg = json.loads(raw)
        method, params, session = msg["method"], msg["params"], msg.get("sessionId")
        self.browser.commands.append((method, params, session))
        result = {}
        if method == "Target.createTarget":
            result = {"targetId": "T1"}
        elif method == "Target.attachToTarget":
            result = {"sessionId": "S1"}
        elif method == "Page.navigate":
            self.page = params["url"]
            if self.page in self.browser.fail:
                result = {"frameId": "F", "errorText": self.browser.fail[self.page]}
            else:
                await self.queue.put(json.dumps({"method": "Page.loadEventFired", "params": {}, "sessionId": "S1"}))
        elif method == "Runtime.evaluate":
            name = self.page.rstrip("/").rsplit("/", 1)[-1]
            text = self.browser.text.get(self.page, f"Produkt {name}\nPreis: 24,99 € (nach JavaScript)")
            result = {"result": {"type": "string", "value": json.dumps(
                {"title": f"Produkt {name}", "url": self.page, "text": text,
                 "html": f"<html><head><title>Produkt {name}</title></head><body>{text}</body></html>"})}}
        elif method == "Captcha.waitForSolve":
            result = {"status": "not_detected"}
        await self.queue.put(json.dumps({"id": msg["id"], "result": result}))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        await self.queue.put(None)


@pytest.fixture
def browser(env, monkeypatch):
    mod = sys.modules[env[1].plugins["brightdata"].manifest.module_name + ".browser"]
    fake = FakeBrowser()
    monkeypatch.setattr(mod, "CONNECT", fake.connect)
    env[2].settings.update({"browser_user": fake.user, "browser_password": fake.password})
    return fake


def test_browser_pages_as_text_without_images(env, browser):
    store, pm, ctx, fake, tmp = env
    inbox, ctrl = run_node(store, pm, tmp, {"wait": 0}, kind="browser")
    text = inbox["n"][0]["text"]
    assert text.startswith("3 of 3 pages loaded (text):") and "Preis: 24,99 € (nach JavaScript)" in text
    assert len(browser.headers) == 3   # one session per page
    import base64
    user = base64.b64decode(browser.headers[0]["Authorization"].split()[1]).decode().split(":")[0]
    assert user == "brd-customer-1-zone-browser1-country-de"
    methods = [m for m, _, _ in browser.commands]
    assert methods.count("Page.navigate") == 3 and methods.count("Captcha.waitForSolve") == 3
    blocked = next(p for m, p, _ in browser.commands if m == "Network.setBlockedURLs")
    assert "*.jpg" in blocked["urls"]
    assert all(s == "S1" for m, _, s in browser.commands if m in ("Page.navigate", "Runtime.evaluate"))
    files = text.split("FILES:\n")[1].split("\n\n")[0].splitlines()
    assert files[0].endswith(".md") and "Source: https://shop.example/a" in Path(files[0]).read_text()
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert "3 of 3 pages** loaded through Bright Data's browser" in said[0]["text"]
    assert not fake.calls   # no REST call


def test_browser_html_images_failures_and_wrong_password(env, browser):
    store, pm, ctx, fake, tmp = env
    browser.fail["https://shop.example/b"] = "net::ERR_NAME_NOT_RESOLVED"
    inbox, _ = run_node(store, pm, tmp, {"format": "html", "images": True, "wait": 0}, kind="browser")
    text = inbox["n"][0]["text"]
    assert "2 of 3 pages loaded (HTML)" in text and "<title>Produkt a</title>" in text
    assert "- https://shop.example/b – net::ERR_NAME_NOT_RESOLVED" in text
    assert not any(m == "Network.setBlockedURLs" for m, _, _ in browser.commands)
    ctx.settings.update({"browser_password": "falsch", "parallel": 1})
    browser.headers.clear()
    inbox, _ = run_node(store, pm, tmp, {"wait": 0}, kind="browser")
    assert "Auth failed" in inbox["x"][0]["text"] and len(browser.headers) == 1   # the rest isn't tried
    ctx.settings.update({"browser_user": ""})
    inbox, _ = run_node(store, pm, tmp, kind="browser")
    assert "No Browser API username" in inbox["x"][0]["text"]


def test_the_test_button_checks_every_part(env, browser):
    store, pm, ctx, fake, tmp = env
    (button,) = pm.settings_buttons_for("brightdata")
    ok, text = asyncio.run(button.run({"api_key": "good", "zone": "web_unlocker1", "serp_zone": "serp_api1",
                                       "browser_user": browser.user, "browser_password": browser.password,
                                       "country": "de", "language": "de"}))
    assert ok and "✔ Web Unlocker" in text and "✔ SERP API · zone serp_api1 · 10 results" in text
    assert "✔ Browser API · test page “Produkt example.com”" in text and "$8 per GB" in text
    ok, text = asyncio.run(button.run({"browser_user": browser.user, "browser_password": "x"}))
    assert not ok and "✖ Browser API: Auth failed" in text and "Web Unlocker" not in text
