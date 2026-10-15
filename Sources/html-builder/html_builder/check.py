"""Is the HTML clean? A small checker on the standard library's parser – what a browser forgives, but a clean
document doesn't have: no doctype, no charset, no title, unclosed or stray tags, images without alt, an empty body …

``check(text)`` → (errors, warnings): errors make the document unusable (the node asks the AI to fix it, then goes
to “Error”), warnings are fixed once if possible and otherwise named in the hand-over.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# closed implicitly by the next sibling or the parent – a missing end tag is fine (HTML spec, "optional tags")
OPTIONAL_END = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup", "colgroup",
                "rt", "rp", "caption", "html", "head", "body"}
RAW = {"script", "style"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doctype = ""
        self.stack: list[str] = []
        self.unclosed: list[str] = []
        self.stray: list[str] = []
        self.seen: dict[str, int] = {}
        self.attrs: list[tuple[str, dict]] = []
        self.title = ""
        self.body_text = 0
        self._in = ""

    def handle_decl(self, decl):
        self.doctype = decl

    def handle_starttag(self, tag, attrs):
        self.seen[tag] = self.seen.get(tag, 0) + 1
        self.attrs.append((tag, {k: (v or "") for k, v in attrs}))
        if tag not in VOID:
            self.stack.append(tag)
        if tag in ("title",) or tag in RAW:
            self._in = tag

    def handle_startendtag(self, tag, attrs):
        self.seen[tag] = self.seen.get(tag, 0) + 1
        self.attrs.append((tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self._in == tag:
            self._in = ""
        if tag not in self.stack:
            if tag not in OPTIONAL_END:
                self.stray.append(tag)
            return
        while self.stack:   # close what is still open inside – only optional end tags may be left out
            top = self.stack.pop()
            if top == tag:
                break
            if top not in OPTIONAL_END:
                self.unclosed.append(top)

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif not self._in and "body" in self.stack:
            self.body_text += len(data.strip())


def check(text: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    src = (text or "").strip()
    if not src:
        return ["the file is empty"], []
    if src.startswith("```") or src.endswith("```"):
        errors.append("the file has Markdown code fences (```) around the HTML")
    p = _Parser()
    try:
        p.feed(src)
        p.close()
    except Exception as exc:  # noqa: BLE001 - the parser is forgiving; this is really broken
        return [f"the HTML can't be parsed: {exc}"], []
    unclosed = p.unclosed + [t for t in p.stack if t not in OPTIONAL_END]
    if "html" not in p.seen:
        errors.append("no <html> element")
    if "body" not in p.seen:
        errors.append("no <body> element")
    elif p.body_text == 0 and not any(t in p.seen for t in ("img", "svg", "canvas", "video", "iframe")):
        errors.append("the <body> is empty")
    if unclosed:
        errors.append("unclosed tags: " + _few([f"<{t}>" for t in unclosed]))
    if p.stray:
        errors.append("end tags without a start tag: " + _few([f"</{t}>" for t in p.stray]))
    if p.doctype.lower().strip() != "doctype html":
        warnings.append("no <!DOCTYPE html> at the top")
    if "head" not in p.seen:
        warnings.append("no <head>")
    metas = [a for t, a in p.attrs if t == "meta"]
    if not any("charset" in m or m.get("http-equiv", "").lower() == "content-type" for m in metas):
        warnings.append('no <meta charset="utf-8">')
    if not any(m.get("name", "").lower() == "viewport" for m in metas):
        warnings.append("no viewport meta tag (phones show it zoomed out)")
    if not p.title.strip():
        warnings.append("no <title>")
    if not any(t == "html" and a.get("lang") for t, a in p.attrs):
        warnings.append("no lang attribute on <html>")
    no_alt = sum(1 for t, a in p.attrs if t == "img" and "alt" not in a)
    if no_alt:
        warnings.append(f"{no_alt} image(s) without alt text")
    if "h1" not in p.seen and "body" in p.seen:
        warnings.append("no <h1> heading")
    if p.seen.get("h1", 0) > 1:
        warnings.append(f"{p.seen['h1']} <h1> headings (one is clean)")
    if any(re.match(r"(?i)file:", a.get("src", "") + a.get("href", "")) for _, a in p.attrs):
        warnings.append("file:// links (they only work on this computer)")
    return errors, warnings


def title_of(text: str) -> str:
    p = _Parser()
    try:
        p.feed(text or "")
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(p.title.split())


def _few(items: list[str], n: int = 6) -> str:
    out = list(dict.fromkeys(items))
    return ", ".join(out[:n]) + (" …" if len(out) > n else "")
