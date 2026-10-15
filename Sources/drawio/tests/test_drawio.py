"""draw.io Diagrams against a fake AI – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/drawio/tests
DRAWIO_DOCKER_TEST=1 also exports with the real Docker image (it must be loaded)."""
import asyncio
import base64
import os
import sys
import time
import urllib.parse
import zlib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.store import Store  # noqa: E402

FLOW = """<mxfile host="Theron"><diagram id="d" name="Login flow"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="s" value="Start" style="ellipse;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1"><mxGeometry x="40" y="20" width="120" height="50" as="geometry"/></mxCell>
<mxCell id="d" value="Valid?" style="rhombus;" vertex="1" parent="1"><mxGeometry x="40" y="120" width="120" height="80" as="geometry"/></mxCell>
<mxCell id="ok" value="Dashboard" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="40" y="260" width="120" height="50" as="geometry"/></mxCell>
<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="s" target="d"><mxGeometry relative="1" as="geometry"/></mxCell>
<mxCell id="e2" value="yes" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="d" target="ok"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""
BROKEN = FLOW.replace('target="ok"', 'target="gone"')
OVERLAP = FLOW.replace('y="260"', 'y="130"')

MIXED = """<mxfile><diagram name="Everything"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="lane" value="Customer" style="swimlane;horizontal=0;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="600" height="150" as="geometry"/></mxCell>
<mxCell id="c1" value="Order" style="rounded=1;" vertex="1" parent="lane"><mxGeometry x="60" y="40" width="100" height="50" as="geometry"/></mxCell>
<mxCell id="cls" value="User" style="swimlane;fontStyle=1;startSize=26;" vertex="1" parent="1"><mxGeometry x="0" y="200" width="160" height="86" as="geometry"/></mxCell>
<mxCell id="f1" value="+ id: int" style="text;align=left;" vertex="1" parent="cls"><mxGeometry y="26" width="160" height="30" as="geometry"/></mxCell>
<mxCell id="ll" value="API" style="shape=umlLifeline;size=40;" vertex="1" parent="1"><mxGeometry x="250" y="200" width="100" height="200" as="geometry"/></mxCell>
<mxCell id="act" value="Admin" style="shape=umlActor;verticalLabelPosition=bottom;" vertex="1" parent="1"><mxGeometry x="400" y="200" width="30" height="60" as="geometry"/></mxCell>
<mxCell id="db" value="DB" style="shape=cylinder3;" vertex="1" parent="1"><mxGeometry x="480" y="200" width="80" height="80" as="geometry"/></mxCell>
<mxCell id="cl" value="Internet" style="shape=cloud;" vertex="1" parent="1"><mxGeometry x="480" y="320" width="120" height="70" as="geometry"/></mxCell>
<mxCell id="hx" value="Hex" style="shape=hexagon;dashed=1;shadow=1;" vertex="1" parent="1"><mxGeometry x="620" y="200" width="100" height="60" as="geometry"/></mxCell>
<mxCell id="nt" value="Note" style="shape=note;" vertex="1" parent="1"><mxGeometry x="620" y="300" width="100" height="60" as="geometry"/></mxCell>
<mxCell id="doc" value="Doc" style="shape=document;" vertex="1" parent="1"><mxGeometry x="740" y="200" width="100" height="60" as="geometry"/></mxCell>
<mxCell id="er" style="endArrow=ERmany;startArrow=ERmandOne;" edge="1" parent="1" source="cls" target="db"><mxGeometry relative="1" as="geometry"/></mxCell>
<mxCell id="m" value="GET /x" style="endArrow=block;dashed=1;" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="300" y="300" as="sourcePoint"/><mxPoint x="415" y="300" as="targetPoint"/></mxGeometry></mxCell>
<mxCell id="inh" style="endArrow=block;endFill=0;edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="hx" target="nt"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="700" y="280"/></Array></mxGeometry></mxCell>
<mxCell id="dia" style="endArrow=diamond;startArrow=oval;" edge="1" parent="1" source="doc" target="cl"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


