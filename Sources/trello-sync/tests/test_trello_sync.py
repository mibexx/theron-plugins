"""Trello Sync against a fake Trello – run with Theron's Python:  python -m pytest Sources/trello-sync/tests"""
import asyncio
import itertools
import json
import os
import sys
import urllib.parse
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.plugins.http import Response  # noqa: E402
from theron.store import Store  # noqa: E402


class FakeTrello:
    """An in-memory Trello board with the REST calls the plugin uses."""

    def __init__(self, key="k", token="t"):
        self.key, self.token = key, token
        self.ids = itertools.count(1)
        self.boards = {"AbCd1234": {"id": "board1", "name": "Shop", "closed": False, "url": "https://trello.com/b/AbCd1234/shop"}}
        self.lists: dict[str, dict] = {}
        self.cards: dict[str, dict] = {}
        self.labels: dict[str, dict] = {}
        self.calls = []

    def nid(self, p):
        return f"{p}{next(self.ids)}"

    def add_list(self, name, pos=None):
        lid = self.nid("L")
        self.lists[lid] = {"id": lid, "name": name, "pos": pos or len(self.lists), "closed": False}
        return lid

    def add_card(self, lid, name, desc="", labels=(), due=False):
        cid = self.nid("C")
        self.cards[cid] = {"id": cid, "name": name, "desc": desc, "idList": lid, "idLabels": list(labels),
                           "dueComplete": due, "pos": len(self.cards), "closed": False}
        return cid

    def add_label(self, name, color=None):
        lid = self.nid("lb")
        self.labels[lid] = {"id": lid, "name": name, "color": color}
        return lid

    async def request(self, method, url, *, params=None, **kw):
        params = dict(params or {})
        path = urllib.parse.urlparse(url).path.removeprefix("/1")
        self.calls.append((method, path))
        if (params.pop("key", None), params.pop("token", None)) != (self.key, self.token):
            return Response(url, 401, {}, b"invalid key")
        parts = path.strip("/").split("/")
        out, status = None, 200
        if method == "GET" and parts[0] == "boards":
            board = self.boards.get(parts[1]) or next((b for b in self.boards.values() if b["id"] == parts[1]), None)
            if board is None:
                return Response(url, 404, {}, b"not found")
            if len(parts) == 2:
                out = board
            elif parts[2] == "lists":
                out = [x for x in self.lists.values() if not x["closed"]]
            elif parts[2] == "cards":
                out = [x for x in self.cards.values() if not x["closed"] and not self.lists[x["idList"]]["closed"]]
            elif parts[2] == "labels":
                out = list(self.labels.values())
        elif method == "POST" and parts == ["lists"]:
            out = self.lists[self.add_list(params["name"], pos=len(self.lists) + 100)]
        elif method == "POST" and parts == ["cards"]:
            labels = [x for x in params.get("idLabels", "").split(",") if x]
            out = self.cards[self.add_card(params["idList"], params["name"], params.get("desc", ""), labels)]
        elif method == "POST" and parts == ["labels"]:
            out = self.labels[self.add_label(params["name"], params.get("color"))]
        elif method == "PUT" and parts[0] in ("lists", "cards"):
            store = self.lists if parts[0] == "lists" else self.cards
            obj = store[parts[1]]
            for k, v in params.items():
                if k == "closed":
                    obj["closed"] = v == "true"
                elif k == "idLabels":
                    obj["idLabels"] = [x for x in v.split(",") if x]
                else:
                    obj[k] = v
            out = obj
        else:
            status = 400
        return Response(url, status, {}, json.dumps(out).encode())


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "trello.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["trello-sync"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("trello-sync")
    fake = FakeTrello()
    ctx.http = fake
    ctx.settings.update({"api_key": "k", "token": "t"})
    project = store.save("project", {"name": "P", "workspace": str(tmp_path)})
    tl = ctx.tasklists.create(project, "Backlog")
    return store, pm, ctx, fake, tl, info.module.TaskListSync(ctx)   # a sync of its own, as the plugin has


def test_the_button_follows_the_link(env):
    store, pm, ctx, fake, tl, sync = env
    (sync_btn, unlink_btn) = pm.actions_for("tasks")
    assert sync_btn.label({}) is None                                     # no list selected → no button
    assert sync_btn.label({"tasklist_id": tl}) == "Sync with Trello" and unlink_btn.label({"tasklist_id": tl}) is None
    ctx.storage.set(f"link:{tl}", {"board": "board1", "direction": "read", "lists": {}, "cards": {}})
    assert sync_btn.label({"tasklist_id": tl}) == "⟳ Sync" and unlink_btn.label({"tasklist_id": tl}) == "Unlink Trello"


