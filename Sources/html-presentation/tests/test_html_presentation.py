"""HTML Presentation against a fake Claude agent – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/html-presentation/tests"""
import asyncio
import json
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


def deck(langs=("de",), options=None, broken=False):
    html = lambda lang, text: f"<h2>{text} ({lang})</h2><ul><li>Punkt</li></ul>" + ("<div>" if broken else "")  # noqa: E731
    return {"title": {lng: f"Kickoff {lng}" for lng in langs},
            "options": options or {},
            "theme": {"light": {"accent": "#e76f51", "bg": "url(javascript:x)"}, "dark": {"accent": "#f4a261"}},
            "css": ".slide.title h1{font-size:120px} </style><script>alert(1)</script>",
            "template_used": "none",
            "slides": [{"layout": "title", "html": {lng: html(lng, "Start") for lng in langs}},
                       {"layout": "content two-cols", "html": {lng: html(lng, "Ziele") for lng in langs}}]}


class FakeAgent:
    """Plays Claude: writes deck.json – as the test wants it, fixed when it is told to."""

    def __init__(self):
        self.calls = []
        self.decks = []          # what it writes, one per call (the last one again if empty)

    async def agent(self, prompt, *, cwd=None, system="", model="", tools=None, max_turns=30, session_id="",
                    on_text=None):
        self.calls.append({"prompt": prompt, "cwd": cwd, "session": session_id, "tools": tools})
        m = re.search(r"WRITE the file (\S+)", prompt) or re.search(r"The check of (\S+) found", prompt)
        target = Path(m.group(1))
        d = self.decks.pop(0) if self.decks else deck()
        if d is not None:
            target.write_text(d if isinstance(d, str) else json.dumps(d), encoding="utf-8")
        return AgentResult(text="Done.", session_id="s1")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "p.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["html-presentation"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("html-presentation")
    ctx.ai = ai = FakeAgent()
    return store, pm, ctx, ai, tmp_path


def make_run(store, pm, tmp, cfg=None, handover="Kickoff des Webshop-Projekts: Ziele, Plan, Team."):
    n = pm.node("html-presentation/presentation")
    cfg = {**n.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "P", "start": "p", "steps": [
        {"id": "p", "type": "plugin", "plugin_node": n.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": n.ports(cfg), "plugin_routes": {"presentation": "end", "error": "end"}}]})
    proj = store.save("project", {"name": "W", "workspace": str(tmp / "ws"), "process_id": pid})
    (tmp / "ws").mkdir(exist_ok=True)
    ctrl = Engine(store).controller(store.create_run(proj, "Präsentation"))
    if handover:
        store.update_run(ctrl.run_id, inbox={"p": [{"id": "h1", "from": "Writer", "agent": "Writer",
                                                    "text": handover}]})
    return ctrl


def run(ctrl, task="Mach eine Präsentation"):
    return asyncio.run(ctrl._execute(0, task))


def block(store, run_id):
    (ev,) = [e for e in store.events(run_id) if e["type"] == "plugin_message"]
    return ev["data"]


def page(data):
    return Path(data["path"]).read_text(encoding="utf-8")


def config_of(text):
    return json.loads(re.search(r"var C = (\{.*?\});\n", text).group(1))


# ------------------------------------------------------------------ the node
def test_the_node(env):
    store, pm, ctx, ai, tmp = env
    n = pm.node("html-presentation/presentation")
    assert [(p["id"], p.get("color")) for p in n.ports(n.defaults())["outputs"]] == [("presentation", "success"),
                                                                                     ("error", "error")]
    assert [f["key"] for f in n.fields] == ["content", "style", "template_dir", "template", "multilingual",
                                            "languages", "theme", "cursor", "arrows", "folder", "filename"]
    d = n.defaults()
    assert (d["multilingual"], d["theme"], d["cursor"], d["arrows"]) == ("input", "input", "input", "input")


def test_a_presentation_with_the_defaults(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("de",), {"languages": ["de"]})]
    out = run(make_run(store, pm, tmp))
    data = block(store, 1)
    text = page(data)
    assert data["slides"] == 2 and data["languages"] == ["de"] and data["title"] == "Kickoff de"
    assert (data["theme"], data["cursor"], data["arrows"]) == ("light", "bottom", True)
    assert Path(data["path"]).parent == tmp / "ws" / "presentations" and Path(data["path"]).name == "kickoff-de.html"
    c = config_of(text)
    assert c == {"languages": ["de"], "names": {"de": "Deutsch"}, "titles": {"de": "Kickoff de"}, "modes": ["light"],
                 "arrows": True}
    assert 'class="stage cursor-bottom"' in text and text.count('<section class="slide') == 2
    assert '<section class="slide content two-cols" data-n="2" lang="de"' in text
    assert "alert(1)" not in text.split("<script>")[0] and "javascript:" not in text   # the AI's CSS is cleaned
    assert "width: 1920px; height: 1080px" in text and "Math.min(window.innerWidth / 1920" in text
    prompt = ai.calls[0]["prompt"]
    assert "Kickoff des Webshop-Projekts" in prompt and "Mach eine Präsentation" in prompt
    assert "DECIDE FROM THE CONTENT" in prompt and "languages, multilingual, theme, cursor, arrows" in prompt
    assert ai.calls[0]["cwd"].startswith(str(ctx.data_dir / "work"))
    assert "Output “Error”" not in out


def test_fixed_options_in_the_node(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("de", "en"))]
    run(make_run(store, pm, tmp, {"multilingual": "yes", "languages": "de, en", "theme": "both", "cursor": "top",
                                  "arrows": "no"}))
    data = block(store, 1)
    c = config_of(page(data))
    assert c["languages"] == ["de", "en"] and c["modes"] == ["light", "dark"] and c["arrows"] is False
    assert 'class="stage cursor-top"' in page(data)
    assert page(data).count('<section class="slide') == 4 and page(data).count('" lang="en"') == 2
    prompt = ai.calls[0]["prompt"]
    assert "FIXED OPTIONS: languages: de, en" in prompt and "theme: both" in prompt and "DECIDE" not in prompt


def test_options_from_lines_of_the_input(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("en", "de"))]
    run(make_run(store, pm, tmp, handover="Inhalt …\nSPRACHEN: Englisch und Deutsch\nTHEME: beides\nCURSOR: oben\n"
                                          "PFEILTASTEN: nein"))
    data = block(store, 1)
    assert (data["languages"], data["theme"], data["cursor"], data["arrows"]) == (["en", "de"], "both", "top", False)
    assert "DECIDE" not in ai.calls[0]["prompt"]