class FakeAi:
    def __init__(self):
        self.prompts = []
        self.answers = []

    async def ask(self, prompt, system="", model="haiku"):
        self.prompts.append((prompt, model))
        return self.answers.pop(0) if self.answers else f"Here you go:\n```xml\n{FLOW}\n```"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "drawio.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["drawio"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("drawio")
    ctx.ai = ai = FakeAi()
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    async def run_here(fn, *args):   # the window would run it on the UI thread – the test is on it
        return fn(*args)
    ctx.ui.run = run_here
    return store, pm, ctx, ai, tmp_path


def make_run(store, pm, tmp, cfg=None, handover="Login: start, check the data, on success the dashboard."):
    n = pm.node("drawio/diagram")
    cfg = {**n.defaults(), **(cfg or {})}
    pid = store.save("process", {"name": "D", "start": "g", "steps": [
        {"id": "g", "type": "plugin", "plugin_node": n.id, "plugin_config": cfg, "plugin_outputs": "ports",
         "plugin_ports": n.ports(cfg), "plugin_routes": {"diagram": "end", "error": "end"}}]})
    proj = store.save("project", {"name": "Docs", "workspace": str(tmp / "ws"), "process_id": pid})
    (tmp / "ws").mkdir(exist_ok=True)
    ctrl = Engine(store).controller(store.create_run(proj, "Diagram"))
    if handover:
        store.update_run(ctrl.run_id, inbox={"g": [{"id": "h1", "from": "Writer", "agent": "Writer",
                                                    "text": handover}]})
    return ctrl


def run(ctrl, task="Draw the login"):
    return asyncio.run(ctrl._execute(0, task))


def blocks(store, run_id):
    return [e for e in store.events(run_id) if e["type"] == "plugin_message"]


def texts(store, run_id):
    return "\n".join(e.get("text") or "" for e in store.events(run_id))


def mod(name):
    import importlib
    return importlib.import_module(f"drawio_diagrams.{name}")


# ------------------------------------------------------------------ the node
def test_the_node(env):
    store, pm, ctx, ai, tmp = env
    n = pm.node("drawio/diagram")
    assert [(p["id"], p.get("color")) for p in n.ports(n.defaults())["outputs"]] == [("diagram", "success"),
                                                                                     ("error", "error")]
    assert [f["key"] for f in n.fields] == ["description", "type", "style", "direction", "folder", "filename", "scale"]
    kinds = [o["value"] for o in n.fields[1]["options"]]
    assert kinds[0] == "auto" and {"flowchart", "sequence", "class", "er", "architecture", "mindmap"} <= set(kinds)


