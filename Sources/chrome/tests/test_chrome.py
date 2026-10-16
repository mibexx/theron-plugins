"""Chrome plugin with the real browser against a local web server – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/chrome/tests
Skipped where no Chrome / Chromium is installed (the Markdown tests always run)."""
import asyncio
import http.server
import os
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.store import Store  # noqa: E402

import sys  # noqa: E402
sys.path.insert(0, str(HERE))
from chrome_scraper.cdp import find_browser  # noqa: E402
from chrome_scraper.markdown import to_markdown  # noqa: E402
from chrome_scraper.scraper import accept_language, urls_in  # noqa: E402

chrome = pytest.mark.skipif(not find_browser(), reason="no Chrome installed")

ARTICLE = """<!doctype html><html lang="de"><head><title>Eulen im Winter</title>
<meta name="description" content="Wie Eulen den Winter überstehen"></head><body>
<header><nav><a href="/">Start</a> <a href="/tiere">Tiere</a> <a href="/kontakt">Kontakt</a></nav></header>
<div id="cookie-consent" style="position:fixed;bottom:0">Wir nutzen Cookies <button>OK</button></div>
<main><article><h1>Eulen im Winter</h1>
<p>Eulen sind <strong>erstaunlich</strong> gut an Kälte angepasst. Ihr <em>Gefieder</em> isoliert hervorragend,
und sie jagen auch bei Schnee – mehr dazu in <a href="/federn">unserem Artikel über Federn</a>.</p>
<h2>Nahrung</h2><ul><li>Mäuse</li><li>Kleine Vögel<ul><li>Spatzen</li></ul></li></ul>
<table><tr><th>Art</th><th>Gewicht</th></tr><tr><td>Uhu</td><td>3 kg</td></tr></table>
<pre><code class="language-python">print("hu")</code></pre>
<p id="late"></p>
<div style="display:none">Versteckter Text</div>
</article></main>
<aside class="related">Ähnliche Artikel: Spechte, Meisen</aside>
<footer>© 2026 Tierportal · Impressum · Datenschutz</footer>
<script>setTimeout(() => document.getElementById('late').textContent = 'Nachgeladen per JavaScript.', 300)</script>
</body></html>"""

