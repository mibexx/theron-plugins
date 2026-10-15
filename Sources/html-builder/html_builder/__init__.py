"""HTML Builder for Theron: 🧱 Build HTML as a process node – one clean, self-contained HTML document per run, from
a description of its content, optionally for an audience, in a style / CI and after a template of your template folder.
The document shows up in the chat with “Open in the browser” (theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

import html
from pathlib import Path

from .node import HtmlNode

CYAN, DIM, TEXT, LINE, AMBER = "#5ce1ff", "#6f8c99", "#cdeff6", "#1f6f8b", "#ffb547"


def register(ctx):
    HtmlNode(ctx).register()
    tr = ctx.tr

    def link(action: str, text: str, path: str) -> str:
        a = ctx.chat.link(action, text, path=path)
        return a.replace("<a ", f'<a style="color:{CYAN}; text-decoration:none; font-weight:bold;" ', 1)

    def card(data: dict) -> str:
        path = data.get("path") or ""
        there = Path(path).is_file()
        size = data.get("size") or 0
        meta = [f"{max(1, round(size / 1024))} KB"] + ([tr("template: {name}", name=data["template"])]
                                                       if data.get("template") else [])
        actions = (link("open", "↗ " + tr("Open in the browser"), path) + " &nbsp; "
                   + link("folder", "📂 " + tr("Show folder"), path)) if there else \
            f'<span style="color:{DIM};">{html.escape(tr("The file is gone."))}</span>'
        warn = "".join(f'<br><span style="color:{AMBER}; font-size:11px;">⚠ {html.escape(w)}</span>'
                       for w in data.get("warnings") or [])
        return (f'<table cellspacing="0" cellpadding="0" style="margin:3px 0;"><tr>'
                f'<td style="background:#0b2a38; padding:6px 12px; border:1px solid {LINE};">'
                f'🧱 <b style="color:{TEXT};">{html.escape(data.get("title") or Path(path).name)}</b>'
                f' <span style="color:{DIM}; font-size:11px;">{html.escape(" · ".join(meta))}</span><br>'
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

    ctx.chat.add_renderer("html", card)
    ctx.chat.on_link("open", open_file)
    ctx.chat.on_link("folder", open_folder)
