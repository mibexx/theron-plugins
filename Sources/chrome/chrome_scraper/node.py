"""The process node 🌐 Scrape pages and the browser it shares between runs."""

from __future__ import annotations

import asyncio
import random
import re
import time
from pathlib import Path

from .cdp import Browser, CdpError, find_browser, has_display
from .claude_chrome import ClaudeChrome, unavailable
from .scraper import Page, accept_language, host_of, urls_in

MODES = ("headless", "window", "visible")
HANDOVER = 11_800   # Theron passes a plugin's hand-over on with at most 12,000 characters


class Pool:
    """One browser for all nodes of the plugin (one profile can't be opened twice); it closes when idle."""

    IDLE = 45

    def __init__(self, ctx):
        self.ctx = ctx
        self.browser: Browser | None = None
        self.mode = ""
        self.users = 0
        self.changed = asyncio.Condition()
        self.closer = None
        self.hosts: dict[str, asyncio.Lock] = {}
        self.last: dict[str, float] = {}

    def profile(self) -> Path:
        return Path(self.ctx.data_dir) / "profile"

    def path(self) -> str:
        return find_browser(self.ctx.settings.get("browser") or "")

    def lang(self) -> str:
        return accept_language(self.ctx.settings.get("language") or "")

    async def acquire(self, mode: str) -> Browser:
        mode = mode if has_display() else "headless"
        async with self.changed:
            while self.browser and self.mode != mode and self.users:
                await self.changed.wait()
            if self.closer:
                self.closer.cancel()
                self.closer = None
            if self.browser and (self.mode != mode or self.browser.proc is None or self.browser.proc.poll() is not None):
                await self.browser.stop()
                self.browser = None
            if self.browser is None:
                path = self.path()
                if not path:
                    raise CdpError("No Chrome found – install Google Chrome (or Chromium / Edge / Brave) or enter "
                                   "its path in Settings → Plugins → Chrome.")
                lang = (self.ctx.settings.get("language") or "").split(",")[0].strip()
                b = Browser(path, self.profile(), headless=mode == "headless",
                            window="offscreen" if mode == "window" else "normal", language=lang)
                await b.start()
                self.browser, self.mode = b, mode
            self.users += 1
            return self.browser

    async def release(self) -> None:
        async with self.changed:
            self.users -= 1
            self.changed.notify_all()
            if not self.users and self.browser:
                self.closer = asyncio.ensure_future(self._close_later())

    async def _close_later(self) -> None:
        await asyncio.sleep(self.IDLE)
        async with self.changed:
            browser = self.browser
            if not self.users and browser:
                self.browser, self.closer = None, None
                await browser.stop()

    async def shutdown(self) -> None:
        if self.closer:
            self.closer.cancel()
            self.closer = None
        browser, self.browser = self.browser, None
        if browser:
            await browser.stop()

    async def polite(self, url: str, pause: float) -> asyncio.Lock:
        """One page per site at a time, with a pause like a person reading."""
        host = host_of(url)
        lock = self.hosts.setdefault(host, asyncio.Lock())
        await lock.acquire()
        wait = self.last.get(host, 0) + pause * random.uniform(0.7, 1.5) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        return lock

    def done(self, url: str, lock: asyncio.Lock) -> None:
        self.last[host_of(url)] = time.monotonic()
        lock.release()


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
    def __init__(self, ctx, pool: Pool):
        self.ctx, self.pool = ctx, pool

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "scrape", label="Scrape pages", icon="🌐", run=self.run,
            description="Opens the URLs it gets (e.g. from Google SERP) in your own Chrome – behaving like a person – "
                        "and hands on their content as clean Markdown or as raw HTML; files in the project's folder.",
            ai_hint="Scrape web pages: loads the URLs of the incoming text (or the node's list) in a real Chrome and "
                    "hands on the page content as Markdown or raw HTML. Outputs: pages, error (nothing could be "
                    "loaded, e.g. all blocked by bot protection).",
            outputs=[{"id": "pages", "label": tr("Pages"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "browser", "type": "choice", "label": "Browser", "default": "own",
                 "options": [{"value": "own", "label": "Own Chrome (headless / window, settings of the plugin)"},
                             {"value": "claude", "label": "Claude in Chrome – your Chrome (desktop only)"}],
                 "description": "Claude in Chrome loads the pages in your own Chrome with the Claude extension – your "
                                "cookies and logins, a real browser. Slower (one page after the other) and it uses "
                                "your Claude usage; needs Theron 0.25+."},
                {"key": "format", "type": "choice", "label": "Format", "default": "markdown",
                 "options": [{"value": "markdown", "label": "Markdown – the clean content"},
                             {"value": "html", "label": "Raw HTML"},
                             {"value": "both", "label": "Both"}]},
                {"key": "content", "type": "choice", "label": "Content", "default": "main",
                 "show_if": {"format": ["markdown", "both"], "browser": ["own", None, ""]},
                 "options": [{"value": "main", "label": "Main content – without menus, footer, cookie banners"},
                             {"value": "full", "label": "Whole page"}]},
                {"key": "images", "type": "bool", "label": "Pictures as links", "default": False,
                 "show_if": {"format": ["markdown", "both"], "browser": ["own", None, ""]}},
                {"key": "html_source", "type": "choice", "label": "HTML", "default": "rendered",
                 "show_if": {"format": ["html", "both"], "browser": ["own", None, ""]},
                 "options": [{"value": "rendered", "label": "As rendered (after JavaScript)"},
                             {"value": "original", "label": "As the server sent it"}]},
                {"key": "urls", "type": "textarea", "label": "URLs (optional)",
                 "description": "One per line. Empty: the URLs of the input (the URLS: list of Google SERP, else "
                                "every link in it)."},
                {"key": "max_pages", "type": "number", "label": "At most pages", "default": 10,
                 "description": "0 = all."},
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
        urls = urls_in(cfg.get("urls") or "") or urls_in(node.input or "") or urls_in(node.task or "")
        limit = int(cfg.get("max_pages") or 0)
        skipped = urls[limit:] if limit > 0 else []
        urls = urls[:limit] if limit > 0 else urls
        if not urls:
            return node.route("error", tr("No URLs in the input – put Google SERP before this node or list them in "
                                          "the node."))
        if cfg.get("browser") == "claude":
            return await self.run_claude(node, urls, skipped)
        s = self.ctx.settings
        mode = s.get("mode") or "headless"
        parallel = max(1, min(int(s.get("parallel") or 3), 8))
        results: dict[str, dict] = {}
        done = [0]

        async def batch(todo: list[str], mode: str, browser) -> None:
            sem = asyncio.Semaphore(parallel)

            async def one(url):
                async with sem:
                    results[url] = await self.scrape(browser, url, cfg)
                    done[0] += 1
                    node.progress(tr("🌐 {n} of {total} pages", n=done[0], total=len(urls)))
            await asyncio.gather(*(one(u) for u in todo))

        node.progress(tr("starts Chrome …"))
        try:
            browser = await self.pool.acquire(mode)
        except CdpError as exc:
            return node.route("error", tr("Chrome: {error}", error=exc))
        try:
            await batch(urls, mode, browser)
        finally:
            await self.pool.release()

        blocked = [u for u in urls if results[u].get("blocked")]
        if blocked and mode == "headless" and s.get("retry_window", True) and has_display():
            node.progress(tr("tries {n} blocked pages in a real window …", n=len(blocked)))
            done[0] -= len(blocked)
            try:
                browser = await self.pool.acquire("window")
                try:
                    await batch(blocked, "window", browser)
                finally:
                    await self.pool.release()
            except CdpError as exc:
                self.ctx.log.error(f"window retry: {exc}")
            blocked = [u for u in urls if results[u].get("blocked")]
        if blocked and s.get("ask_user", True) and has_display():
            for url in blocked:
                results[url] = await self.by_hand(node, url, cfg, results[url])

        return self.hand_on(node, urls, results, skipped)

    async def run_claude(self, node, urls: list[str], skipped: list[str]):
        tr = self.ctx.tr
        why = unavailable(self.ctx)
        if why:
            return node.route("error", why)
        node.progress(tr("Claude in Chrome …"))
        results = await ClaudeChrome(self.ctx).run(
            node, urls, node.config,
            lambda n: node.progress(tr("🌐 {n} of {total} pages", n=n, total=len(urls)) + " · Claude in Chrome"))
        return self.hand_on(node, urls, results, skipped)

    async def scrape(self, browser, url: str, cfg: dict) -> dict:
        r = await self._scrape(browser, url, cfg)
        if "Session with given id not found" in (r.get("error") or "") or "No target with given id" in \
                (r.get("error") or ""):
            r = await self._scrape(browser, url, cfg)   # the tab went away under us (first window start): once more
        return r

    async def _scrape(self, browser, url: str, cfg: dict) -> dict:
        s = self.ctx.settings
        lock = await self.pool.polite(url, float(s.get("pause") or 2))
        page = None
        try:
            page = await Page.open(browser, self.pool.lang())
            await page.load(url)
            found = await page.wait_out(float(s.get("challenge_wait") or 20))
            if found:
                return {"url": url, "blocked": found, "error": self.ctx.tr("blocked by bot protection ({name})",
                                                                            name=found)}
            mime = page.doc.get("mime") or ""
            if mime and "html" not in mime and not mime.startswith("text/"):
                return {"url": url, "error": self.ctx.tr("not a web page ({mime})", mime=mime)}
            await page.wander()
            fmt = cfg.get("format") or "markdown"
            data = await page.content(main=(cfg.get("content") or "main") == "main", images=bool(cfg.get("images")),
                                      original=fmt in ("html", "both") and cfg.get("html_source") == "original")
            if (page.doc.get("status") or 200) >= 400 and len(data.get("text") or "") < 500:
                return {"url": url, "error": f"HTTP {page.doc['status']}", **data}
            return {"url": url, **data}
        except (CdpError, asyncio.TimeoutError, OSError) as exc:
            return {"url": url, "error": str(exc) or exc.__class__.__name__}
        finally:
            if page:
                await page.close()
            self.pool.done(url, lock)

    async def by_hand(self, node, url: str, cfg: dict, before: dict) -> dict:
        """The page stays blocked: show it in a Chrome window and let the user get past the check."""
        tr = self.ctx.tr
        try:
            browser = await self.pool.acquire("window")
        except CdpError:
            return before
        page = None
        try:
            page = await Page.open(browser, self.pool.lang())
            await page.load(url)
            if not await page.challenged():
                return await self._take(page, url, cfg)
            await browser.show(page.s.target_id)
            answer = await node.ask(
                tr("{url} is protected by a bot check ({name}). Please solve it in the Chrome window that just "
                   "opened, then answer “Done”.", url=url, name=before.get("blocked") or "?"),
                [tr("Done"), tr("Skip")], recommended=1)
            if answer.strip().lower() in (tr("Skip").lower(), "skip", "überspringen"):
                return before
            await page.settle()
            found = await page.wait_out(10)
            if found:
                return before
            return await self._take(page, url, cfg)
        except (CdpError, asyncio.TimeoutError, OSError) as exc:
            return {**before, "error": f"{before.get('error')} · {exc}"}
        finally:
            if page:
                await page.close()
            await self.pool.release()

    async def _take(self, page, url, cfg) -> dict:
        fmt = cfg.get("format") or "markdown"
        data = await page.content(main=(cfg.get("content") or "main") == "main", images=bool(cfg.get("images")),
                                  original=fmt in ("html", "both") and cfg.get("html_source") == "original")
        return {"url": url, **data}

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

    def hand_on(self, node, urls: list[str], results: dict[str, dict], skipped: list[str]):
        tr = self.ctx.tr
        cfg = node.config
        fmt = cfg.get("format") or "markdown"
        ok = [results[u] for u in urls if not results[u].get("error")]
        bad = [results[u] for u in urls if results[u].get("error")]
        folder = self.folder(node)
        limit = int(cfg.get("max_chars") or 0)
        parts, files, chat = [], [], []
        for i, r in enumerate(ok, 1):
            title = (r.get("title") or r["url"]).strip()
            md = f"# {title}\n\nSource: {r.get('final_url') or r['url']}\n\n{r.get('markdown') or ''}"
            saved = []
            if folder:
                stem = f"{node.run_id:04d}-{i:02d}-{slug(title)}"
                if fmt in ("markdown", "both"):
                    p = unique(folder / f"{stem}.md")
                    p.write_text(md, encoding="utf-8")
                    saved.append(str(p))
                if fmt in ("html", "both"):
                    p = unique(folder / f"{stem}.html")
                    p.write_text(r.get("raw") or "", encoding="utf-8")
                    saved.append(str(p))
            r["files"] = saved
            files += saved
            chat.append(f"{i}. [{title.replace('[', '(').replace(']', ')')}]({r.get('final_url') or r['url']})"
                        + (f" – `{Path(saved[0]).name}`" if saved else ""))
            head = f"## {i}. {title}\nURL: {r.get('final_url') or r['url']}" + \
                   ("\nFiles: " + ", ".join(saved) if saved else "")
            if cfg.get("handover") == "files" and saved:
                preview = " ".join((r.get("text") or "").split())[:300]
                parts.append((head, f"{preview}…" if preview else ""))
                continue
            parts.append((head, r.get("markdown") if fmt in ("markdown", "both") else r.get("raw") or ""))
        failed = [f"- {r['url']} – {r['error']}" for r in bad] + \
                 [f"- {u} – " + tr("over the limit of the node") for u in skipped]
        node.say(text=tr("🌐 **{ok} of {total} pages** scraped", ok=len(ok), total=len(urls))
                 + ("\n\n" + "\n".join(chat) if chat else "")
                 + ("\n\n" + tr("Not scraped:") + "\n" + "\n".join(failed) if failed else ""))
        if not ok:
            return node.route("error", tr("No page could be loaded:") + "\n" + "\n".join(failed))
        kind = {"markdown": "Markdown", "html": "HTML", "both": "Markdown + HTML"}[fmt]
        # Theron passes at most HANDOVER characters on: the file list and what failed first, then the pages –
        # each cut to its share (the files always have everything)
        text = tr("{ok} of {total} pages scraped ({kind}):", ok=len(ok), total=len(urls), kind=kind)
        if files:
            text += "\n\nFILES:\n" + "\n".join(files)
        if failed:
            text += "\n\n" + tr("Not scraped:") + "\n" + "\n".join(failed)
        note = "\n\n" + tr("[… cut after {n} characters – the whole page is in the file]", n="{n}")
        room = HANDOVER - len(text) - sum(len(h) + 12 for h, _ in parts)
        share = max(200, room // max(len(parts), 1) - len(note))
        cap = min(limit, share) if limit else share
        for head, body in parts:
            if len(body) > cap:
                body = body[:cap].rstrip() + note.replace("{n}", f"{cap:,}")
            text += "\n\n---\n\n" + head + (f"\n\n{body}" if body else "")
        return node.route("pages", text[:HANDOVER])
