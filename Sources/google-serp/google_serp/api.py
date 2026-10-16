"""The Google search calls – SerpApi (serpapi.com) or Serper (serper.dev), through ``ctx.http``.

Google hands out 10 results per page; more results = more pages = more searches on the provider's bill."""

from __future__ import annotations

PAGE = 10
MAX_RESULTS = 100

PROVIDERS = {
    "serpapi": {"name": "SerpApi", "site": "serpapi.com",
                "cost": "≈ $25 (Starter, 1,000/month) down to ≈ $9 (Big Data, 30,000/month); 250 free per month"},
    "serper": {"name": "Serper", "site": "serper.dev",
               "cost": "≈ $1.00 (50k credits) down to ≈ $0.30 (12.5M credits); 2,500 free once"},
}


class SerpError(RuntimeError):
    """``kind``: "no_key", "invalid_key", "quota", "rate_limit", "network", "other"."""

    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def _message(resp) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or "")[:300]
    return ""


def error_for(status: int, msg: str, name: str) -> SerpError:
    low = msg.lower()
    if "run out of searches" in low or "credits" in low or "quota" in low or status == 402:
        return SerpError("quota", msg or f"No {name} searches left.", status)
    if status in (401, 403) or "api key" in low or "unauthorized" in low:
        return SerpError("invalid_key", msg or f"{name} refused the API key.", status)
    if status == 429:
        return SerpError("rate_limit", msg or f"Too many {name} requests at once.", status)
    return SerpError("other", f"HTTP {status}: {msg}".strip(), status)


class Client:
    def __init__(self, http, key: str, provider: str = "serpapi"):
        self.provider = provider if provider in PROVIDERS else "serpapi"
        self.name = PROVIDERS[self.provider]["name"]
        if not (key or "").strip():
            raise SerpError("no_key", "No Google SERP API key – add it in Settings → Plugins → Google SERP.")
        self.http, self.key = http, key.strip()

    async def _send(self, method: str, url: str, **kw):
        try:
            resp = await self.http.request(method, url, **kw)
        except OSError as exc:
            raise SerpError("network", f"{self.name} can't be reached: {exc}") from exc
        if not resp.ok:
            raise error_for(resp.status, _message(resp), self.name)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            return {}
        err = str(data.get("error") or "")
        if err and "hasn't returned any results" not in err:   # SerpApi: no results is not an error
            raise error_for(resp.status, err, self.name)
        return data

    async def page(self, query: str, n: int, *, country: str = "", language: str = "") -> list[dict]:
        """One page of organic results (``n`` = 0, 1, …): [{"title", "url", "snippet"}]."""
        if self.provider == "serper":
            body = {"q": query, "num": PAGE, "page": n + 1}
            if country:
                body["gl"] = country
            if language:
                body["hl"] = language
            data = await self._send("POST", "https://google.serper.dev/search", json=body,
                                    headers={"X-API-KEY": self.key, "Content-Type": "application/json"})
            items = data.get("organic") or []
        else:
            params = {"engine": "google", "q": query, "api_key": self.key, "num": PAGE, "start": n * PAGE}
            if country:
                params["gl"] = country
            if language:
                params["hl"] = language
            data = await self._send("GET", "https://serpapi.com/search.json", params=params)
            items = data.get("organic_results") or []
        return [{"title": str(i.get("title") or ""), "url": str(i.get("link") or ""),
                 "snippet": str(i.get("snippet") or "")} for i in items if isinstance(i, dict) and i.get("link")]

    async def search(self, query: str, count: int, *, country: str = "", language: str = "",
                     exclude: list[str] | None = None) -> tuple[list[dict], int]:
        """Up to ``count`` distinct results and how many searches (pages) it took."""
        count = max(1, min(int(count), MAX_RESULTS))
        out, seen, pages = [], set(), 0
        while len(out) < count and pages < MAX_RESULTS // PAGE + 2:
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
            if len(got) < PAGE // 2 or not fresh:   # Google has no more
                break
        return out[:count], pages

    async def account(self) -> dict:
        """SerpApi: {"plan", "left", "per_month"}; Serper has no free account call – one search instead."""
        if self.provider == "serpapi":
            data = await self._send("GET", "https://serpapi.com/account.json", params={"api_key": self.key})
            return {"plan": str(data.get("plan_name") or ""), "left": data.get("total_searches_left"),
                    "per_month": data.get("searches_per_month")}
        await self.page("theron", 0)
        return {}


def _excluded(url: str, sites: list[str]) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in sites)
