"""The process node 🛰 Scrape pages (Bright Data Web Unlocker) – same contract as the Chrome Scraper's node: URLs in,
pages out. ``hand_on`` is shared with the Browser API node."""

from __future__ import annotations

import asyncio
import html as _html
import re
from pathlib import Path

from .api import Client, UnlockError, explain, redirect_target

HANDOVER = 11_800   # Theron passes a plugin's hand-over on with at most 12,000 characters
URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
TAGS = re.compile(r"<(script|style|noscript)\b.*?</\1>|<[^>]+>", re.I | re.S)


def urls_in(text: str) -> list[str]:
    """The URLs of a hand-over – the ``URLS:`` block (Google SERP / Search) if there is one, else every http(s) link."""
    m = re.search(r"^URLS:\s*\n((?:\s*https?://\S+\s*\n?)+)", text or "", re.M)
    found = URL.findall(m.group(1) if m else text or "")
    out, seen = [], set()
    for u in found:
        u = u.rstrip(".,;:!?»”’")
        key = u.rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def title_of(body: str, markdown: bool) -> str:
    if markdown:
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""
    m = TITLE.search(body)
    return " ".join(_html.unescape(m.group(1)).split()) if m else ""


def text_of(body: str, markdown: bool) -> str:
    return body if markdown else " ".join(_html.unescape(TAGS.sub(" ", body)).split())


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].strip("-") or "page"


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        p = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not p.exists():
            return p
    return path


class ScrapeNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "scrape", label="Web Unlocker (Bright Data)", icon="🛰", run=self.run,
            description="Loads the URLs it gets (e.g. from Google Search) through Bright Data's Web Unlocker – past "
                        "bot protection and CAPTCHAs – and hands on their content as Markdown or raw HTML; files in "
                        "the project's folder.",
            ai_hint="Scrape web pages via Bright Data Web Unlocker (paid per page, gets past bot protection; no JavaScript clicks): loads the URLs of the "
                    "incoming text (the URLS: block, else every link; or the node's list) and hands on the page "
                    "content as Markdown or raw HTML. Outputs: pages, error (nothing could be loaded).",
            outputs=[{"id": "pages", "label": tr("Pages"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "format", "type": "choice", "label": "Format", "default": "markdown",
                 "options": [{"value": "markdown", "label": "Markdown – converted by Bright Data"},
                             {"value": "html", "label": "Raw HTML"}]},
                {"key": "urls", "type": "textarea", "label": "URLs (optional)",
                 "description": "One per line. Empty: the URLs of the input (the URLS: list of Google Search / SERP, "
                                "else every link in it)."},
                {"key": "max_pages", "type": "number", "label": "At most pages", "default": 10,
                 "description": "0 = all. Every page loaded is one billed request."},
                {"key": "country", "type": "text", "label": "Country (optional)",
                 "description": "Two letters like de, at, us. Empty: the setting."},
                {"key": "folder", "type": "text", "label": "Folder", "default": "scraped",
                 "description": "Where the files go – relative to the project's workspace. Empty: no files."},
                {"key": "handover", "type": "choice", "label": "Hand on", "default": "content",
                 "options": [{"value": "content", "label": "The content (cut at the limit below)"},
                             {"value": "files", "label": "Only titles and file paths"}]},
                {"key": "max_chars", "type": "number", "label": "Characters per page", "default": 0,
                 "show_if": {"handover": "content"},
                 "description": "0 = an equal share: Theron hands on about 12,000 characters in all, so longer pages "
                                "are cut – the files always have everything (an agent behind can read them)."},
            ])

    # ------------------------------------------------------------------ run
    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        s = self.ctx.settings
        urls = urls_in(cfg.get("urls") or "") or urls_in(node.input or "") or urls_in(node.task or "")
        urls = list(dict.fromkeys(await asyncio.gather(*(asyncio.to_thread(redirect_target, u) for u in urls))))   # Google's /goto links → the pages
        limit = int(cfg.get("max_pages") or 0)
        skipped = urls[limit:] if limit > 0 else []
        urls = urls[:limit] if limit > 0 else urls
        if not urls:
            return node.route("error", tr("No URLs in the input – put Google Search before this node or list them "
                                          "in the node."))
        try:
            client = Client(self.ctx.http, s.get("api_key") or "", s.get("zone") or "",
                            timeout=float(s.get("timeout") or 120), limit=int(s.get("parallel") or 5))
        except UnlockError as exc:
            return node.route("error", str(exc))
        markdown = (cfg.get("format") or "markdown") == "markdown"
        country = (cfg.get("country") or s.get("country") or "").strip()
        render = bool(s.get("render"))
        sem = asyncio.Semaphore(max(1, min(int(s.get("parallel") or 5), 20)))
        results: dict[str, dict] = {}
        fatal: list[UnlockError] = []
        done = [0]

        async def one(url: str) -> None:
            async with sem:
                if fatal:   # the key or the zone is wrong: don't send the rest
                    results[url] = {"url": url, "error": str(fatal[0])}
                    return
                try:
                    page = await client.unlock(url, markdown=markdown, country=country, render=render)
                except UnlockError as exc:
                    if exc.kind in ("invalid_key", "no_zone", "quota"):
                        fatal.append(exc)
                    results[url] = {"url": url, "error": str(exc)}
                else:
                    body = page["body"]
                    r = {"url": url, "title": title_of(body, markdown), "text": text_of(body, markdown),
                         "markdown": body if markdown else "", "raw": "" if markdown else body}
                    if page.get("code", "").startswith("policy") or (page["status"] >= 400 and len(r["text"]) < 500):
                        r["error"] = explain(page["status"], page.get("why", ""), page.get("code", ""))
                    elif not body.strip():
                        r["error"] = tr("empty page")
                    results[url] = r
                done[0] += 1
                node.progress(tr("🛰 {n} of {total} pages", n=done[0], total=len(urls)))

        node.progress(tr("loads {n} pages through Bright Data …", n=len(urls)))
        await asyncio.gather(*(one(u) for u in urls))
        return self.hand_on(node, urls, results, skipped)

    # ------------------------------------------------------------------ results
    def folder(self, node) -> Path | None:
        sub = (node.config.get("folder") or "").strip()
        if not sub:
            return None
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else Path(self.ctx.data_dir)
        target = Path(sub).expanduser() if Path(sub).expanduser().is_absolute() else base / sub
        target.mkdir(parents=True, exist_ok=True)
        return target

    def hand_on(self, node, urls: list[str], results: dict[str, dict], skipped: list[str], *,
                markdown: bool | None = None, kind: str = "", via: str = "Bright Data", icon: str = "🛰"):
        tr = self.ctx.tr
        cfg = node.config
        if markdown is None:
            markdown = (cfg.get("format") or "markdown") == "markdown"
        ok = [results[u] for u in urls if not results[u].get("error")]
        bad = [results[u] for u in urls if results[u].get("error")]
        folder = self.folder(node)
        limit = int(cfg.get("max_chars") or 0)
        parts, files, chat = [], [], []
        for i, r in enumerate(ok, 1):
            title = (r.get("title") or r["url"]).strip()
            saved = []
            if folder:
                stem = f"{node.run_id:04d}-{i:02d}-{slug(title)}"
                if markdown:
                    p = unique(folder / f"{stem}.md")
                    p.write_text(f"# {title}\n\nSource: {r['url']}\n\n{r['markdown']}", encoding="utf-8")
                else:
                    p = unique(folder / f"{stem}.html")
                    p.write_text(r["raw"], encoding="utf-8")
                saved.append(str(p))
            files += saved
            chat.append(f"{i}. [{title.replace('[', '(').replace(']', ')')}]({r['url']})"
                        + (f" – `{Path(saved[0]).name}`" if saved else ""))
            head = f"## {i}. {title}\nURL: {r['url']}" + ("\nFiles: " + ", ".join(saved) if saved else "")
            if cfg.get("handover") == "files" and saved:
                preview = " ".join((r.get("text") or "").split())[:300]
                parts.append((head, f"{preview}…" if preview else ""))
                continue
            parts.append((head, r["markdown"] if markdown else r["raw"]))
        failed = [f"- {r['url']} – {r['error']}" for r in bad] + \
                 [f"- {u} – " + tr("over the limit of the node") for u in skipped]
        node.say(text=tr("{icon} **{ok} of {total} pages** loaded through {via}", icon=icon, ok=len(ok),
                         total=len(urls), via=via)
                 + ("\n\n" + "\n".join(chat) if chat else "")
                 + ("\n\n" + tr("Not loaded:") + "\n" + "\n".join(failed) if failed else ""))
        if not ok:
            return node.route("error", tr("No page could be loaded:") + "\n" + "\n".join(failed))
        kind = kind or ("Markdown" if markdown else "HTML")
        # Theron passes at most HANDOVER characters on: the file list and what failed first, then the pages –
        # each cut to its share (the files always have everything)
        text = tr("{ok} of {total} pages loaded ({kind}):", ok=len(ok), total=len(urls), kind=kind)
        if files:
            text += "\n\nFILES:\n" + "\n".join(files)
        if failed:
            text += "\n\n" + tr("Not loaded:") + "\n" + "\n".join(failed)
        note = "\n\n" + tr("[… cut after {n} characters – the whole page is in the file]", n="{n}")
        room = HANDOVER - len(text) - sum(len(h) + 12 for h, _ in parts)
        share = max(200, room // max(len(parts), 1) - len(note))
        cap = min(limit, share) if limit else share
        for head, body in parts:
            if len(body) > cap:
                body = body[:cap].rstrip() + note.replace("{n}", f"{cap:,}")
            text += "\n\n---\n\n" + head + (f"\n\n{body}" if body else "")
        return node.route("pages", text[:HANDOVER])
