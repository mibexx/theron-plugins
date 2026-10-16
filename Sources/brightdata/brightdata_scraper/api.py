"""The Web Unlocker call – POST https://api.brightdata.com/request through ``ctx.http``.

``format: json`` wraps the target's answer as {"status_code", "headers", "body"}; ``data_format: markdown`` lets
Bright Data turn the HTML into Markdown. Only successful pages are billed."""

from __future__ import annotations

import json as _json

ENDPOINT = "https://api.brightdata.com/request"
COST = "≈ $1.50 pay as you go, ≈ $1.30 on the Scale plan; 5,000 free per month"


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


class Client:
    def __init__(self, http, key: str, zone: str, *, timeout: float = 120):
        if not (key or "").strip():
            raise UnlockError("no_key", "No Bright Data API key – add it in Settings → Plugins → Bright Data Scraper.")
        if not (zone or "").strip():
            raise UnlockError("no_zone", "No Web Unlocker zone – add it in Settings → Plugins → Bright Data Scraper.")
        self.http, self.key, self.zone, self.timeout = http, key.strip(), zone.strip(), timeout

    async def unlock(self, url: str, *, markdown: bool = True, country: str = "", render: bool = False) -> dict:
        """{"url", "status" (the target's), "body", "headers"}; raises UnlockError when Bright Data itself refuses."""
        body = {"zone": self.zone, "url": url, "format": "json"}
        if markdown:
            body["data_format"] = "markdown"
        if country:
            body["country"] = country.lower()
        if render:
            body["render"] = "true"
        try:
            resp = await self.http.request("POST", ENDPOINT, json=body, timeout=self.timeout,
                                           headers={"Authorization": f"Bearer {self.key}",
                                                    "Content-Type": "application/json"})
        except (OSError, TimeoutError) as exc:
            raise UnlockError("network", f"Bright Data can't be reached: {exc or exc.__class__.__name__}") from exc
        if not resp.ok:
            raise error_for(resp.status, _message(resp))
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
