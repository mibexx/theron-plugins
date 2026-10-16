"""HTML → clean Markdown (standard library only): headings, paragraphs, lists (nested), links, pictures, emphasis,
code, quotes, tables."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "aside", "figure", "figcaption", "address",
         "details", "summary", "dl", "dt", "dd", "center", "hgroup", "body", "html", "nav"}
SKIP = {"script", "style", "noscript", "template", "head", "title", "svg", "button", "select", "option", "textarea"}
BR = "\x00BR\x00"
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "param", "track"}


class _Md(HTMLParser):
    def __init__(self, images: bool):
        super().__init__(convert_charrefs=True)
        self.images = images
        self.out: list[str] = []
        self.lists: list[list] = []          # [kind, counter]
        self.quote = 0
        self.pre = 0
        self.skip = 0
        self.links: list[str | None] = []
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.head_row = False

    # ------------------------------------------------------------------ output helpers
    def write(self, s: str) -> None:
        if self.cell is not None:
            self.cell.append(s)
        else:
            self.out.append(s)

    def close_mark(self, mark: str, opening: str | None = None) -> None:
        """Closes ``mark`` – or drops the opening one when nothing came in between (empty emphasis / link)."""
        buf = self.cell if self.cell is not None else self.out
        k = len(buf)
        while k and not buf[k - 1].strip() and buf[k - 1] != (opening or mark):
            k -= 1
        if k and buf[k - 1] == (opening or mark):
            del buf[k - 1:]
        else:
            buf.append(mark)

    def blank(self, n: int = 2) -> None:
        if self.cell is not None:
            self.cell.append(" ")
            return
        self.out.append("\n" * n)

    def prefix(self) -> str:
        return "> " * self.quote

    # ------------------------------------------------------------------ parser
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip or tag in SKIP:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.blank()
            self.write(self.prefix() + "#" * int(tag[1]) + " ")
        elif tag in BLOCK:
            self.blank()
        elif tag == "br":
            self.write(BR + self.prefix() if not self.pre else "\n")
        elif tag == "hr":
            self.blank()
            self.write("---")
            self.blank()
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag in ("s", "del", "strike"):
            self.write("~~")
        elif tag == "code" and not self.pre:
            self.write("`")
        elif tag == "code" and self.out and self.out[-1] == "```\n":
            m = re.search(r"(?:language|lang)-([\w+-]+)", a.get("class") or "")
            if m:
                self.out[-1] = f"```{m.group(1)}\n"
        elif tag == "pre":
            self.blank()
            lang = ""
            m = re.search(r"(?:language|lang)-([\w+-]+)", a.get("class") or "")
            if m:
                lang = m.group(1)
            self.write(f"```{lang}\n")
            self.pre += 1
        elif tag == "blockquote":
            self.blank()
            self.quote += 1
            self.write(self.prefix())
        elif tag in ("ul", "ol"):
            if not self.lists:
                self.blank()
            self.lists.append([tag, int(a.get("start") or 1) if tag == "ol" and (a.get("start") or "").isdigit()
                               else 1])
        elif tag == "li":
            depth = max(len(self.lists) - 1, 0)
            self.write("\n" + self.prefix() + "  " * depth)
            if self.lists and self.lists[-1][0] == "ol":
                self.write(f"{self.lists[-1][1]}. ")
                self.lists[-1][1] += 1
            else:
                self.write("- ")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            if href and not href.lower().startswith(("javascript:", "#")):
                self.write("[")
                self.links.append(href)
            else:
                self.links.append(None)
        elif tag == "img" and self.images:
            src = (a.get("src") or "").strip()
            if src:
                self.write(f"![{_inline(a.get('alt') or '')}]({src})")
        elif tag == "table":
            self.blank()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            if not self.table:
                self.table.append([])
            if tag == "th" and len(self.table) == 1:
                self.head_row = True
            self.cell = []

    def handle_endtag(self, tag):
        if self.skip:
            if tag in SKIP or tag not in VOID:
                self.skip -= 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") or tag in BLOCK:
            self.blank()
        elif tag in ("strong", "b"):
            self.close_mark("**")
        elif tag in ("em", "i"):
            self.close_mark("*")
        elif tag in ("s", "del", "strike"):
            self.close_mark("~~")
        elif tag == "code" and not self.pre:
            self.close_mark("`")
        elif tag == "pre" and self.pre:
            self.pre -= 1
            self.write("\n```")
            self.blank()
        elif tag == "blockquote" and self.quote:
            self.quote -= 1
            self.blank()
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            if not self.lists:
                self.blank()
        elif tag == "a" and self.links:
            href = self.links.pop()
            if href:
                self.close_mark(f"]({href})", "[")
        elif tag in ("td", "th") and self.cell is not None and self.table is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            self.cell = None
            self.table[-1].append(text)
        elif tag == "table" and self.table is not None:
            self.out.append(_table(self.table, self.head_row))
            self.table, self.head_row = None, False
            self.blank()

    def handle_data(self, data):
        if self.skip:
            return
        if self.pre:
            self.write(data)
            return
        text = re.sub(r"\s+", " ", data)
        if self.quote and self.cell is None:
            text = text.replace("\n", "\n" + self.prefix())
        self.write(_escape(text))


def _escape(text: str) -> str:
    return re.sub(r"([\\`*_])", r"\\\1", text)


def _inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("[", "(").replace("]", ")").strip()


def _table(rows: list[list[str]], head: bool) -> str:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if width == 1:   # layout table: just the text
        return "\n\n".join(r[0] for r in rows)
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n" + "\n".join(lines) + "\n"


def _tidy(text: str) -> str:
    text = re.sub(r"(?m)^[ \t]+(?![ \t]|(?:[-*]|\d+\.)[ \t])", "", text)   # stray indentation outside lists
    text = re.sub(r"(?<!!)\[[ \t\n]+", "[", text)
    text = re.sub(r"[ \t\n]+\]\(", "](", text)
    return re.sub(r"(?<=\S)[ \t]{2,}(?=[^\s\x00])", " ", text)


def _outside_code(text: str, fn) -> str:
    """``fn`` on everything but fenced code blocks."""
    parts = re.split(r"(```[^\n]*\n.*?\n```)", text, flags=re.S)
    return "".join(part if i % 2 else fn(part) for i, part in enumerate(parts))


def to_markdown(html: str, *, images: bool = False) -> str:
    p = _Md(images)
    p.feed(html or "")
    p.close()
    text = "".join(p.out)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = _outside_code(text, _tidy)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^[ \t>]*(?:[-*]|\d+\.)[ \t]*(?:\x00BR\x00[ \t]*)*$\n?", "", text)   # empty list items
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]*\x00BR\x00[ \t]*", "  \n", text.strip())
    return text.replace("\x00BR\x00", "") + "\n"
