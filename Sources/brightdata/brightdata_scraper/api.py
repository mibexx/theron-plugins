"""The Bright Data REST calls – POST https://api.brightdata.com/request through ``ctx.http``.

Web Unlocker: ``format: json`` wraps the target's answer as {"status_code", "headers", "body"}; ``data_format:
markdown`` lets Bright Data turn the HTML into Markdown. SERP API: the same endpoint with a SERP zone and a Google URL –
``data_format: parsed`` makes it answer with the parsed results ({"general", "organic": [{"link", "title",
"description", "rank"}]}) whatever the zone's default response format is (Markdown there gave empty results;
``brd_json=1`` in the URL gave an empty body with the zone on JSON).
Only successful requests are billed."""

from __future__ import annotations

import asyncio
import json as _json
from urllib.parse import urlencode, urlparse

ENDPOINT = "https://api.brightdata.com/request"
COST = "≈ $1.50 pay as you go, ≈ $1.30 on the Scale plan; 5,000 free per month"
SERP_COST = "≈ $1.50 per 1,000 searches pay as you go, ≈ $1.30 on the Scale plan"
PAGE = 10           # Google: 10 results per page – every page is one billed search
RETRY_DELAY = 1.5   # seconds before asking again after an empty answer (times the attempt)
MAX_RESULTS = 100


class UnlockError(RuntimeError):
    """``kind``: "no_key", "no_zone", "invalid_key", "quota", "rate_limit", "network", "other"."""

    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def _message(resp) -> str:
    why = (resp.headers.get("x-brd-error") or resp.headers.get("X-Brd-Error") or "").strip()
    try:
        data = resp.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        why = why or str(data.get("error") or data.get("message") or "")
    return (why or resp.text)[:300].strip()


def error_for(status: int, msg: str) -> UnlockError:
    low = msg.lower()
    if status == 402 or "balance" in low or "payment" in low or "quota" in low:
        return UnlockError("quota", msg or "Your Bright Data balance is used up.", status)
    if status in (401, 403) or "authentication" in low or "unauthorized" in low:
        return UnlockError("invalid_key", msg or "Bright Data refused the API key.", status)
    if "zone" in low:
        return UnlockError("no_zone", msg, status)
    if status == 429:
        return UnlockError("rate_limit", msg or "Too many Bright Data requests at once.", status)
    return UnlockError("other", f"HTTP {status}: {msg}".strip(), status)


def google_url(query: str, page: int = 0, *, country: str = "", language: str = "") -> str:
    params = {"q": query}
    if country:
        params["gl"] = country.lower()
    if language:
        params["hl"] = language.lower()
    if page:
        params["start"] = page * PAGE
    return "https://www.google.com/search?" + urlencode(params)


def is_goto(url: str) -> bool:
    u = urlparse(url)
    return u.netloc.endswith("google.com") and u.path == "/goto"


def location(url: str, timeout: float = 10) -> str:
    """Where ``url`` redirects to – asked without following it (the target isn't loaded); "" if it doesn't."""
    import urllib.error
    import urllib.request

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Theron)"})
    try:
        with urllib.request.build_opener(Stay).open(req, timeout=timeout):
            return ""
    except urllib.error.HTTPError as exc:
        target = exc.headers.get("Location", "") if exc.code in (301, 302, 303, 307, 308) else ""
        return target if urlparse(target).scheme in ("http", "https") else ""
    except (OSError, ValueError):
        return ""


def redirect_target(url: str) -> str:
    """Google's encrypted ``/goto?url=…`` link → the shop page its 302 points to. Free (Google, not Bright Data).
    Anything else, or no answer: the link as it is."""
    return (location(url) or url) if is_goto(url) else url


async def resolve_redirects(hits: list[dict]) -> list[dict]:
    """The hits with Google's /goto links replaced by the pages they lead to (all at once)."""
    todo = [h for h in hits if "google.com/goto" in h["url"]]
    if todo:
        targets = await asyncio.gather(*(asyncio.to_thread(redirect_target, h["url"]) for h in todo))
        for h, t in zip(todo, targets):
            h["url"] = t
    return hits


class NotParsed(ValueError):
    """The answer has no parsed Google page (empty, Markdown, HTML …)."""


def real_link(url: str) -> str:
    """Google's own redirect (/url?q=…) → the page it leads to; anything else as it is."""
    from urllib.parse import parse_qs
    u = urlparse(url)
    if u.netloc.endswith("google.com") and u.path == "/url":
        target = (parse_qs(u.query).get("q") or parse_qs(u.query).get("url") or [""])[0]
        if urlparse(target).scheme in ("http", "https"):
            return target
    return url


