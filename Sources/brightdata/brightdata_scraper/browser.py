"""The process node 🖥 Browser API (Bright Data): every URL in a real Chrome at Bright Data – JavaScript runs, CAPTCHAs
are solved there – and the rendered page goes on, the same contract as the other scrape nodes.

The Browser API is a remote Chrome spoken to over the Chrome DevTools Protocol (wss://brd.superproxy.io:9222, the
zone's username and password). No Playwright needed: a small CDP client over ``websockets`` (part of Theron). One
browser session per URL – Bright Data allows one domain per session. Billed by traffic (≈ $8 per GB), so images, fonts
and videos are not loaded unless the node asks for them."""

from __future__ import annotations

import asyncio
import base64
import itertools
import json

from .node import ScrapeNode, urls_in

ENDPOINT = "wss://brd.superproxy.io:9222"
COST = "≈ $8 per GB pay as you go, ≈ $7 per GB on the Scale plan ($499/month for 71 GB); 1 GB free per month"
BLOCK = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.avif", "*.svg", "*.ico", "*.woff", "*.woff2", "*.ttf",
         "*.otf", "*.mp4", "*.webm", "*.mp3"]
EXTRACT = ("JSON.stringify({title: document.title, url: location.href, html: document.documentElement.outerHTML, "
           "text: document.body ? document.body.innerText : ''})")