def test_the_ai_decides_what_is_open(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("de", "fr"), {"multilingual": True, "languages": ["de", "fr"], "theme": "dark",
                                    "cursor": "top", "arrows": False})]
    run(make_run(store, pm, tmp, handover="Bitte auf Deutsch und Französisch, dunkel."))
    data = block(store, 1)
    assert (data["languages"], data["theme"], data["cursor"], data["arrows"]) == (["de", "fr"], "dark", "top", False)


def test_not_multilingual_keeps_one_language(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("de",), {"multilingual": True, "languages": ["de", "en"]})]
    run(make_run(store, pm, tmp, {"multilingual": "no", "languages": "de, en"}))
    assert block(store, 1)["languages"] == ["de"]


def test_problems_go_back_to_the_agent(env):
    store, pm, ctx, ai, tmp = env
    missing = deck(("de", "en"))
    del missing["slides"][1]["html"]["en"]
    ai.decks = [deck(("de",), broken=True), missing, deck(("de", "en"))]
    run(make_run(store, pm, tmp, {"languages": "de, en"}))
    assert len(ai.calls) == 3 and ai.calls[1]["session"] == "s1"
    assert "slide 1 (de): unclosed <div>" in ai.calls[1]["prompt"] and "missing in language en" in ai.calls[1]["prompt"]
    assert "missing in language en" in ai.calls[2]["prompt"]
    assert block(store, 1)["slides"] == 2


def test_unusable_goes_to_error(env):
    store, pm, ctx, ai, tmp = env
    script = deck()
    script["slides"][0]["html"]["de"] = "<p onclick='x()'>hi</p>"
    ai.decks = ["not json", None, script]
    out = run(make_run(store, pm, tmp))
    assert "Output “Error”" in out and len(ai.calls) == 3
    assert not (tmp / "ws" / "presentations").exists() or not list((tmp / "ws" / "presentations").iterdir())
    out = asyncio.run(make_run(store, pm, tmp, handover="")._execute(0, ""))
    assert "Output “Error”" in out


def test_one_presentation_per_run(env):
    store, pm, ctx, ai, tmp = env
    for _ in range(2):
        run(make_run(store, pm, tmp, {"filename": "Kickoff.html"}))
    assert sorted(p.name for p in (tmp / "ws" / "presentations").iterdir()) == ["Kickoff-2.html", "Kickoff.html"]


def test_templates_like_the_html_builder(env):
    store, pm, ctx, ai, tmp = env
    tpl = ctx.data_dir / "templates"
    tpl.mkdir(parents=True)
    (tpl / "firma.pdf").write_bytes(b"%PDF")
    run(make_run(store, pm, tmp))
    assert f"- {tpl / 'firma.pdf'}" in ai.calls[-1]["prompt"]
    run(make_run(store, pm, tmp, {"template": "firma.pdf"}))
    assert f"TEMPLATE: {tpl / 'firma.pdf'}\nRead it first" in ai.calls[-1]["prompt"]
    n = pm.node("html-presentation/presentation")
    assert [o["value"] for o in n.fields[3]["options"]({})] == ["auto", "", "firma.pdf"]


def test_the_chat_card(env):
    store, pm, ctx, ai, tmp = env
    ai.decks = [deck(("de", "en"))]
    run(make_run(store, pm, tmp, {"languages": "de, en", "theme": "both"}))
    data = block(store, 1)
    card = pm.chat_renderers[("html-presentation", "presentation")](data)
    assert "2 slides" in card and "de · en" in card and "light / dark" in card and "Present" in card
    opened = []
    ctx.ui.open_url = opened.append
    pm.chat_links[("html-presentation", "open")]({"path": data["path"]})
    assert opened == [Path(data["path"]).as_uri()]


def test_package_and_translations():
    import zipfile
    from tempfile import mkdtemp
    names = zipfile.ZipFile(plugins.pack(HERE, Path(mkdtemp()) / "p.theronplugin")).namelist()
    assert "html_presentation/shell.py" in names and not any(n.startswith("tests/") for n in names)
    de = json.loads((HERE / "i18n" / "de.json").read_text(encoding="utf-8"))
    assert de["Build presentation"] == "Präsentation erzeugen" and de["Slide cursor"] == "Folien-Cursor"
