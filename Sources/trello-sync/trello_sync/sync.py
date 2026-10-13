"""The sync between one Theron task list and one Trello board – in the direction the user chose.

The structure on both sides:

    Trello board  ↔  Theron task list
    list          ↔  epic
    card          ↔  requirement   (name ↔ title, description ↔ description + acceptance criteria)
    label         ↔  status        (“Theron: done”, “Theron: in progress” … – no label = open)

    read   Trello → Theron: the board's lists and cards become the epics and requirements of the list
    write  Theron → Trello: the list's epics and requirements become lists and cards on the board

What belongs together is remembered per task list (``ctx.storage`` "link:<task list id>"): which list is which epic,
which card which requirement. The first sync matches by name, so an existing board or list isn't duplicated. Only
what the sync linked is ever deleted or archived – lists and cards of the board that have nothing to do with the
task list stay untouched when writing.
"""

from __future__ import annotations

import asyncio
import time

from .trello import Trello, TrelloError

STATUS_LABELS = {   # Theron status → (Trello label, colour); "open" has no label
    "in_progress": ("Theron: in progress", "blue"),
    "hitl": ("Theron: needs input", "yellow"),
    "done": ("Theron: done", "green"),
    "failed": ("Theron: failed", "red"),
    "skipped": ("Theron: skipped", "black"),
    "closed": ("Theron: closed", "black"),
}
SYNONYMS = {   # label names (lower case) read as a status – Theron's own and common ones
    **{name.lower(): status for status, (name, _) in STATUS_LABELS.items()},
    "done": "done", "erledigt": "done", "fertig": "done", "complete": "done", "completed": "done",
    "in progress": "in_progress", "in arbeit": "in_progress", "doing": "in_progress", "wip": "in_progress",
    "blocked": "hitl", "blockiert": "hitl", "needs input": "hitl", "failed": "failed", "fehlgeschlagen": "failed",
}
ACCEPTANCE = "**Acceptance criteria**"


def link_key(tasklist_id: int) -> str:
    return f"link:{tasklist_id}"


def card_text(req: dict) -> str:
    desc = (req.get("description") or "").strip()
    acc = (req.get("acceptance") or "").strip()
    return f"{desc}\n\n---\n{ACCEPTANCE}\n{acc}".strip() if acc else desc


def split_card(desc: str) -> tuple[str, str]:
    """Card description → (description, acceptance criteria)."""
    if ACCEPTANCE in (desc or ""):
        head, _, acc = desc.partition(ACCEPTANCE)
        return head.rstrip().removesuffix("---").rstrip(), acc.strip()
    return (desc or "").strip(), ""


def card_status(card: dict, labels: dict[str, dict]) -> str:
    for lid in card.get("idLabels") or []:
        status = SYNONYMS.get(((labels.get(lid) or {}).get("name") or "").strip().lower())
        if status:
            return status
    return "done" if card.get("dueComplete") else "open"


