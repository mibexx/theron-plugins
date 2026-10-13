"""Trello Sync – a Theron task list ↔ a Trello board.

On the task-list page (TASKS) a button “Sync with Trello” appears for the selected list: enter the board's id or link,
the plugin reads the board, says what it found and asks for the direction – read (Trello → Theron) or write
(Theron → Trello). After that the button is “⟳ Sync” and syncs again in that direction; “Unlink Trello” removes the
link. The API key and token are in the plugin's settings (Settings → Plugins → Trello Sync → Settings …).
"""

from __future__ import annotations

from .sync import TaskListSync
from .trello import TrelloError


def register(ctx):
    sync = TaskListSync(ctx)
    if not ctx.ui.available:   # the buttons live in the desktop app – nothing to do on a slave
        return

    def sync_label(context):
        tid = context.get("tasklist_id")
        if not tid:
            return None
        if tid in sync.running:
            return ctx.tr("Syncing …")
        return ctx.tr("⟳ Sync") if sync.link(tid) else ctx.tr("Sync with Trello")

    def unlink_label(context):
        tid = context.get("tasklist_id")
        return ctx.tr("Unlink Trello") if tid and sync.link(tid) and tid not in sync.running else None

    def clicked(context):
        tid = context["tasklist_id"]
        if tid in sync.running:
            return
        if not sync.trello.configured():
            ctx.ui.message(ctx.tr("Sync with Trello"), ctx.tr("Enter your Trello API key and token in the plugin "
                                                              "settings first (Settings → Plugins → Trello Sync)."),
                           "warning")
            return
        if sync.link(tid):
            start(tid)
            return
        raw = ctx.ui.ask_text(ctx.tr("Sync with Trello"), ctx.tr("Board id or link of the Trello board:"))
        if not raw:
            return
        ctx.notify(ctx.tr("Reading the Trello board …"))
        future = ctx.spawn(sync.inspect, tid, raw)
        future.add_done_callback(lambda f: ctx.ui.call(inspected, tid, f.result() or {"ok": False, "error": "?"}))

    def inspected(tid, found):
        title = ctx.tr("Sync with Trello")
        if not found.get("ok"):
            ctx.ui.message(title, ctx.tr("The board doesn't fit: {error}", error=found.get("error", "")), "error")
            return
        read, write = ctx.tr("Read (Trello → Theron)"), ctx.tr("Write (Theron → Trello)")
        options = ([read] if found["can_read"] else []) + ([write] if found["can_write"] else [])
        choice = ctx.ui.ask_choice(title, found["text"] + "\n\n" + ctx.tr("In which direction should it sync?"), options)
        if not choice:
            return
        sync.save_link(tid, {"board": found["board_id"], "board_name": found["board"], "url": found["url"],
                             "direction": "read" if choice == read else "write", "lists": {}, "cards": {}})
        start(tid)

    def start(tid):
        sync.running.add(tid)
        ctx.ui.refresh_actions()

        async def job():
            try:
                await sync.sync(tid)
                return None
            except Exception as exc:  # noqa: BLE001 – shown to the user
                return str(exc)
            finally:
                sync.running.discard(tid)
        future = ctx.spawn(job)
        future.add_done_callback(lambda f: ctx.ui.call(finished, tid, f.result()))

    def finished(tid, error):
        ctx.ui.refresh_actions()
        link = sync.link(tid) or {}
        if error:
            ctx.notify(ctx.tr("Trello sync failed: {error}", error=error), "error")
        else:
            ctx.notify(f"„{link.get('board_name', '')}“ · " + sync.report_text(link))

    def unlink(context):
        tid = context["tasklist_id"]
        link = sync.link(tid) or {}
        answer = ctx.ui.ask_choice(ctx.tr("Unlink Trello"), ctx.tr("Remove the link to the board “{name}”? Nothing "
                                                                   "is deleted – neither in Theron nor on Trello.",
                                                                   name=link.get("board_name", "")),
                                   [ctx.tr("Unlink")])
        if answer:
            sync.unlink(tid)

    ctx.ui.add_action("tasks", sync_label, clicked, id="sync", icon="▦", style="primary",
                      tooltip=ctx.tr("Sync this task list with a Trello board"))
    ctx.ui.add_action("tasks", unlink_label, unlink, id="unlink",
                      tooltip=ctx.tr("Remove the link to the Trello board (nothing is deleted)"))
