"""Grounding with Google Search – the Gemini API (Google AI / Google Cloud) answers with Google Search behind it and
names its sources. Google's official way to search the whole web after the Custom Search API.

The sources come as Google redirect links (vertexaisearch.cloud.google.com/grounding-api-redirect/…) with the
site's domain as title; ``resolve`` follows them to the real pages."""

from __future__ import annotations

import asyncio
import re

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-latest"
ALIASES = ["gemini-flash-latest", "gemini-pro-latest", "gemini-flash-lite-latest"]
COST = "grounded requests: a free amount per month/day, then about $14–35 per 1,000 depending on the model"
REDIRECT = re.compile(r"^https://vertexaisearch\.cloud\.google\.com/grounding-api-redirect/", re.I)


class GeminiError(RuntimeError):
    """``kind``: "no_key", "invalid_key", "quota", "model", "blocked", "network", "other"."""

    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def error_for(resp) -> GeminiError:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    err = err if isinstance(err, dict) else {}
    msg = str(err.get("message") or resp.text[:300] or "")
    low = f"{msg} {err.get('status') or ''}".lower()
    if resp.status == 429 or "resource_exhausted" in low or "quota" in low:
        return GeminiError("quota", msg or "Quota exceeded.", resp.status)
    if "api key" in low or resp.status in (401, 403):
        return GeminiError("invalid_key", msg or "Google refused the API key.", resp.status)
    if resp.status == 404 or "model" in low:
        return GeminiError("model", msg or "Unknown model.", resp.status)
    return GeminiError("other", f"HTTP {resp.status}: {msg}".strip(), resp.status)


class Gemini:
    def __init__(self, http, key: str):
        if not (key or "").strip():
            raise GeminiError("no_key", "No Gemini API key – add it in Settings → Plugins → Google Search (or a "
                                        "Google API key with the Gemini API enabled).")
        self.http, self.key = http, key.strip()

    async def _call(self, method: str, path: str, **kw):
        try:
            resp = await self.http.request(method, BASE + path, headers={"x-goog-api-key": self.key}, **kw)
        except OSError as exc:
            raise GeminiError("network", f"Google can't be reached: {exc}") from exc
        if not resp.ok:
            raise error_for(resp)
        try:
            return resp.json() or {}
        except ValueError:
            return {}

    async def models(self) -> list[str]:
        """The models of the account that can answer (generateContent) – Gemini only, newest names first."""
        out, token = [], ""
        for _ in range(10):
            data = await self._call("GET", "/models", params={"pageSize": 200, **({"pageToken": token} if token else {})})
            for m in data.get("models") or []:
                name = str(m.get("name") or "").removeprefix("models/")
                if name.startswith("gemini") and "generateContent" in (m.get("supportedGenerationMethods") or []) \
                        and not any(x in name for x in ("embedding", "tts", "image", "audio", "live")):
                    out.append(name)
            token = data.get("nextPageToken") or ""
            if not token:
                break
        return sorted(set(out), key=lambda n: (not n.endswith("-latest"), [-int(x) for x in re.findall(r"\d+", n)],
                                               "preview" in n, n))

    async def ask(self, prompt: str, *, model: str = DEFAULT_MODEL, system: str = "") -> dict:
        """One grounded answer: {"text", "queries", "sources": [{"title", "url"}], "supports": [...]}."""
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = await self._call("POST", f"/models/{model or DEFAULT_MODEL}:generateContent", json=body)
        cands = data.get("candidates") or []
        if not cands:
            why = (data.get("promptFeedback") or {}).get("blockReason") or "no answer"
            raise GeminiError("blocked", f"Gemini gave no answer ({why}).")
        cand = cands[0]
        text = "".join(str(p.get("text") or "") for p in (cand.get("content") or {}).get("parts") or [])
        meta = cand.get("groundingMetadata") or {}
        sources = []
        for ch in meta.get("groundingChunks") or []:
            web = ch.get("web") if isinstance(ch, dict) else None
            if isinstance(web, dict) and web.get("uri"):
                sources.append({"title": str(web.get("title") or ""), "url": str(web["uri"])})
        return {"text": text.strip(), "queries": [str(q) for q in meta.get("webSearchQueries") or []],
                "sources": sources, "supports": meta.get("groundingSupports") or [],
                "finish": str(cand.get("finishReason") or "")}

    async def resolve(self, sources: list[dict]) -> list[dict]:
        """Google's redirect links → the real page URLs (HEAD, else GET); a link that won't resolve stays as it is."""
        async def one(s):
            if not REDIRECT.match(s["url"]):
                return s
            for method in ("HEAD", "GET"):
                try:
                    resp = await self.http.request(method, s["url"], timeout=12)
                except OSError:
                    continue
                if resp.url and not REDIRECT.match(resp.url):
                    return {**s, "url": resp.url, "via": s["url"]}
            return s
        return list(await asyncio.gather(*(one(s) for s in sources)))