CHALLENGE = """<!doctype html><html><head><title>Just a moment...</title></head><body>
<div id="challenge-running">Checking your browser before accessing the site.</div>
<script>setTimeout(() => location.href = '/article?passed=1', %d)</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        Handler.seen.append((self.path, dict(self.headers)))
        p = self.path.split("?")[0]
        if p == "/article":
            return self.send(200, ARTICLE)
        if p == "/slow-check":
            return self.send(503, CHALLENGE % 2500)
        if p == "/hard-check":
            return self.send(403, CHALLENGE % 10_000_000)
        if p == "/moved":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.end_headers()
            return
        if p == "/doc.pdf":
            return self.send(200, b"%PDF-1.4\n%%EOF", "application/pdf")
        if p == "/favicon.ico":
            return self.send(404, "")
        return self.send(404, "<html><head><title>404</title></head><body>Not found</body></html>")


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "chrome.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["chrome"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("chrome")
    ctx.settings.update({"pause": 0, "challenge_wait": 6, "retry_window": False, "ask_user": False})
    ctx.pool.IDLE = 0
    Handler.seen.clear()
    yield store, pm, ctx, tmp_path
    asyncio.run(ctx.pool.shutdown())


def run_node(store, pm, tmp, cfg=None, text=""):
    node = pm.node("chrome/scrape")
    cfg = {**node.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "Lesen", "start": "s", "steps": [
        {"id": "s", "type": "plugin", "plugin_node": node.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": node.ports(cfg), "plugin_routes": {"pages": "n", "error": "x"}},
        {"id": "n", "agent_id": None, "on_success": "end"}, {"id": "x", "agent_id": None, "on_success": "end"}]})
    (tmp / "ws").mkdir(exist_ok=True)
    proj = store.save("project", {"name": "R", "workspace": str(tmp / "ws"), "process_id": pid})
    ctrl = Engine(store).controller(store.create_run(proj, "Lesen"))
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h1", "from": "Suche", "agent": "Suche", "text": text}]})

    async def go():
        try:
            return await ctrl._execute(0, "")
        finally:
            await pm.ctx("chrome").pool.shutdown()
    asyncio.run(go())
    return store.run(ctrl.run_id).get("inbox") or {}, ctrl


# ------------------------------------------------------------------ without a browser
def test_markdown():
    md = to_markdown('<h1>Titel</h1><p>Ein <b>fetter</b> und <a href="https://x.de/a">Link</a>.<br>Zeile 2</p>'
                     '<ol><li>eins</li><li>zwei<ul><li>a</li></ul></li></ol><blockquote>Zitat</blockquote>'
                     '<pre><code class="language-js">let a = 1;\nlet b = 2;</code></pre>'
                     '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2|3</td></tr></table>'
                     '<p><img src="https://x.de/i.png" alt="Bild"></p><script>evil()</script>')
    assert md.startswith("# Titel\n\nEin **fetter** und [Link](https://x.de/a).  \nZeile 2")
    assert "1. eins\n2. zwei\n  - a" in md and "> Zitat" in md
    assert "```js\nlet a = 1;\nlet b = 2;\n```" in md
    assert "| A | B |\n|---|---|\n| 1 | 2\\|3 |" in md
    assert "evil" not in md and "![" not in md
    assert "![Bild](https://x.de/i.png)" in to_markdown('<img src="https://x.de/i.png" alt="Bild">', images=True)


def test_urls_and_languages():
    serp = "Google search “x” – 2 results:\n1. A – https://a.de/1\n\nURLS:\nhttps://a.de/1\nhttps://b.de/2\n"
    assert urls_in(serp) == ["https://a.de/1", "https://b.de/2"]
    assert urls_in("Lies https://a.de/x. und (https://b.de/y), nochmal https://a.de/x/") == \
        ["https://a.de/x", "https://b.de/y"]
    assert accept_language("de-DE, de, en") == "de-DE,de;q=0.9,en;q=0.8"
    assert accept_language("fr") == "fr,en-US;q=0.9,en;q=0.8"


# ------------------------------------------------------------------ the real browser
@chrome
def test_scrapes_the_main_content_as_markdown(env, server):
    store, pm, ctx, tmp = env
    inbox, ctrl = run_node(store, pm, tmp, text=f"URLS:\n{server}/article\n{server}/moved\n")
    text = inbox["n"][0]["text"]
    assert "2 of 2 pages scraped (Markdown)" in text
    assert "# Eulen im Winter" in text and "**erstaunlich**" in text and "*Gefieder*" in text
    assert f"[unserem Artikel über Federn]({server}/federn)" in text   # absolute links
    assert "- Mäuse" in text and "  - Spatzen" in text and "| Uhu | 3 kg |" in text
    assert "Nachgeladen per JavaScript." in text   # rendered, not the raw source
    for gone in ("Kontakt", "Wir nutzen Cookies", "Versteckter Text", "Impressum", "Ähnliche Artikel"):
        assert gone not in text.split("FILES:")[0].split("URL:")[2], gone
    files = text.split("FILES:\n")[1].split()
    assert len(files) == 2 and all(f.endswith(".md") and Path(f).is_file() for f in files)
    assert Path(files[0]).parent == tmp / "ws" / "scraped"
    headers = dict(Handler.seen[0][1])
    ua = headers.get("User-Agent", "")
    assert "Headless" not in ua and "Chrome/" in ua
    assert headers.get("Accept-Language", "").startswith("de-DE,de;q=0.9")
    said = [e for e in store.events(ctrl.run_id) if e["type"] == "plugin_message"]
    assert "2 of 2 pages" in said[0]["text"]


@chrome
def test_raw_html_rendered_and_original(env, server):
    store, pm, ctx, tmp = env
    inbox, _ = run_node(store, pm, tmp, {"format": "html", "folder": ""}, text=f"{server}/article")
    text = inbox["n"][0]["text"]
    assert "<footer>" in text and "Nachgeladen per JavaScript." in text and "FILES:" not in text
    inbox, _ = run_node(store, pm, tmp, {"format": "both", "html_source": "original", "handover": "files"},
                        text=f"{server}/article")
    text = inbox["n"][0]["text"]
    files = text.split("FILES:\n")[1].split()
    assert sorted(Path(f).suffix for f in files) == [".html", ".md"]
    raw = Path(next(f for f in files if f.endswith(".html"))).read_text()
    assert raw == ARTICLE   # exactly what the server sent
    assert "# Eulen im Winter" not in text.split("FILES:")[0]   # only titles and paths


@chrome
def test_a_bot_check_that_clears_itself_and_one_that_stays(env, server):
    store, pm, ctx, tmp = env
    inbox, _ = run_node(store, pm, tmp, text=f"{server}/slow-check {server}/hard-check {server}/missing "
                                             f"{server}/doc.pdf")
    text = inbox["n"][0]["text"]
    assert "1 of 4 pages scraped" in text and "Eulen im Winter" in text
    assert f"{server}/hard-check – blocked by bot protection" in text
    assert f"{server}/missing – HTTP 404" in text
    assert f"{server}/doc.pdf – not a web page (application/pdf)" in text


@chrome
def test_nothing_loaded_goes_to_error_and_limits(env, server):
    store, pm, ctx, tmp = env
    inbox, _ = run_node(store, pm, tmp, text=f"{server}/missing")
    assert "No page could be loaded" in inbox["x"][0]["text"]
    inbox, _ = run_node(store, pm, tmp, text="nichts")
    assert "No URLs in the input" in inbox["x"][0]["text"]
    inbox, _ = run_node(store, pm, tmp, {"max_pages": 1, "max_chars": 100},
                        text=f"{server}/article {server}/moved")
    text = inbox["n"][0]["text"]
    assert "1 of 1 pages" in text and "over the limit of the node" in text and "cut after 100 characters" in text


@chrome
def test_the_test_button(env):
    store, pm, ctx, tmp = env
    test, _profile = pm.settings_buttons_for("chrome")
    ok, text = asyncio.run(test.run({}))
    assert ok and "looks like a normal browser: yes" in text, text
    ok, text = asyncio.run(test.run({"browser": "/nope/chrome"}))
    assert ok or "No Chrome" not in text   # a wrong path falls back to the installed one
