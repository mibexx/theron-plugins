"""What the plugin shows in Theron's chat – all of it its own: ▶ players, the list of voices, the chosen voice, the
audio files. Theron only offers the hooks (``ctx.chat.add_renderer`` / ``add_format`` / ``link`` / ``on_link``)."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .api import label_text

CYAN, DIM, TEXT, LINE = "#5ce1ff", "#6f8c99", "#cdeff6", "#1f6f8b"

# an audio file in any chat text: /abs/path/x.mp3 or C:\path\x.mp3 – becomes a player when the file is there
AUDIO_PATH = re.compile(r"(?<![\w/\\])((?:/|[A-Za-z]:\\)[^\s<>\"'`|*?]+?\.(?:mp3|wav|ogg|m4a|flac))(?![\w])",
                        re.IGNORECASE)


class ChatView:
    def __init__(self, ctx, player):
        self.ctx, self.player = ctx, player

    def register(self) -> None:
        c = self.ctx.chat
        c.add_renderer("voices", self.voices)
        c.add_renderer("voice", self.voice)
        c.add_renderer("audio", self.audio_files)
        c.add_format(AUDIO_PATH, self.path_format)
        c.on_link("play", self.on_play)

    # ------------------------------------------------------------------ pieces
    def button(self, src: str, title: str = "") -> str:
        """▶ / ■ – a link the plugin handles itself (on_link "play")."""
        playing = bool(src) and self.player.playing() == src
        mark = "■" if playing else "▶"
        text = f"{mark} {title}" if title else mark
        link = self.ctx.chat.link("play", text, src=src)
        return link.replace("<a ", f'<a style="color:{CYAN}; text-decoration:none; font-weight:bold;" ', 1)

    def player_row(self, src: str, title: str, note: str = "") -> str:
        extra = f' <span style="color:{DIM}; font-size:11px;">{html.escape(note)}</span>' if note else ""
        return (f'<table cellspacing="0" cellpadding="0" style="margin:3px 0;"><tr>'
                f'<td style="background:#0b2a38; padding:4px 10px; border:1px solid {LINE};">'
                f'{self.button(src, title)}{extra}</td></tr></table>')

    # ------------------------------------------------------------------ renderers (data comes from node.say)
    def voices(self, data: dict) -> str:
        rows = []
        for i, v in enumerate(data.get("voices") or [], 1):
            sample = self.button(v["preview_url"], self.ctx.tr("Sample")) if v.get("preview_url") else ""
            desc = html.escape(v.get("description") or "")
            rows.append(
                f'<tr><td style="color:{CYAN}; padding:3px 8px 3px 0;" valign="top"><b>{i}</b></td>'
                f'<td style="padding:3px 10px 3px 0;" valign="top"><b style="color:{TEXT};">{html.escape(v["name"])}</b>'
                f'<br><span style="color:{DIM}; font-size:11px;">{html.escape(label_text(v))}</span>'
                + (f'<br><span style="font-size:11px;">{desc}</span>' if desc else "")
                + f'</td><td valign="top" style="padding:3px 0;">{sample}</td></tr>')
        head = html.escape(data.get("title") or "")
        return ((f'<p style="margin:2px 0 6px 0;">{head}</p>' if head else "")
                + f'<table cellspacing="0" cellpadding="0">{"".join(rows)}</table>')

    def voice(self, data: dict) -> str:
        v = data.get("voice") or {}
        why = data.get("reason") or ""
        out = (f'<p style="margin:2px 0;">🎙 <b style="color:{TEXT};">{html.escape(v.get("name", ""))}</b>'
               f' <span style="color:{DIM}; font-size:11px;">{html.escape(label_text(v))}</span></p>')
        if why:
            out += f'<p style="margin:2px 0; font-size:12px;">{html.escape(why)}</p>'
        if v.get("preview_url"):
            out += self.player_row(v["preview_url"], self.ctx.tr("Listen to the sample"))
        return out

    def audio_files(self, data: dict) -> str:
        rows = []
        for f in data.get("files") or []:
            note = f.get("note") or ""
            rows.append(self.player_row(f["path"], Path(f["path"]).name, note))
            if f.get("text"):
                rows.append(f'<p style="margin:0 0 6px 2px; color:{DIM}; font-size:11px;">'
                            f'{html.escape(_short(f["text"], 220))}</p>')
        head = html.escape(data.get("title") or "")
        return (f'<p style="margin:2px 0 4px 0;">{head}</p>' if head else "") + "".join(rows)

    def path_format(self, m: re.Match) -> str | None:
        path = m.group(1)
        if not Path(path).is_file():
            return None   # not (any more) there: plain text
        return (f'<span style="font-family:monospace; font-size:12px;">{html.escape(path)}</span> '
                + self.button(path))

    # ------------------------------------------------------------------ clicks
    def on_play(self, params: dict) -> None:
        src = params.get("src") or ""
        try:
            self.player.toggle(src)
        except Exception as exc:  # noqa: BLE001
            self.ctx.log.error(f"play {src}: {exc}")
            self.ctx.notify(self.ctx.tr("Can't play the audio: {error}", error=exc), "error")
            self.ctx.chat.refresh()


def _short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"
