"""Loads pages in the browser like a person would and takes out their content.

"Real" means: the user's own Chrome without automation switches, a profile that keeps cookies, a user agent and client
hints without "Headless", a screen that fits the window, mouse moves and scrolling with pauses, one page per site at
a time. A bot check that doesn't clear by itself is reported as blocked – the plugin never solves CAPTCHAs; it can show
the page to the user instead."""

from __future__ import annotations

import asyncio
import json
import platform
import random
import re
from pathlib import Path
from urllib.parse import urlparse

from .cdp import Browser, CdpError, Session
from .markdown import to_markdown

EXTRACT = (Path(__file__).parent / "extract.js").read_text(encoding="utf-8")

CHALLENGE_TITLE = re.compile(r"just a moment|einen moment|checking your browser|attention required|access denied|"
                             r"zugriff verweigert|are you a robot|verify you are human|security check|"
                             r"bot verification|pardon our interruption|request blocked|ddos-guard", re.I)
CHALLENGE_DOM = ("#challenge-form, #challenge-running, #cf-challenge-running, .cf-turnstile, #turnstile-wrapper, "
                 "iframe[src*='challenges.cloudflare.com'], iframe[src*='captcha-delivery.com'], #px-captcha, "
                 "iframe[src*='hcaptcha.com'], iframe[src*='recaptcha'], .g-recaptcha, #distil_ident_block, "
                 "[id^='sec-if-cpt'], #sec-container")
PROTECTION = (("challenges.cloudflare.com", "Cloudflare"), ("cf-", "Cloudflare"), ("captcha-delivery", "DataDome"),
              ("px-captcha", "PerimeterX"), ("hcaptcha", "hCaptcha"), ("recaptcha", "reCAPTCHA"),
              ("sec-if-cpt", "Akamai"), ("ddos-guard", "DDoS-Guard"), ("distil", "Distil"))


def plat() -> tuple[str, str, str]:
    """navigator.platform, client-hint platform, architecture of this machine."""
    s, m = platform.system(), platform.machine().lower()
    arch = "arm" if m.startswith(("arm", "aarch")) else "x86"
    if s == "Darwin":
        return "MacIntel", "macOS", arch
    if s == "Windows":
        return "Win32", "Windows", arch
    return "Linux x86_64" if arch == "x86" else "Linux aarch64", "Linux", arch


def accept_language(lang: str) -> str:
    """"de" / "de-DE" / "de-DE,en" → a header like a browser sends it."""
    parts = [p.strip() for p in re.split(r"[,;\s]+", lang or "") if p.strip() and "=" not in p]
    if not parts:
        return ""
    out, seen = [], set()
    for p in parts:
        for code in ([p, p.split("-")[0]] if "-" in p else [p]):
            if code.lower() not in seen:
                seen.add(code.lower())
                out.append(code)
    if "en" not in seen:
        out += ["en-US", "en"] if "en-us" not in seen else ["en"]
    return ",".join(c if i == 0 else f"{c};q={max(0.9 - 0.1 * (i - 1), 0.1):.1f}" for i, c in enumerate(out))


def disguise(version: dict, lang: str) -> dict:
    """Emulation.setUserAgentOverride for a headless browser: the UA and client hints of the normal one."""
    ua = (version.get("userAgent") or "").replace("HeadlessChrome", "Chrome")
    product = version.get("product") or "Chrome/0"
    full = product.split("/")[-1]
    major = full.split(".")[0]
    name = "Microsoft Edge" if "Edg/" in ua else "Brave" if "Brave" in product else \
        "Chromium" if product.startswith("Chromium") else "Google Chrome"
    brands = [{"brand": name, "version": major}, {"brand": "Chromium", "version": major},
              {"brand": "Not-A.Brand", "version": "24"}]
    nav, ch, arch = plat()
    params = {"userAgent": ua, "platform": nav, "userAgentMetadata": {
        "brands": brands, "fullVersionList": [dict(b, version=full if b["version"] == major else "24.0.0.0")
                                              for b in brands],
        "platform": ch, "platformVersion": platform.mac_ver()[0] or platform.release() or "",
        "architecture": arch, "model": "", "mobile": False, "bitness": "64", "wow64": False}}
    if lang:
        params["acceptLanguage"] = lang
    return params


def protection_of(html: str) -> str:
    low = (html or "").lower()
    for marker, name in PROTECTION:
        if marker in low:
            return name
    return ""