class TaskListSync:
    def __init__(self, ctx, trello: Trello | None = None):
        self.ctx = ctx
        self.trello = trello or Trello(ctx)
        self.locks: dict[int, asyncio.Lock] = {}
        self.running: set[int] = set()

    # ------------------------------------------------------------------ the link of a task list
    def link(self, tasklist_id: int) -> dict | None:
        return self.ctx.storage.get(link_key(tasklist_id))

    def save_link(self, tasklist_id: int, link: dict) -> None:
        self.ctx.storage.set(link_key(tasklist_id), link)

    def unlink(self, tasklist_id: int) -> None:
        self.ctx.storage.delete(link_key(tasklist_id))

    # ------------------------------------------------------------------ 1. look at the board
    async def inspect(self, tasklist_id: int, raw_board: str) -> dict:
        """Does the board fit? {"ok", "error", "board_id", "board", "url", "lists", "cards", "can_read",
        "can_write", "text"} – never raises."""
        from .trello import board_id
        try:
            bid = board_id(raw_board)
            board = await self.trello.board(bid)
            lists = await self.trello.lists(bid)
            cards = await self.trello.cards(bid)
        except TrelloError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 – no connection …
            return {"ok": False, "error": self.ctx.tr("Trello can't be reached: {error}", error=exc)}
        if board.get("closed"):
            return {"ok": False, "error": self.ctx.tr("The board “{name}” is closed.", name=board.get("name", ""))}
        tl = self.ctx.tasklists.get(tasklist_id) or {"name": "", "epics": []}
        epics = tl["epics"]
        reqs = sum(len(e["requirements"]) for e in epics)
        epic_names = {e["name"].strip().lower() for e in epics}
        foreign = [lst["name"] for lst in lists if lst["name"].strip().lower() not in epic_names]
        can_read = bool(lists)
        can_write = True
        t = self.ctx.tr
        parts = [t("Board “{name}”: {lists} lists, {cards} cards.", name=board.get("name", ""), lists=len(lists),
                   cards=len(cards))]
        parts.append(t("Read (Trello → Theron): every list becomes an epic, every card a requirement of “{tl}” – "
                       "{lists} epics, {cards} requirements.", tl=tl["name"], lists=len(lists), cards=len(cards))
                     if can_read else t("Read: not possible – the board has no lists."))
        parts.append(t("Write (Theron → Trello): {epics} epics become lists, {reqs} requirements cards; the status is "
                       "shown as a label.", epics=len(epics), reqs=reqs))
        if foreign and epics:
            parts.append(t("When writing, these lists of the board stay untouched: {names}",
                           names=", ".join(foreign[:8]) + (" …" if len(foreign) > 8 else "")))
        return {"ok": can_read or can_write, "error": "", "board_id": board.get("id") or bid,
                "board": board.get("name", ""), "url": board.get("url", ""), "lists": len(lists), "cards": len(cards),
                "can_read": can_read, "can_write": can_write, "text": "\n\n".join(parts)}

    # ------------------------------------------------------------------ 2. sync
    async def sync(self, tasklist_id: int) -> dict:
        """Sync in the linked direction. Returns the report (also stored in the link); raises TrelloError."""
        link = self.link(tasklist_id)
        if not link:
            raise TrelloError(self.ctx.tr("This task list isn't linked with a Trello board."))
        lock = self.locks.setdefault(tasklist_id, asyncio.Lock())
        async with lock:
            self.running.add(tasklist_id)
            try:
                if link["direction"] == "read":
                    report = await self._read(tasklist_id, link)
                else:
                    report = await self._write(tasklist_id, link)
                link.update(last=time.time(), report=report, error="")
                return report
            except Exception as exc:
                link.update(last=time.time(), error=str(exc))
                raise
            finally:
                self.save_link(tasklist_id, link)
                self.running.discard(tasklist_id)

    # ---- Trello → Theron
    async def _read(self, tid: int, link: dict) -> dict:
        tls, t = self.ctx.tasklists, self.trello
        bid = link["board"]
        lists = sorted(await t.lists(bid), key=lambda x: x.get("pos", 0))
        cards = sorted(await t.cards(bid), key=lambda x: x.get("pos", 0))
        labels = {lb["id"]: lb for lb in await t.labels(bid)}
        tl = tls.get(tid)
        if tl is None:
            raise TrelloError(self.ctx.tr("The task list doesn't exist any more."))
        epics = {e["id"]: e for e in tl["epics"]}
        reqs = {r["id"]: (r, e["id"]) for e in tl["epics"] for r in e["requirements"]}
        list_map = {k: v for k, v in (link.get("lists") or {}).items() if v in epics}
        card_map = {k: v for k, v in (link.get("cards") or {}).items() if v in reqs}
        rep = {"epics_new": 0, "epics_changed": 0, "epics_deleted": 0, "new": 0, "changed": 0, "deleted": 0}
        seen_lists, seen_cards = set(), set()
        for lst in lists:
            seen_lists.add(lst["id"])
            eid = list_map.get(lst["id"])
            if eid is None:   # first time: an epic with the same name, else a new one
                eid = next((e["id"] for e in epics.values() if e["name"].strip().lower() == lst["name"].strip().lower()
                            and e["id"] not in list_map.values()), None)
            if eid is None:
                eid = tls.add_epic(tid, lst["name"])
                epics[eid] = {"id": eid, "name": lst["name"], "requirements": []}
                rep["epics_new"] += 1
            elif epics[eid]["name"] != lst["name"]:
                tls.update_epic(eid, name=lst["name"])
                rep["epics_changed"] += 1
            list_map[lst["id"]] = eid
            for card in (c for c in cards if c["idList"] == lst["id"]):
                seen_cards.add(card["id"])
                desc, acc = split_card(card.get("desc", ""))
                status = card_status(card, labels)
                rid = card_map.get(card["id"])
                if rid is None:
                    rid = next((r["id"] for r in epics[eid]["requirements"]
                                if r["title"].strip().lower() == card["name"].strip().lower()
                                and r["id"] not in card_map.values()), None)
                if rid is not None and reqs.get(rid, (None, None))[1] not in (None, eid):   # moved to another list
                    tls.delete_requirement(rid)
                    rid = None
                if rid is None:
                    rid = tls.add_requirement(eid, card["name"], description=desc, acceptance=acc, status=status)
                    rep["new"] += 1
                else:
                    r = reqs[rid][0] if rid in reqs else tls.requirement(rid) or {}
                    change = {k: v for k, v in (("title", card["name"]), ("description", desc), ("acceptance", acc),
                                                ("status", status)) if (r.get(k) or "") != v}
                    if change:
                        tls.update_requirement(rid, **change)
                        rep["changed"] += 1
                card_map[card["id"]] = rid
        for cid in [c for c in card_map if c not in seen_cards]:   # cards gone from the board
            if self.ctx.tasklists.requirement(card_map[cid]):
                tls.delete_requirement(card_map[cid])
                rep["deleted"] += 1
            card_map.pop(cid)
        for lid in [x for x in list_map if x not in seen_lists]:   # lists gone: their epic, if nothing else is in it
            epic = (tls.get(tid) or {"epics": []})["epics"]
            e = next((x for x in epic if x["id"] == list_map[lid]), None)
            if e is not None and not e["requirements"]:
                tls.delete_epic(e["id"])
                rep["epics_deleted"] += 1
            list_map.pop(lid)
        link.update(lists=list_map, cards=card_map)
        return rep

    # ---- Theron → Trello
    async def _write(self, tid: int, link: dict) -> dict:
        t = self.trello
        bid = link["board"]
        tl = self.ctx.tasklists.get(tid)
        if tl is None:
            raise TrelloError(self.ctx.tr("The task list doesn't exist any more."))
        lists = {x["id"]: x for x in await t.lists(bid)}
        cards = {c["id"]: c for c in await t.cards(bid)}
        labels = {lb["id"]: lb for lb in await t.labels(bid)}
        status_label = {}   # status → label id (created when needed)
        by_name = {(lb.get("name") or "").strip().lower(): lid for lid, lb in labels.items()}
        theirs = {lid for lid, lb in labels.items() if (lb.get("name") or "").strip().lower() in SYNONYMS}

        async def label_for(status: str) -> str | None:
            if status not in STATUS_LABELS:
                return None
            if status not in status_label:
                name, colour = STATUS_LABELS[status]
                lid = by_name.get(name.lower())
                if lid is None:
                    lid = (await t.add_label(bid, name, colour))["id"]
                    by_name[name.lower()] = lid
                theirs.add(lid)
                status_label[status] = lid
            return status_label[status]

        epic_list = {v: k for k, v in (link.get("lists") or {}).items()}      # epic → list
        req_card = {v: k for k, v in (link.get("cards") or {}).items()}       # requirement → card
        rep = {"lists_new": 0, "lists_changed": 0, "lists_archived": 0, "new": 0, "changed": 0, "archived": 0}
        epic_ids, req_ids = set(), set()
        for epic in tl["epics"]:
            epic_ids.add(epic["id"])
            lid = epic_list.get(epic["id"])
            if lid not in lists:
                lid = next((x["id"] for x in lists.values() if x["name"].strip().lower() == epic["name"].strip().lower()
                            and x["id"] not in epic_list.values()), None)
            if lid is None:
                new = await t.add_list(bid, epic["name"])
                lists[new["id"]] = new
                lid = new["id"]
                rep["lists_new"] += 1
            elif lists[lid]["name"] != epic["name"]:
                await t.update_list(lid, name=epic["name"])
                rep["lists_changed"] += 1
            epic_list[epic["id"]] = lid
            for req in epic["requirements"]:
                req_ids.add(req["id"])
                desc = card_text(req)
                status_id = await label_for(req.get("status") or "open")
                cid = req_card.get(req["id"])
                if cid not in cards:
                    cid = next((c["id"] for c in cards.values() if c["idList"] == lid
                                and c["name"].strip().lower() == req["title"].strip().lower()
                                and c["id"] not in req_card.values()), None)
                if cid is None:
                    new = await t.add_card(lid, req["title"], desc, [status_id] if status_id else [])
                    cards[new["id"]] = new
                    cid = new["id"]
                    rep["new"] += 1
                else:
                    card = cards[cid]
                    keep = [x for x in card.get("idLabels") or [] if x not in theirs]   # the user's own labels stay
                    want = keep + ([status_id] if status_id else [])
                    change = {}
                    if card["name"] != req["title"]:
                        change["name"] = req["title"]
                    if (card.get("desc") or "") != desc:
                        change["desc"] = desc
                    if card["idList"] != lid:
                        change["idList"] = lid
                    if sorted(card.get("idLabels") or []) != sorted(want):
                        change["idLabels"] = want
                    if change:
                        await t.update_card(cid, **change)
                        rep["changed"] += 1
                req_card[req["id"]] = cid
        for rid in [r for r in req_card if r not in req_ids]:   # requirements deleted in Theron: archive the card
            if req_card[rid] in cards:
                await t.update_card(req_card[rid], closed="true")
                rep["archived"] += 1
            req_card.pop(rid)
        for eid in [e for e in epic_list if e not in epic_ids]:  # epics deleted: archive their list
            if epic_list[eid] in lists:
                await t.update_list(epic_list[eid], closed="true")
                rep["lists_archived"] += 1
            epic_list.pop(eid)
        link.update(lists={v: k for k, v in epic_list.items()}, cards={v: k for k, v in req_card.items()})
        return rep

    def report_text(self, link: dict) -> str:
        r = link.get("report") or {}
        t = self.ctx.tr
        if link.get("direction") == "read":
            return t("Read from Trello: {new} new, {changed} changed, {deleted} removed requirements; {epics} new epics.",
                     new=r.get("new", 0), changed=r.get("changed", 0), deleted=r.get("deleted", 0),
                     epics=r.get("epics_new", 0))
        return t("Written to Trello: {new} new, {changed} changed, {archived} archived cards; {lists} new lists.",
                 new=r.get("new", 0), changed=r.get("changed", 0), archived=r.get("archived", 0),
                 lists=r.get("lists_new", 0))
