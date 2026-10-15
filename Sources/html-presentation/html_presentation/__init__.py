"""HTML Presentation for Theron: 📽 Build presentation as a process node – one presentation per run as ONE HTML file:
always one 16:9 slide, as large as the screen allows; optionally multilingual (switch), light / dark / both (switch),
slide cursor top / bottom, arrow keys. The presentation shows in the chat with “Present” (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

import html
from pathlib import Path

from .node import PresentationNode

CYAN, DIM, TEXT, LINE, AMBER = "#5ce1ff", "#6f8c99", "#cdeff6", "#1f6f8b", "#ffb547"


def register(ctx):
    PresentationNode(ctx).register()
    tr = ctx.tr

    def link(action: str, text: str, path: str) -> str:
        a = ctx.chat.link(action, text, path=path)
        return a.replace("<a ", f'<a style="color:{CYAN}; text-decoration:none; font-weight:bold;" ', 1)

    def card(data: dict) -> str:
        path = data.get("path") or ""
        there = Path(path).is_file()
        theme = {"light": tr("light"), "dark": tr("dark"), "both": tr("light / dark")}.get(data.get("theme"), "")
        meta = [tr("{n} slides", n=data.get("slides") or 0), " · ".join(data.get("languages") or []), theme,
                tr("cursor {where}", where=tr("top") if data.get("cursor") == "top" else tr("bottom")),
                tr("arrow keys") if data.get("arrows") else ""]
        if data.get("template"):
            meta.append(tr("template: {name}", name=data["template"]))
        actions = (link("open", "▶ " + tr("Present"), path) + " &nbsp; " + link("folder", "📂 " + tr("Show folder"), path)
                   ) if there else f'<span style="color:{DIM};">{html.escape(tr("The file is gone."))}</span>'
        warn = "".join(f'<br><span style="color:{AMBER}; font-size:11px;">⚠ {html.escape(w)}</span>'
                       for w in data.get("warnings") or [])
        return (f'<table cellspacing="0" cellpadding="0" style="margin:3px 0;"><tr>'
                f'<td style="background:#0b2a38; padding:6px 12px; border:1px solid {LINE};">'
                f'📽 <b style="color:{TEXT};">{html.escape(data.get("title") or Path(path).stem)}</b><br>'
                f'<span style="color:{DIM}; font-size:11px;">{html.escape(" · ".join(m for m in meta if m))}</span><br>'
                f'<span style="font-family:monospace; font-size:11px; color:{DIM};">{html.escape(path)}</span><br>'
                f'{actions}{warn}</td></tr></table>')

    def open_file(params: dict) -> None:
        p = Path(params.get("path") or "")
        if p.is_file():
            ctx.ui.open_url(p.as_uri())
        else:
            ctx.notify(tr("The file is gone: {path}", path=str(p)), "error")

    def open_folder(params: dict) -> None:
        p = Path(params.get("path") or "").parent
        if p.is_dir():
            ctx.ui.open_url(p.as_uri())

    ctx.chat.add_renderer("presentation", card)
    ctx.chat.on_link("open", open_file)
    ctx.chat.on_link("folder", open_folder)