def test_a_diagram_and_its_png(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp)
    out = run(ctrl)
    folder = tmp / "ws" / "diagrams"
    assert sorted(p.name for p in folder.iterdir()) == ["login-flow.drawio", "login-flow.png"]
    assert (folder / "login-flow.drawio").read_text().startswith("<mxfile")
    assert (folder / "login-flow.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    prompt, model = ai.prompts[0]
    assert "check the data" in prompt and "Draw the login" in prompt and model == "sonnet"
    assert "KIND: the one the description asks for" in prompt
    (ev,) = blocks(store, ctrl.run_id)
    d = ev["data"]
    assert ev["kind"] == "diagram" and d["title"] == "Login flow" and d["exporter"] == "built-in"
    assert d["width"] > 300 and d["height"] > 600 and d["warnings"] == []    # 2× scale
    assert f"DRAWIO_FILE: {folder / 'login-flow.drawio'}" in texts(store, ctrl.run_id)
    assert "Output “Error”" not in out


def test_the_kind_fixed_named_or_chosen(env):
    store, pm, ctx, ai, tmp = env
    run(make_run(store, pm, tmp, {"type": "sequence"}))
    assert "KIND: Sequence diagram – participants as shape=umlLifeline" in ai.prompts[-1][0]
    run(make_run(store, pm, tmp, handover="DIAGRAM_TYPE: ER\nCustomers have orders."))
    assert "KIND: Entity relationship (ER) diagram" in ai.prompts[-1][0]
    run(make_run(store, pm, tmp, {"type": "class"}, handover="DIAGRAM_TYPE: sequence\nx"))
    assert "KIND: UML class diagram" in ai.prompts[-1][0]          # the node's fixed kind wins
    run(make_run(store, pm, tmp, {"style": "black and white", "direction": "LR"}))
    assert "LOOK: black and white" in ai.prompts[-1][0] and "DIRECTION: left to right" in ai.prompts[-1][0]


def test_problems_go_back_to_the_ai(env):
    store, pm, ctx, ai, tmp = env
    ai.answers = [BROKEN, FLOW]
    ctrl = make_run(store, pm, tmp)
    run(ctrl)
    assert len(ai.prompts) == 2 and "edge e2: its target gone doesn't exist" in ai.prompts[1][0]
    assert blocks(store, ctrl.run_id)[0]["data"]["warnings"] == []
    ai.answers = [OVERLAP, OVERLAP, OVERLAP]
    ctrl = make_run(store, pm, tmp)
    run(ctrl)                                                  # only a warning left: the diagram still comes
    assert "shapes overlap: Valid? / Dashboard" in blocks(store, ctrl.run_id)[0]["data"]["warnings"][0]


def test_unusable_answers_go_to_error(env):
    store, pm, ctx, ai, tmp = env
    ai.answers = ["Sorry, no.", "<mxfile>broken", BROKEN]
    out = run(make_run(store, pm, tmp))
    assert "Output “Error”" in out and len(ai.prompts) == 3
    assert not (tmp / "ws" / "diagrams").exists() or not list((tmp / "ws" / "diagrams").iterdir())


def test_without_a_description_it_goes_to_error(env):
    store, pm, ctx, ai, tmp = env
    out = asyncio.run(make_run(store, pm, tmp, handover="")._execute(0, ""))
    assert "Output “Error”" in out and not ai.prompts


def test_one_diagram_per_run_nothing_overwritten(env):
    store, pm, ctx, ai, tmp = env
    for _ in range(2):
        run(make_run(store, pm, tmp, {"filename": "Login Ablauf.drawio", "folder": "out"}))
    assert sorted(p.name for p in (tmp / "ws" / "out").iterdir()) == [
        "Login Ablauf-2.drawio", "Login Ablauf-2.png", "Login Ablauf.drawio", "Login Ablauf.png"]


# ------------------------------------------------------------------ the file and the drawing
def test_the_check_and_compressed_files():
    m = mod("model")
    assert m.check(FLOW) == ([], [])
    errors, _ = m.check(FLOW.replace('id="d" value="Valid?"', 'id="s" value="Valid?"'))
    assert any("duplicate cell ids: s" in e for e in errors)
    assert m.check("<mxfile><diagram")[0][0].startswith("the XML is broken")
    assert m.check('<mxfile><diagram name="x"><mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
                   '</diagram></mxfile>')[0] == ["the diagram has no shapes"]
    no_size = FLOW.replace('width="120" height="50" as="geometry"/></mxCell>\n<mxCell id="d"',
                           'as="geometry"/></mxCell>\n<mxCell id="d"')
    assert any("no width/height" in e for e in m.check(no_size)[0])
    inner = FLOW.split('name="Login flow">')[1].split("</diagram>")[0]
    packed = base64.b64encode(zlib.compress(urllib.parse.quote(inner).encode())[2:-4]).decode()
    name, cells = m.cells(f'<mxfile><diagram name="Packed">{packed}</diagram></mxfile>')
    assert name == "Packed" and len([c for c in cells if c.vertex]) == 3
    assert m.extract_xml("bla <mxGraphModel><root/></mxGraphModel> bla").startswith("<mxfile")
    assert m.plain("a<br>b&nbsp;<b>c</b>") == "a\nb c"


def test_the_renderer_draws_all_kinds_of_shapes(tmp_path):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    r = mod("render")
    w, h = r.render_png(MIXED, str(tmp_path / "m.png"), 1.0)
    img = QImage(str(tmp_path / "m.png"))
    assert (img.width(), img.height()) == (w, h) and w > 800 and h > 380
    colours = {img.pixelColor(x, y).name() for x in range(0, w, 7) for y in range(0, h, 7)}
    assert len(colours) > 5                                   # not an empty white picture
    if os.environ.get("DRAWIO_SHOT"):
        r.render_png(MIXED, os.environ["DRAWIO_SHOT"], 1.5)


# ------------------------------------------------------------------ the chat and the large view
def test_the_picture_in_the_chat_and_the_large_view(env):
    store, pm, ctx, ai, tmp = env
    ctrl = make_run(store, pm, tmp)
    run(ctrl)
    data = blocks(store, ctrl.run_id)[0]["data"]
    card = pm.chat_renderers[("drawio", "diagram")](data)
    png = Path(data["png"])
    assert f'<img src="{png.as_uri()}"' in card and "theron-plugin://drawio/zoom" in card
    assert "Large view" in card and "Open in draw.io" in card and "Login flow" in card
    opened = []
    ctx.ui.open_window = lambda title, factory, **kw: opened.append((title, factory, kw))
    pm.chat_links[("drawio", "zoom")]({"png": str(png), "drawio": data["drawio"], "title": "Login flow"})
    ((title, factory, kw),) = opened
    assert title == "📐 Login flow" and kw["id"] == f"zoom:{png}"
    view = factory(None)
    view.resize(500, 400)
    view.show()
    view.act("one")
    assert view.level.text() == "100 %" and view.image.pixmap().width() == data["width"]
    view.act("in")
    assert view.level.text() == "125 %"
    view.act("fit")
    assert int(view.level.text().rstrip(" %")) < 100
    urls = []
    ctx.ui.open_url = urls.append
    pm.chat_links[("drawio", "open")]({"path": data["drawio"]})
    assert urls == [Path(data["drawio"]).as_uri()]
    view.close()
    png.unlink()
    assert "The picture is gone." in pm.chat_renderers[("drawio", "diagram")](data)


# ------------------------------------------------------------------ settings: the way to the PNG
def test_the_settings_offer_three_ways(env):
    store, pm, ctx, ai, tmp = env
    s = next(s for s in pm.plugins["drawio"].manifest.settings if s.key == "exporter")
    assert [o["value"] for o in s.options] == ["builtin", "desktop", "docker"] and s.default == "builtin"
    test, pull = pm.settings_buttons_for("drawio")
    ok, text = asyncio.run(test.run({"exporter": "builtin"}))
    assert ok and "plugin's own renderer" in text
    ex = pm.plugins["drawio"].module.exporters
    ex_find = ex.find_drawio
    try:
        ex.find_drawio = lambda setting="": ""
        ok, text = asyncio.run(test.run({"exporter": "desktop"}))
        assert not ok and "not installed" in text
    finally:
        ex.find_drawio = ex_find


def test_choosing_desktop_finds_draw_io_or_asks_where_it_is(env, tmp_path, monkeypatch):
    store, pm, ctx, ai, tmp = env
    ex = pm.plugins["drawio"].module.exporters
    (edit,) = pm.settings_edits_for("drawio", "exporter")
    app = tmp_path / "draw.io.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "draw.io").write_text("#!/bin/sh\necho 29.0.3\n")
    (app / "draw.io").chmod(0o755)
    asked = []

    def ask_files(title, filter="", *, multiple=True, start=""):
        asked.append((title, multiple))
        return [str(tmp_path / "draw.io.app")]                   # the user picks the .app bundle
    monkeypatch.setattr(type(ctx.ui), "ask_files", lambda self, *a, **k: ask_files(*a, **k))
    monkeypatch.setattr(ex, "find_drawio", lambda setting="": "")          # not installed where it is looked for
    r = asyncio.run(edit.run({"exporter": "desktop", "drawio_path": ""}, "exporter"))
    assert asked == [("Where is the draw.io app?", False)]
    assert r["ok"] and r["values"] == {"drawio_path": str(app / "draw.io")} and "29.0.3" in r["text"]
    asked.clear()
    monkeypatch.setattr(ex, "find_drawio", lambda setting="": str(app / "draw.io"))   # found by itself
    r = asyncio.run(edit.run({"exporter": "desktop", "drawio_path": ""}, "exporter"))
    assert not asked and r["values"] == {"drawio_path": str(app / "draw.io")}
    (tmp_path / "fake").write_text("#!/bin/sh\nexit 3\n")
    (tmp_path / "fake").chmod(0o755)
    monkeypatch.setattr(ex, "find_drawio", lambda setting="": "")
    monkeypatch.setattr(type(ctx.ui), "ask_files", lambda self, *a, **k: [str(tmp_path / "fake")])
    ok, text = asyncio.run(edit.run({"exporter": "desktop", "drawio_path": ""}, "exporter"))
    assert not ok and "isn't a working draw.io" in text
    monkeypatch.setattr(type(ctx.ui), "ask_files", lambda self, *a, **k: [])
    ok, text = asyncio.run(edit.run({"exporter": "desktop", "drawio_path": ""}, "exporter"))
    assert not ok and "wasn't found" in text
    assert asyncio.run(edit.run({"exporter": "builtin"}, "exporter")) is None


def test_choosing_docker_checks_docker(env, monkeypatch):
    store, pm, ctx, ai, tmp = env
    ex = pm.plugins["drawio"].module.exporters
    (edit,) = pm.settings_edits_for("drawio", "exporter")
    monkeypatch.setattr(ex, "find_docker", lambda: "")
    ok, text = asyncio.run(edit.run({"exporter": "docker"}, "exporter"))
    assert not ok and "Docker is not installed" in text and "docker.com" in text
    monkeypatch.setattr(ex, "docker_ready", lambda image: (False, f"the image {image} isn't loaded yet"))
    monkeypatch.setattr(ex, "find_docker", lambda: "/usr/local/bin/docker")
    ok, text = asyncio.run(edit.run({"exporter": "docker", "docker_image": "x/y:1"}, "exporter"))
    assert not ok and "x/y:1 isn't loaded" in text and "Load Docker image" in text
    monkeypatch.setattr(ex, "docker_ready", lambda image: (True, "sha256:1"))
    ok, text = asyncio.run(edit.run({"exporter": "docker"}, "exporter"))
    assert ok and "Docker is ready" in text


def test_the_settings_dialog_fills_in_the_path(env, tmp_path, monkeypatch):
    """Settings → Plugins → draw.io: choose “Use the desktop app” – the plugin checks and fills in the path."""
    from PySide6.QtWidgets import QApplication

    from theron.ui.plugins_ui import PluginSettingsDialog
    store, pm, ctx, ai, tmp = env
    app = QApplication.instance()
    ex = pm.plugins["drawio"].module.exporters
    exe = tmp_path / "drawio"
    exe.write_text("#!/bin/sh\necho 29.0.3\n")
    exe.chmod(0o755)
    monkeypatch.setattr(ex, "find_drawio", lambda setting="": str(exe))
    dlg = PluginSettingsDialog(store, pm.plugins["drawio"])
    kind, combo = dlg.inputs["exporter"]
    combo.setCurrentIndex(combo.findData("desktop"))
    end = time.time() + 10
    while time.time() < end and not dlg.result.text().startswith("✔"):
        app.processEvents()
        time.sleep(0.02)
    assert dlg.inputs["drawio_path"][1].text() == str(exe) and "draw.io 29.0.3 found" in dlg.result.text()
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Draw it myself (built-in renderer)", "Use the desktop app", "Load via Docker"]
    dlg.reject()


@pytest.mark.skipif(not os.environ.get("DRAWIO_DOCKER_TEST"), reason="needs Docker and the draw.io image")
def test_the_real_docker_export(tmp_path):
    ex = mod("exporters")
    (tmp_path / "f.drawio").write_text(FLOW)
    ex.docker(tmp_path / "f.drawio", tmp_path / "f.png", 1.0)
    assert (tmp_path / "f.png").read_bytes()[:4] == b"\x89PNG"


def test_package_and_translations():
    import json
    import zipfile
    from tempfile import mkdtemp
    names = zipfile.ZipFile(plugins.pack(HERE, Path(mkdtemp()) / "d.theronplugin")).namelist()
    assert "drawio_diagrams/render.py" in names and not any(n.startswith("tests/") for n in names)
    de = json.loads((HERE / "i18n" / "de.json").read_text(encoding="utf-8"))
    assert de["Load via Docker"] == "Lade via Docker" and de["Draw it myself (built-in renderer)"].startswith("Zeichne")