def organic(data) -> list[dict]:
    """The organic hits of a parsed SERP answer: [{"title", "url", "snippet"}] (also when it comes wrapped as
    {"status_code", "body": "<json>"} or in the newer {"results": [{"url", "title"}]} shape). Raises NotParsed when
    there is no parsed Google page at all – not the same as a page without hits."""
    if isinstance(data, dict) and "body" in data and "general" not in data:
        body = data.get("body")
        if isinstance(body, str):
            try:
                body = _json.loads(body) if body.strip() else None
            except ValueError:
                raise NotParsed(body.strip()[:80]) from None
        data = body
    if not isinstance(data, dict) or not any(k in data for k in ("general", "organic", "results")):
        raise NotParsed(str(data)[:80] if data else "empty")
    items = data.get("organic") or data.get("results") or []
    out = []
    for i in items if isinstance(items, list) else []:
        if not isinstance(i, dict) or i.get("type") not in (None, "organic"):
            continue
        url = real_link(str(i.get("link") or i.get("url") or ""))
        if urlparse(url).scheme in ("http", "https"):
            out.append({"title": str(i.get("title") or ""), "url": url,
                        "snippet": str(i.get("description") or i.get("snippet") or "")})
    return out


class Client:
    def __init__(self, http, key: str, zone: str, *, timeout: float = 120, what: str = "Web Unlocker zone"):
        if not (key or "").strip():
            raise UnlockError("no_key", "No Bright Data API key – add it in Settings → Plugins → Bright Data Scraper.")
        if not (zone or "").strip():
            raise UnlockError("no_zone", f"No {what} – add it in Settings → Plugins → Bright Data Scraper.")
        self.http, self.key, self.zone, self.timeout = http, key.strip(), zone.strip(), timeout

    async def _post(self, body: dict):
        try:
            resp = await self.http.request("POST", ENDPOINT, json={"zone": self.zone, **body}, timeout=self.timeout,
                                           headers={"Authorization": f"Bearer {self.key}",
                                                    "Content-Type": "application/json"})
        except (OSError, TimeoutError) as exc:
            raise UnlockError("network", f"Bright Data can't be reached: {exc or exc.__class__.__name__}") from exc
        if not resp.ok:
            raise error_for(resp.status, _message(resp))
        return resp

    async def unlock(self, url: str, *, markdown: bool = True, country: str = "", render: bool = False) -> dict:
        """{"url", "status" (the target's), "body", "headers"}; raises UnlockError when Bright Data itself refuses."""
        body = {"url": url, "format": "json"}
        if markdown:
            body["data_format"] = "markdown"
        if country:
            body["country"] = country.lower()
        if render:
            body["render"] = "true"
        resp = await self._post(body)
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict) or "body" not in data:   # an answer as it is (format raw)
            return {"url": url, "status": 200, "body": resp.text, "headers": {}}
        page = data.get("body")
        if not isinstance(page, str):
            page = _json.dumps(page, ensure_ascii=False)
        return {"url": url, "status": int(data.get("status_code") or 200), "body": page,
                "headers": data.get("headers") if isinstance(data.get("headers"), dict) else {}}

    async def serp_page(self, query: str, page: int = 0, *, country: str = "", language: str = "",
                        tries: int = 3) -> list[dict]:
        """One Google result page through the SERP zone (``page`` = 0, 1, …). Now and then Bright Data answers with an
        empty body – asked again (``tries`` in all) before it counts as an error."""
        body = {"url": google_url(query, page, country=country, language=language), "format": "json",
                "data_format": "parsed"}
        if country:
            body["country"] = country.lower()
        for attempt in range(max(1, tries)):
            resp = await self._post(body)
            try:
                return await resolve_redirects(organic(resp.json()))
            except (NotParsed, ValueError):
                if attempt + 1 < max(1, tries):
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise NotParsed("no parsed Google page") from None
        return []

    async def search(self, query: str, count: int, *, country: str = "", language: str = "",
                     exclude: list[str] | None = None) -> tuple[list[dict], int]:
        """Up to ``count`` distinct results and how many searches (pages) it took."""
        count = max(1, min(int(count), MAX_RESULTS))
        out, seen, pages = [], set(), 0
        while len(out) < count and pages < MAX_RESULTS // PAGE + 2:
            try:
                got = await self.serp_page(query, pages, country=country, language=language)
            except NotParsed:
                if pages:   # a further page Google has nothing for: what we have is the result
                    break
                raise UnlockError("other", "The SERP zone didn't answer with parsed Google results (asked 3 times) – "
                                           "is it a SERP API zone?") from None
            pages += 1
            fresh = 0
            for r in got:
                key = r["url"].rstrip("/")
                if key in seen or excluded(r["url"], exclude or []):
                    continue
                seen.add(key)
                fresh += 1
                out.append(r)
            if len(got) < PAGE // 2 or not fresh:   # Google has no more
                break
        return out[:count], pages


def excluded(url: str, sites: list[str]) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in sites)