class BrowserError(RuntimeError):
    """``kind``: "no_auth", "invalid_auth", "quota", "network", "navigate", "other"."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class CdpError(RuntimeError):
    pass


def auth(user: str, password: str, country: str = "") -> str:
    """The Basic auth of the zone – a country is asked for with ``-country-de`` after the username."""
    user = (user or "").strip()
    if country and "-country-" not in user:
        user += f"-country-{country.lower()}"
    return "Basic " + base64.b64encode(f"{user}:{(password or '').strip()}".encode()).decode()


async def default_connect(url: str, headers: dict, timeout: float):
    from websockets.asyncio.client import connect
    return await connect(url, additional_headers=headers, open_timeout=timeout, max_size=64 * 1024 * 1024)


CONNECT = default_connect   # tests put a fake browser here


def connect_error(exc: Exception) -> BrowserError:
    status = getattr(getattr(exc, "response", None), "status_code", 0) or 0
    why = getattr(getattr(exc, "response", None), "headers", {}) or {}
    why = (why.get("x-brd-error") or why.get("X-Brd-Error") or "") if hasattr(why, "get") else ""
    if status in (401, 403, 407):
        return BrowserError("invalid_auth", why or f"Bright Data refused the Browser API username / password "
                                                   f"(HTTP {status}).")
    if status == 402:
        return BrowserError("quota", why or "Your Bright Data balance is used up.")
    if status:
        return BrowserError("other", f"Browser API: HTTP {status} {why}".strip())
    return BrowserError("network", f"The Browser API can't be reached: {exc or exc.__class__.__name__}")


class Cdp:
    """Commands (``send``) and events (``expect``) on one browser connection; flat sessions for the tabs."""

    def __init__(self, ws):
        self.ws, self.ids = ws, itertools.count(1)
        self.pending: dict[int, asyncio.Future] = {}
        self.waiters: list[tuple[str, str | None, asyncio.Future]] = []
        self.reader = asyncio.get_running_loop().create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self.pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CdpError(str((msg["error"] or {}).get("message") or msg["error"])))
                        else:
                            fut.set_result(msg.get("result") or {})
                    continue
                for method, session, fut in list(self.waiters):
                    if method == msg.get("method") and session in (None, msg.get("sessionId")) and not fut.done():
                        fut.set_result(msg.get("params") or {})
        except Exception:  # noqa: BLE001 – the connection is gone; the open commands learn it below
            pass
        finally:
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_exception(BrowserError("network", "The Browser API closed the connection."))

    async def send(self, method: str, params: dict | None = None, session: str | None = None,
                   timeout: float = 60) -> dict:
        n = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[n] = fut
        msg = {"id": n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(n, None)

    def expect(self, method: str, session: str | None = None) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append((method, session, fut))
        return fut

    async def close(self) -> None:
        self.reader.cancel()
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass


async def fetch(url: str, header: str, *, timeout: float = 120, wait: float = 2, images: bool = False) -> dict:
    """One page in a fresh Browser API session: {"title", "url" (after redirects), "html", "text"}."""
    try:
        ws = await CONNECT(ENDPOINT, {"Authorization": header}, min(timeout, 60))
    except BrowserError:
        raise
    except Exception as exc:  # noqa: BLE001 – websockets' InvalidStatus, OSError, timeouts …
        raise connect_error(exc) from exc
    cdp = Cdp(ws)
    try:
        target = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        session = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        await cdp.send("Page.enable", session=session)
        if not images:
            try:   # billed by traffic: no pictures, fonts, videos
                await cdp.send("Network.enable", session=session)
                await cdp.send("Network.setBlockedURLs", {"urls": BLOCK}, session)
            except CdpError:
                pass
        loaded = cdp.expect("Page.loadEventFired", session)
        nav = await cdp.send("Page.navigate", {"url": url}, session, timeout=timeout)
        if nav.get("errorText"):
            raise BrowserError("navigate", str(nav["errorText"]))
        try:
            await asyncio.wait_for(loaded, timeout)
        except TimeoutError:
            pass   # still loading after the timeout: take what is there
        try:   # Bright Data solves CAPTCHAs on its own – wait until it is done (returns at once without one)
            await cdp.send("Captcha.waitForSolve", {}, session, timeout=min(timeout, 90))
        except (CdpError, TimeoutError):
            pass
        if wait > 0:
            await asyncio.sleep(wait)   # prices and lists that come after the load event
        res = await cdp.send("Runtime.evaluate", {"expression": EXTRACT, "returnByValue": True}, session, timeout=60)
        value = (res.get("result") or {}).get("value")
        page = json.loads(value) if isinstance(value, str) else {}
        return {"title": str(page.get("title") or ""), "url": str(page.get("url") or url),
                "html": str(page.get("html") or ""), "text": str(page.get("text") or "")}
    except TimeoutError as exc:
        raise BrowserError("network", f"No answer from the browser after {timeout:.0f} s") from exc
    except CdpError as exc:
        raise BrowserError("other", f"Browser: {exc}") from exc
    finally:
        await cdp.close()


class BrowserNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "browser", label="Browser API (Bright Data)", icon="🖥", run=self.run,
            description="Opens the URLs it gets in a real Chrome at Bright Data – JavaScript runs, CAPTCHAs are "
                        "solved – and hands on the rendered pages as text or HTML; files in the project's folder.",
            ai_hint="Load web pages in Bright Data's remote browser (Browser API, billed by traffic): for pages that "
                    "only show their content after JavaScript or block even the Web Unlocker. Loads the URLs of the "
                    "incoming text (the URLS: block, else every link; or the node's list) and hands on the visible "
                    "text or the rendered HTML. Outputs: pages, error (nothing could be loaded).",
            outputs=[{"id": "pages", "label": tr("Pages"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "format", "type": "choice", "label": "Format", "default": "text",
                 "options": [{"value": "text", "label": "Visible text of the page"},
                             {"value": "html", "label": "Rendered HTML"}]},
                {"key": "urls", "type": "textarea", "label": "URLs (optional)",
                 "description": "One per line. Empty: the URLs of the input (the URLS: list of Google Search / SERP, "
                                "else every link in it)."},
                {"key": "max_pages", "type": "number", "label": "At most pages", "default": 5,
                 "description": "0 = all. Every page is one browser session, billed by its traffic."},
                {"key": "wait", "type": "number", "label": "Wait after loading (seconds)", "default": 2,
                 "description": "For prices and lists that appear only after the page has loaded."},
                {"key": "images", "type": "bool", "label": "Load images and fonts", "default": False,
                 "description": "Off saves traffic (and money) – the text is the same."},
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

    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        s = self.ctx.settings
        urls = urls_in(cfg.get("urls") or "") or urls_in(node.input or "") or urls_in(node.task or "")
        limit = int(cfg.get("max_pages") or 0)
        skipped = urls[limit:] if limit > 0 else []
        urls = urls[:limit] if limit > 0 else urls
        if not urls:
            return node.route("error", tr("No URLs in the input – put Google Search before this node or list them "
                                          "in the node."))
        user, password = (s.get("browser_user") or "").strip(), (s.get("browser_password") or "").strip()
        if not user or not password:
            return node.route("error", tr("No Browser API username / password – add them in Settings → Plugins → "
                                          "Bright Data Scraper (the zone's Overview tab)."))
        text_mode = (cfg.get("format") or "text") == "text"
        country = (cfg.get("country") or s.get("country") or "").strip()
        header = auth(user, password, country)
        timeout = float(s.get("timeout") or 120)
        try:
            wait = max(0.0, min(float(cfg.get("wait") or 0), 30.0))
        except (TypeError, ValueError):
            wait = 2.0
        sem = asyncio.Semaphore(max(1, min(int(s.get("parallel") or 5), 20)))
        results: dict[str, dict] = {}
        fatal: list[BrowserError] = []
        done = [0]

        async def one(url: str) -> None:
            async with sem:
                if fatal:   # wrong username / password or no balance: don't open the rest
                    results[url] = {"url": url, "error": str(fatal[0])}
                    return
                try:
                    page = await fetch(url, header, timeout=timeout, wait=wait, images=bool(cfg.get("images")))
                except BrowserError as exc:
                    if exc.kind in ("invalid_auth", "quota"):
                        fatal.append(exc)
                    results[url] = {"url": url, "error": str(exc)}
                else:
                    body = page["text"] if text_mode else page["html"]
                    r = {"url": url, "title": page["title"], "text": page["text"],
                         "markdown": body if text_mode else "", "raw": "" if text_mode else body}
                    if not body.strip():
                        r["error"] = tr("empty page")
                    results[url] = r
                done[0] += 1
                node.progress(tr("🖥 {n} of {total} pages", n=done[0], total=len(urls)))

        node.progress(tr("opens {n} pages in Bright Data's browser …", n=len(urls)))
        await asyncio.gather(*(one(u) for u in urls))
        return ScrapeNode(self.ctx).hand_on(node, urls, results, skipped, markdown=text_mode,
                                            kind=tr("text") if text_mode else "HTML",
                                            via=tr("Bright Data's browser"), icon="🖥")