class Page:
    """One tab, kept for several URLs."""

    def __init__(self, browser: Browser, session: Session, lang: str):
        self.browser, self.s, self.lang = browser, session, lang
        self.requests: set[str] = set()
        self.docs: dict[str, dict] = {}     # frame id → its document response (the last one: after redirects)
        self.frame = ""
        self.loaded = asyncio.Event()

    @classmethod
    async def open(cls, browser: Browser, lang: str) -> "Page":
        s = await browser.new_page()
        p = cls(browser, s, lang)
        p.pump = asyncio.create_task(p._events())
        await s.send("Page.enable")
        await s.send("Network.enable")
        await s.send("Runtime.enable")
        if browser.headless:
            await s.send("Emulation.setUserAgentOverride", disguise(browser.version, lang))
        elif lang:
            await s.send("Emulation.setUserAgentOverride",
                         {"userAgent": browser.version.get("userAgent", ""), "acceptLanguage": lang})
        return p

    async def _events(self) -> None:
        while True:
            msg = await self.s.events.get()
            m, p = msg.get("method"), msg.get("params") or {}
            if m == "Network.requestWillBeSent":
                self.requests.add(p.get("requestId"))
            elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                self.requests.discard(p.get("requestId"))
            elif m == "Network.responseReceived" and p.get("type") == "Document":
                r = p.get("response") or {}
                self.docs[p.get("frameId") or ""] = {"status": r.get("status"), "mime": r.get("mimeType"),
                                                     "url": r.get("url"), "request": p.get("requestId")}
            elif m == "Page.loadEventFired":
                self.loaded.set()

    @property
    def doc(self) -> dict:
        return self.docs.get(self.frame) or {}

    async def close(self) -> None:
        self.pump.cancel()
        await self.s.close()

    # ------------------------------------------------------------------ like a person
    async def settle(self, quiet: float = 1.2, longest: float = 8) -> None:
        loop = asyncio.get_running_loop()
        end, calm_since = loop.time() + longest, None
        while loop.time() < end:
            if not self.requests:
                calm_since = calm_since or loop.time()
                if loop.time() - calm_since >= quiet:
                    return
            else:
                calm_since = None
            await asyncio.sleep(0.15)

    async def wander(self) -> None:
        """Mouse moves and a few scrolls with pauses – also loads lazy content."""
        w, h = self.browser.size
        x, y = random.randint(200, w - 200), random.randint(150, h - 200)
        for _ in range(random.randint(3, 6)):
            tx, ty = random.randint(80, w - 80), random.randint(80, h - 120)
            for i in range(1, 6):
                await self.s.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x + (tx - x) * i / 5,
                                                               "y": y + (ty - y) * i / 5})
                await asyncio.sleep(random.uniform(0.01, 0.04))
            x, y = tx, ty
            await asyncio.sleep(random.uniform(0.05, 0.25))
        try:
            height = int(await self.s.eval("Math.max(document.body ? document.body.scrollHeight : 0, "
                                           "document.documentElement.scrollHeight)", timeout=5) or 0)
        except CdpError:
            height = 0
        scrolled, steps = 0, 0
        while scrolled < min(height, 12000) and steps < 14:
            delta = random.randint(350, 800)
            await self.s.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                                                           "deltaX": 0, "deltaY": delta})
            scrolled += delta
            steps += 1
            await asyncio.sleep(random.uniform(0.12, 0.45))
        await self.settle(0.8, 5)

    async def challenged(self) -> str:
        """'' or the name of the bot protection the page shows right now."""
        try:
            info = await self.s.eval(
                "({t: document.title, n: (document.body ? document.body.innerText : '').length, "
                f"c: !!document.querySelector({json.dumps(CHALLENGE_DOM)}), "
                "h: document.documentElement.outerHTML.slice(0, 60000)})", timeout=10) or {}
        except CdpError:
            return ""
        if info.get("c") or (CHALLENGE_TITLE.search(info.get("t") or "") and (info.get("n") or 0) < 3000):
            return protection_of(info.get("h") or "") or "bot check"
        if self.doc.get("status") in (403, 429, 503) and (info.get("n") or 0) < 1500:
            return protection_of(info.get("h") or "") or f"HTTP {self.doc['status']}"
        return ""

    # ------------------------------------------------------------------ one URL
    async def load(self, url: str, timeout: float = 45) -> None:
        self.docs, self.requests = {}, set()
        self.loaded.clear()
        r = await self.s.send("Page.navigate", {"url": url}, timeout=timeout)
        if r.get("errorText"):
            raise CdpError(r["errorText"])
        self.frame = r.get("frameId") or ""
        try:
            await asyncio.wait_for(self.loaded.wait(), timeout)
        except asyncio.TimeoutError:
            pass   # slow pages: take what is there
        await self.settle()

    async def wait_out(self, seconds: float) -> str:
        """A bot check often clears itself in a real browser – wait for it; '' = it did."""
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        found = await self.challenged()
        while found and loop.time() < end:
            await asyncio.sleep(1.5)
            if random.random() < 0.5:
                w, h = self.browser.size
                await self.s.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": random.randint(100, w - 100),
                                                               "y": random.randint(100, h - 100)})
            found = await self.challenged()
        if not found:
            self.loaded.clear()
            await self.settle()
        return found

    async def content(self, *, main: bool, images: bool, original: bool) -> dict:
        title = await self.s.eval("document.title", timeout=10) or ""
        out = {"title": title, "final_url": await self.s.eval("location.href", timeout=10) or "",
               "status": self.doc.get("status"), "mime": self.doc.get("mime") or ""}
        if original and self.doc.get("request"):
            try:
                body = await self.s.send("Network.getResponseBody", {"requestId": self.doc["request"]})
                out["raw"] = body.get("body") if not body.get("base64Encoded") else ""
            except CdpError:
                out["raw"] = ""
        if not out.get("raw"):
            out["raw"] = await self.s.eval("'<!DOCTYPE html>\\n' + document.documentElement.outerHTML", timeout=30) or ""
        script = f"const MODE = {json.dumps('main' if main else 'full')}; const IMAGES = {json.dumps(images)};\n"
        data = await self.s.eval("(() => {" + script + "return (\n" + EXTRACT.strip().rstrip(";") + "\n);})()",
                                 timeout=30) or {}
        out.update(title=data.get("title") or title, lang=data.get("lang") or "",
                   description=data.get("description") or "", canonical=data.get("canonical") or "",
                   html=data.get("html") or "", text=data.get("text") or "")
        out["markdown"] = to_markdown(out["html"], images=images)
        return out


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)


def urls_in(text: str) -> list[str]:
    """The URLs of a hand-over – the ``URLS:`` block (Google SERP) if there is one, else every http(s) link."""
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