def test_inspect_says_whether_the_board_fits(env):
    store, pm, ctx, fake, tl, sync = env
    assert "no Trello board" in asyncio.run(sync.inspect(tl, "?? x"))["error"]
    assert "Not found" in asyncio.run(sync.inspect(tl, "Nope1234"))["error"]
    found = asyncio.run(sync.inspect(tl, "https://trello.com/b/AbCd1234/shop"))
    assert found["ok"] and not found["can_read"] and found["can_write"]   # no lists yet: only writing
    fake.add_list("Todo")
    found = asyncio.run(sync.inspect(tl, "AbCd1234"))
    assert found.get("can_read") and found["board"] == "Shop" and "1 lists" in found["text"], found
    ctx.settings.set("token", "wrong")
    assert "refused" in asyncio.run(sync.inspect(tl, "AbCd1234"))["error"]
    fake.boards["AbCd1234"]["closed"] = True
    ctx.settings.set("token", "t")
    assert "closed" in asyncio.run(sync.inspect(tl, "AbCd1234"))["error"]


def test_read_trello_into_the_task_list(env):
    store, pm, ctx, fake, tl, sync = env
    done = fake.add_label("Done", "green")
    todo, doing = fake.add_list("Login"), fake.add_list("Checkout")
    c1 = fake.add_card(todo, "Form", "A login form\n\n---\n**Acceptance criteria**\nworks with SSO", [done])
    fake.add_card(todo, "Reset password", due=True)
    c3 = fake.add_card(doing, "Pay with card")
    sync.save_link(tl, {"board": "board1", "direction": "read", "lists": {}, "cards": {}})
    rep = asyncio.run(sync.sync(tl))
    assert rep["new"] == 3 and rep["epics_new"] == 2
    got = ctx.tasklists.get(tl)
    assert [e["name"] for e in got["epics"]] == ["Login", "Checkout"]
    form = got["epics"][0]["requirements"][0]
    assert (form["title"], form["description"], form["acceptance"], form["status"]) == \
        ("Form", "A login form", "works with SSO", "done")
    assert got["epics"][0]["requirements"][1]["status"] == "done"            # completed due date
    # changes on Trello come over on the next sync – and nothing is duplicated
    fake.cards[c1]["name"] = "Login form"
    fake.cards[c3]["closed"] = True
    fake.add_card(doing, "Invoice")
    rep = asyncio.run(sync.sync(tl))
    assert (rep["new"], rep["changed"], rep["deleted"], rep["epics_new"]) == (1, 1, 1, 0)
    got = ctx.tasklists.get(tl)
    assert [r["title"] for e in got["epics"] for r in e["requirements"]] == ["Login form", "Reset password", "Invoice"]
    assert "1 new" in sync.report_text(sync.link(tl))
    # a card moved to another list → its requirement moves to that epic
    fake.cards[c1]["idList"] = doing
    asyncio.run(sync.sync(tl))
    got = ctx.tasklists.get(tl)
    assert [r["title"] for r in got["epics"][1]["requirements"]] == ["Invoice", "Login form"]


