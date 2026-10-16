"""Google's Custom Search JSON API (Google Cloud) through ``ctx.http``.

10 results per request (``num`` ≤ 10), ``start`` up to 91 – so at most 100 results per query; every request is one
query on the quota (100 free per day, then $5 per 1,000, at most 10,000 per day). Google closed the API to new
customers and switches it off on 1 January 2027."""

from __future__ import annotations

URL = "https://www.googleapis.com/customsearch/v1"
PAGE = 10
MAX_RESULTS = 100
COST = "100 free per day, then $5 per 1,000 (at most 10,000 per day)"


class CseError(RuntimeError):
    """``kind``: "no_key", "no_cx", "invalid_key", "quota", "network", "other"."""

    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def error_for(resp) -> CseError:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    err = err if isinstance(err, dict) else {}
    msg = str(err.get("message") or resp.text[:300] or "")
    reasons = " ".join(str(e.get("reason") or "") for e in err.get("errors") or [] if isinstance(e, dict))
    low = f"{msg} {reasons} {err.get('status') or ''}".lower()
    if resp.status == 429 or "quota" in low or "ratelimit" in low or "dailylimit" in low:
        return CseError("quota", msg or "Quota exceeded.", resp.status)
    if "api key" in low or "keyinvalid" in low or "api_key" in low or resp.status == 401:
        return CseError("invalid_key", msg or "Google refused the API key.", resp.status)
    if resp.status == 403:
        return CseError("invalid_key", msg or "Access denied – is the Custom Search API enabled in the project?",
                        resp.status)
    if "cx" in low or "search engine" in low or "invalid value" in low:
        return CseError("no_cx", msg or "Google doesn't know the search engine id (cx).", resp.status)
    return CseError("other", f"HTTP {resp.status}: {msg}".strip(), resp.status)


class Client:
    name = "Google Custom Search"

    def __init__(self, http, key: str, cx: str):
        if not (key or "").strip():
            raise CseError("no_key", "No Google API key – add it in Settings → Plugins → Google Search.")
        if not (cx or "").strip():
            raise CseError("no_cx", "No search engine id (cx) – add it in Settings → Plugins → Google Search.")
        self.http, self.key, self.cx = http, key.strip(), cx.strip()

    async def page(self, query: str, n: int, *, country: str = "", language: str = "") -> list[dict]:
        """One page of results (``n`` = 0, 1, …): [{"title", "url", "snippet"}]."""
        params = {"key": self.key, "cx": self.cx, "q": query, "num": PAGE, "start": n * PAGE + 1}
        if country:
            params["gl"] = country
        if language:
            params["hl"] = language
            params["lr"] = f"lang_{language}"
        try:
            resp = await self.http.request("GET", URL, params=params)
        except OSError as exc:
            raise CseError("network", f"Google can't be reached: {exc}") from exc
        if not resp.ok:
            raise error_for(resp)
        try:
            data = resp.json() or {}
        except ValueError:
            data = {}
        items = (data.get("items") or []) if isinstance(data, dict) else []
        return [{"title": str(i.get("title") or ""), "url": str(i.get("link") or ""),
                 "snippet": str(i.get("snippet") or "").replace("\n", " ")}
                for i in items if isinstance(i, dict) and i.get("link")]

    async def search(self, query: str, count: int, *, country: str = "", language: str = "",
                     exclude: list[str] | None = None) -> tuple[list[dict], int]:
        """Up to ``count`` distinct results and how many queries (pages) it took."""
        count = max(1, min(int(count), MAX_RESULTS))
        out, seen, pages = [], set(), 0
        while len(out) < count and pages < MAX_RESULTS // PAGE:
            got = await self.page(query, pages, country=country, language=language)
            pages += 1
            fresh = 0
            for r in got:
                key = r["url"].rstrip("/")
                if key in seen or _excluded(r["url"], exclude or []):
                    continue
                seen.add(key)
                fresh += 1
                out.append(r)
            if len(got) < PAGE or not fresh:   # Google has no more
                break
        return out[:count], pages


def _excluded(url: str, sites: list[str]) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in sites)
