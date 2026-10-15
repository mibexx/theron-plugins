"""HTML Builder against a fake Claude agent – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/html-builder/tests"""
import asyncio
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.plugins.context import AgentResult  # noqa: E402
from theron.store import Store  # noqa: E402

GOOD = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>body{{font-family:sans-serif}}</style></head>
<body><header><h1>{title}</h1></header><main><section><p>Echter Inhalt.<p>Noch ein Absatz.</section>
<ul><li>Eins<li>Zwei</ul><img src="https://x/y.png" alt="Bild"></main><footer>© 2026</footer></body></html>"""
BROKEN = """<html><body><div><h1>Kaputt</h1><span>offen</div></body></html>"""


class FakeAgent:
    """Plays Claude: writes the file the prompt asks for – good, broken, or broken until it is told to fix it."""

    def __init__(self):
        self.calls = []
        self.mode = "good"           # good | broken | fixable | nothing
        self.title = "Angebot Webshop"

    async def agent(self, prompt, *, cwd=None, system="", model="", tools=None, max_turns=30, session_id="",
                    on_text=None):
        self.calls.append({"prompt": prompt, "cwd": cwd, "model": model, "tools": tools, "session": session_id})
        if on_text:
            on_text("Ich lese die Vorlage …")
        fixing = "found these problems" in prompt
        m = re.search(r"Write it to exactly this file: (.+)", prompt)
        if fixing:
            path = Path(re.search(r"The check of (.+?) found", prompt).group(1))
        elif m:
            path = Path(m.group(1).strip())
        else:
            path = Path(cwd) / "angebot-webshop.html"
            n = 2
            while path.exists():
                path = Path(cwd) / f"angebot-webshop-{n}.html"
                n += 1
        if self.mode == "nothing":
            return AgentResult(text="Ich konnte nichts schreiben.", session_id="s1")
        broken = self.mode == "broken" or (self.mode == "fixable" and not fixing)
        path.write_text(BROKEN if broken else GOOD.format(title=self.title), encoding="utf-8")
        used = "TEMPLATE_USED: angebot.html\n" if "TEMPLATES you may follow" in prompt else ""
        return AgentResult(text=f"Fertig.\n{used}HTML_FILE: {path}", session_id="s1")

    async def ask(self, prompt, system="", model="haiku"):
        return ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "html.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["html-builder"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("html-builder")
    ctx.ai = ai = FakeAgent()
    return store, pm, ctx, ai, tmp_path


def make_run(store, pm, tmp, cfg=None, handover="Ein Angebot für einen Webshop: 3 Pakete, Preise, Kontakt."):
    n = pm.node("html-builder/html")
    cfg = {**n.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "HTML", "start": "h", "steps": [
        {"id": "h", "type": "plugin", "plugin_node": n.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": n.ports(cfg), "plugin_routes": {"document": "end", "error": "end"}}]})
    proj = store.save("project", {"name": "Web", "workspace": str(tmp / "ws"), "process_id": pid})
    (tmp / "ws").mkdir(exist_ok=True)
    ctrl = Engine(store).controller(store.create_run(proj, "Angebot als HTML"))
    if handover:
        store.update_run(ctrl.run_id, inbox={"h": [{"id": "h1", "from": "Writer", "agent": "Writer",
                                                    "text": handover}]})
    return ctrl


def run(ctrl, task="Erstelle das Angebot als HTML"):
    return asyncio.run(ctrl._execute(0, task))


def blocks(store, run_id):
    return [e for e in store.events(run_id) if e["type"] == "plugin_message"]


# ------------------------------------------------------------------ the node
def test_the_node_has_two_coloured_outputs_and_its_fields(env):
    store, pm, ctx, ai, tmp = env
    n = pm.node("html-builder/html")
    ports = n.ports(n.defaults())["outputs"]
    assert [(p["id"], p.get("color")) for p in ports] == [("document", "success"), ("error", "error")]
    assert [f["key"] for f in n.fields] == ["content", "audience", "style", "template_dir", "template", "folder",
                                            "filename", "self_contained"]
    assert n.defaults()["template"] == "auto" and n.defaults()["self_contained"] is True


def test_one_clean_document_from_the_hand_over(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"audience": "Kleine Händler", "style": "Dunkelblau, ruhig, Inter"})
    out = run(ctrl)
    files = list((tmp / "ws" / "html").glob("*.html"))
    assert [f.name for f in files] == ["angebot-webshop.html"]
    prompt = ai.calls[0]["prompt"]
    assert "3 Pakete" in prompt and "Erstelle das Angebot" in prompt          # hand-over AND assignment
    assert "AUDIENCE: Kleine Händler" in prompt and "STYLE / CI: Dunkelblau" in prompt
    assert "Self-contained" in prompt and ai.calls[0]["cwd"] == str(tmp / "ws" / "html")
    assert ai.calls[0]["model"] == "sonnet" and "Write" in ai.calls[0]["tools"] and "Bash" not in ai.calls[0]["tools"]
    assert len(ai.calls) == 1                                                  # clean: no fix round
    assert "Output “Document”" in out or "document" in out.lower()
    (ev,) = blocks(store, ctrl.run_id)
    assert ev["kind"] == "html" and ev["data"]["title"] == "Angebot Webshop" and ev["data"]["warnings"] == []
    assert ev["data"]["path"] == str(files[0])


def test_the_hand_over_carries_the_path(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp)
    run(ctrl)
    path = tmp / "ws" / "html" / "angebot-webshop.html"
    texts = [e.get("text") or "" for e in store.events(ctrl.run_id)]
    assert any(f"HTML_FILE: {path}" in t for t in texts), texts[-5:]


def test_without_any_description_it_goes_to_error(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp, handover="")
    out = asyncio.run(ctrl._execute(0, ""))
    assert "Output “Error”" in out and not ai.calls


def test_the_content_field_is_enough(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"content": "Eine Landingpage für ein Yoga-Studio"}, handover="")
    run(ctrl, "")
    assert "CONTENT (from the node):\nEine Landingpage für ein Yoga-Studio" in ai.calls[0]["prompt"]


def test_broken_html_is_fixed_by_the_same_agent(env):
    store, pm, ctx, ai, tmp = env
    ai.mode = "fixable"
    ctrl = make_run(store, pm, tmp)
    out = run(ctrl)
    assert len(ai.calls) == 2 and ai.calls[1]["session"] == "s1"
    assert "unclosed tags: <span>" in ai.calls[1]["prompt"] and "no <!DOCTYPE html>" in ai.calls[1]["prompt"]
    assert "Output “Error”" not in out
    assert blocks(store, ctrl.run_id)[0]["data"]["title"] == "Angebot Webshop"


def test_html_that_stays_broken_goes_to_error(env):
    store, pm, ctx, ai, tmp = env
    ai.mode = "broken"
    out = run(make_run(store, pm, tmp))
    assert "Output “Error”" in out and len(ai.calls) == 3   # written + 2 fix rounds


def test_no_file_goes_to_error(env):
    store, pm, ctx, ai, tmp = env
    ai.mode = "nothing"
    out = run(make_run(store, pm, tmp))
    assert "Output “Error”" in out


def test_one_document_per_run_and_nothing_is_overwritten(env):
    """Behind a loop the node runs once per item – each round its own file."""
    store, pm, ctx, ai, tmp = env
    for _ in range(2):
        run(make_run(store, pm, tmp))
    assert sorted(f.name for f in (tmp / "ws" / "html").glob("*.html")) == ["angebot-webshop-2.html",
                                                                          "angebot-webshop.html"]
    for _ in range(2):
        run(make_run(store, pm, tmp, {"filename": "Offer Final.html", "folder": "out"}))
    assert sorted(f.name for f in (tmp / "ws" / "out").glob("*.html")) == ["Offer Final-2.html", "Offer Final.html"]


# ------------------------------------------------------------------ templates
def test_templates_of_the_folder(env):
    store, pm, ctx, ai, tmp = env
    n = pm.node("html-builder/html")
    tpl = ctx.data_dir / "templates"
    (tpl / "newsletter").mkdir(parents=True)
    (tpl / "angebot.html").write_text(GOOD.format(title="Vorlage"))
    (tpl / "newsletter" / "mai.pdf").write_bytes(b"%PDF")
    (tpl / ".DS_Store").write_bytes(b"x")
    (tpl / "notes.xyz").write_text("x")
    opts = [o["value"] for o in n.fields[4]["options"](n.defaults())]
    assert opts == ["auto", "", "angebot.html", "newsletter/mai.pdf"]
    # a name is a sub-folder of the plugin's template folder, an absolute path is itself
    assert [o["value"] for o in n.fields[4]["options"]({"template_dir": "newsletter"})][2:] == ["mai.pdf"]
    other = tmp / "elsewhere"
    other.mkdir()
    (other / "x.md").write_text("# x")
    assert [o["value"] for o in n.fields[4]["options"]({"template_dir": str(other)})][2:] == ["x.md"]
    ctx.settings.update({"template_dir": str(other)})
    assert [o["value"] for o in n.fields[4]["options"]({})][2:] == ["x.md"]   # the setting when the node has none


def test_automatic_template_lets_the_ai_choose(env):
    store, pm, ctx, ai, tmp = env
    tpl = ctx.data_dir / "templates"
    tpl.mkdir(parents=True)
    (tpl / "angebot.html").write_text(GOOD.format(title="Vorlage"))
    ctrl = make_run(store, pm, tmp)
    run(ctrl)
    assert f"- {tpl / 'angebot.html'}" in ai.calls[0]["prompt"] and "TEMPLATE_USED" in ai.calls[0]["prompt"]
    assert blocks(store, ctrl.run_id)[0]["data"]["template"] == "angebot.html"


def test_fixed_template_and_a_template_from_the_hand_over(env):
    store, pm, ctx, ai, tmp = env
    tpl = ctx.data_dir / "templates"
    tpl.mkdir(parents=True)
    (tpl / "a.html").write_text("x")
    (tpl / "b.md").write_text("x")
    run(make_run(store, pm, tmp, {"template": "a.html"}))
    assert f"TEMPLATE: {tpl / 'a.html'}\nRead it first" in ai.calls[-1]["prompt"]
    run(make_run(store, pm, tmp, {"template": "a.html"}, handover="Inhalt …\nTEMPLATE: b.md"))
    assert f"TEMPLATE: {tpl / 'b.md'}\nRead it first" in ai.calls[-1]["prompt"]
    run(make_run(store, pm, tmp, {"template": ""}))
    assert "TEMPLATE" not in ai.calls[-1]["prompt"]
    out = run(make_run(store, pm, tmp, {"template": "gone.html"}))
    assert "Output “Error”" in out


def test_buttons_open_and_add_templates(env, tmp_path):
    store, pm, ctx, ai, tmp = env
    n = pm.node("html-builder/html")
    opened, src = [], tmp_path / "src"
    src.mkdir()
    (src / "angebot.html").write_text("x")
    ctx.ui.open_url = opened.append

    async def run_on_ui(fn, *args):   # what Theron's ctx.ui.run does – the dialog answered by the "user"
        return [str(src / "angebot.html")]
    ctx.ui.run = run_on_ui
    open_btn, add_btn = n.fields[3]["buttons"]
    show_btn = n.fields[4]["buttons"][0]
    cfg = {"template_dir": "kunde-a"}
    asyncio.run(open_btn["run"](cfg))
    assert opened == [(ctx.data_dir / "templates" / "kunde-a").as_uri()]
    ok, text = asyncio.run(add_btn["run"](cfg))
    ok2, _ = asyncio.run(add_btn["run"](cfg))
    assert ok and ok2 and "angebot.html" in text
    assert sorted(p.name for p in (ctx.data_dir / "templates" / "kunde-a").iterdir()) == ["angebot-2.html",
                                                                                          "angebot.html"]
    assert asyncio.run(show_btn["run"]({**cfg, "template": "auto"}))[0] is False
    asyncio.run(show_btn["run"]({**cfg, "template": "angebot.html"}))
    assert opened[-1].endswith("/kunde-a/angebot.html")


# ------------------------------------------------------------------ the check
def test_the_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("hb_check", HERE / "html_builder" / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.check(GOOD.format(title="T")) == ([], [])
    errors, warnings = mod.check(BROKEN)
    assert errors == ["unclosed tags: <span>"] and "no <!DOCTYPE html> at the top" in warnings
    assert mod.check("")[0] == ["the file is empty"]
    assert "Markdown code fences" in mod.check("```html\n" + GOOD.format(title="T") + "\n```")[0][0]
    errors, _ = mod.check("<!DOCTYPE html><html><body><p>x</p></em></body></html>")
    assert errors == ["end tags without a start tag: </em>"]
    _, warnings = mod.check("<!DOCTYPE html><html><head><title>t</title></head><body><h1>a</h1><h1>b</h1>"
                            "<img src=a.png></body></html>")
    assert "2 <h1> headings (one is clean)" in warnings and "1 image(s) without alt text" in warnings
    assert 'no <meta charset="utf-8">' in warnings and "no lang attribute on <html>" in warnings
    assert mod.title_of(GOOD.format(title="Hallo  Welt")) == "Hallo Welt"


# ------------------------------------------------------------------ the chat
def test_the_chat_card(env):
    store, pm, ctx, ai, tmp = env
    run(make_run(store, pm, tmp))
    path = tmp / "ws" / "html" / "angebot-webshop.html"
    render = pm.chat_renderers[("html-builder", "html")]
    card = render({"path": str(path), "title": "Angebot", "size": 2048, "template": "a.html",
                   "warnings": ["no <h1> heading"]})
    assert "Angebot" in card and "2 KB" in card and "template: a.html" in card and "theron-plugin://html-builder/open" in card
    assert "⚠ no &lt;h1&gt; heading" in card
    opened = []
    ctx.ui.open_url = opened.append
    pm.chat_links[("html-builder", "open")]({"path": str(path)})
    pm.chat_links[("html-builder", "folder")]({"path": str(path)})
    assert opened == [path.as_uri(), path.parent.as_uri()]
    path.unlink()
    assert "The file is gone." in render({"path": str(path), "title": "Angebot", "size": 1})


def test_package_and_translations():
    import json
    import zipfile
    from tempfile import mkdtemp
    pkg = plugins.pack(HERE, Path(mkdtemp()) / "h.theronplugin")
    names = zipfile.ZipFile(pkg).namelist()
    assert "plugin.toml" in names and "html_builder/node.py" in names and not any(n.startswith("tests/") for n in names)
    de = json.loads((HERE / "i18n" / "de.json").read_text(encoding="utf-8"))
    assert de["Build HTML"] == "HTML erzeugen" and de["Template folder"] == "Vorlagen-Verzeichnis"