def test_write_the_task_list_to_trello(env):
    store, pm, ctx, fake, tl, sync = env
    e1 = ctx.tasklists.add_epic(tl, "Login")
    r1 = ctx.tasklists.add_requirement(e1, "Form", description="A form", acceptance="SSO", status="done")
    r2 = ctx.tasklists.add_requirement(e1, "Reset")
    e2 = ctx.tasklists.add_epic(tl, "Checkout")
    ctx.tasklists.add_requirement(e2, "Pay", status="in_progress")
    other = fake.add_list("Ideas")                                          # the user's own list – stays untouched
    mine = fake.add_label("Urgent", "red")
    sync.save_link(tl, {"board": "board1", "direction": "write", "lists": {}, "cards": {}})
    rep = asyncio.run(sync.sync(tl))
    assert rep["lists_new"] == 2 and rep["new"] == 3
    names = {c["name"]: c for c in fake.cards.values()}
    assert names["Form"]["desc"].endswith("**Acceptance criteria**\nSSO")
    label_names = {fake.labels[x]["name"] for x in names["Form"]["idLabels"]}
    assert label_names == {"Theron: done"} and names["Reset"]["idLabels"] == []
    assert {fake.labels[x]["name"] for x in names["Pay"]["idLabels"]} == {"Theron: in progress"}
    # the user adds an own label on Trello; Theron changes status and title, deletes one requirement
    names["Form"]["idLabels"].append(mine)
    ctx.tasklists.update_requirement(r1, status="failed", title="Login form")
    ctx.tasklists.delete_requirement(r2)
    rep = asyncio.run(sync.sync(tl))
    assert (rep["new"], rep["changed"], rep["archived"]) == (0, 1, 1)
    form = next(c for c in fake.cards.values() if c["name"] == "Login form")
    assert {fake.labels[x]["name"] for x in form["idLabels"]} == {"Theron: failed", "Urgent"}   # own label kept
    assert next(c for c in fake.cards.values() if c["name"] == "Reset")["closed"]
    ctx.tasklists.delete_epic(e2)
    rep = asyncio.run(sync.sync(tl))
    assert rep["lists_archived"] == 1 and not fake.lists[other]["closed"]
    assert sum(1 for x in fake.lists.values() if x["name"] == "Login") == 1   # nothing duplicated
    rep = asyncio.run(sync.sync(tl))
    assert rep == {"lists_new": 0, "lists_changed": 0, "lists_archived": 0, "new": 0, "changed": 0, "archived": 0}


def test_a_failed_sync_is_reported_and_kept_in_the_link(env):
    store, pm, ctx, fake, tl, sync = env
    sync.save_link(tl, {"board": "gone", "direction": "read", "lists": {}, "cards": {}})
    with pytest.raises(Exception) as exc:
        asyncio.run(sync.sync(tl))
    assert "Not found" in str(exc.value) and "Not found" in sync.link(tl)["error"]
    assert tl not in sync.running


def test_the_package_is_clean():
    import zipfile
    from tempfile import mkdtemp
    pkg = plugins.pack(HERE, Path(mkdtemp()) / "t.theronplugin")
    names = zipfile.ZipFile(pkg).namelist()
    assert "plugin.toml" in names and "trello_sync/sync.py" in names and not any(n.startswith("tests/") for n in names)
    de = json.loads((HERE / "i18n" / "de.json").read_text(encoding="utf-8"))
    assert de["Read (Trello → Theron)"] == "Lesen (Trello → Theron)"


def test_the_whole_flow_in_the_app_window(env, monkeypatch):
    """Click “Sync with Trello” on the task-list page: board id → board read → direction → sync → “⟳ Sync”."""
    import time

    from PySide6.QtWidgets import QApplication

    from theron.engine.orchestrator import Engine
    from theron.ui import pickers, usage_bar
    from theron.ui.main_window import MainWindow
    store, pm, ctx, fake, tl, _ = env
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(usage_bar.UsageMonitor, "refresh", lambda self: None)
    monkeypatch.setattr(pickers.ModelCatalog, "refresh", lambda self, *a, **k: None)
    monkeypatch.setattr(plugins.PluginManager, "start", lambda self: None)
    fake.add_card(fake.add_list("Login"), "Form")
    asked = []
    monkeypatch.setattr(type(ctx.ui), "ask_text", lambda self, title, text, default="": asked.append(text) or "AbCd1234")
    monkeypatch.setattr(type(ctx.ui), "ask_choice", lambda self, title, text, options: asked.append(text) or options[0])
    notes = []
    monkeypatch.setattr(type(ctx), "notify", lambda self, text, level="info": notes.append(text))
    w = MainWindow(store, Engine(store))
    w.show_page(4)
    w.tasks.project_id, w.tasks.tasklist_id = store.child("tasklist", tl)["parent_id"], tl
    w._panel_context()
    host = w.panel_hosts[4]
    btn = next(b for s, b in host.action_buttons if s.id == "sync")
    assert btn.text() == "▦ Sync with Trello"
    btn.click()
    end = time.time() + 5
    while time.time() < end and not any("Read from Trello" in n for n in notes):
        app.processEvents()
        time.sleep(0.02)
    assert any("Read from Trello: 1 new" in n for n in notes), notes
    assert "Board id or link" in asked[0] and "Board “Shop”: 1 lists, 1 cards." in asked[1]
    assert [r["title"] for e in ctx.tasklists.get(tl)["epics"] for r in e["requirements"]] == ["Form"]
    assert btn.text() == "▦ ⟳ Sync"
    w.close()
