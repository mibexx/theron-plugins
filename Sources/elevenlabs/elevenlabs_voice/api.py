"""The ElevenLabs REST calls the plugin needs – through ``ctx.http`` (standard library, works in every Theron build)."""

from __future__ import annotations

import time

BASE = "https://api.elevenlabs.io"
V3 = "eleven_v3"
MODELS = {
    V3: 4800,                         # characters per request (with a little room)
    "eleven_multilingual_v2": 9500,
    "eleven_turbo_v2_5": 38000,
    "eleven_flash_v2_5": 38000,
}


class ElevenLabsError(RuntimeError):
    """``kind``: "no_key", "invalid_key", "quota", "permissions", "rate_limit", "voice", "model", "network", "other"."""

    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def _detail(resp) -> tuple[str, str]:
    try:
        data = resp.json()
    except ValueError:
        return "", resp.text[:300]
    d = data.get("detail") if isinstance(data, dict) else None
    if isinstance(d, dict):
        return str(d.get("status") or d.get("code") or ""), str(d.get("message") or "")
    if isinstance(d, list) and d:   # validation errors
        return "invalid_request", "; ".join(str(x.get("msg", x)) for x in d if isinstance(x, dict))[:300]
    return "", str(d or resp.text)[:300]


def error_for(resp) -> ElevenLabsError:
    status, message = _detail(resp)
    s = status.lower()
    if "quota" in s or "credits" in s or resp.status == 402:
        return ElevenLabsError("quota", message or "Not enough ElevenLabs credits.", resp.status)
    if "missing_permission" in s or "permission" in s:
        return ElevenLabsError("permissions", message or "The API key lacks a permission.", resp.status)
    if resp.status == 401 or "invalid_api_key" in s or "unauthorized" in s:
        return ElevenLabsError("invalid_key", message or "ElevenLabs refused the API key.", resp.status)
    if resp.status == 429:
        return ElevenLabsError("rate_limit", message or "Too many requests at once.", resp.status)
    if "voice" in s or (resp.status == 404 and "voice" in message.lower()):
        return ElevenLabsError("voice", message or "Unknown voice.", resp.status)
    if "model" in s or "model" in message.lower():
        return ElevenLabsError("model", message or "The model can't be used like this.", resp.status)
    return ElevenLabsError("other", f"HTTP {resp.status}: {message}".strip(), resp.status)


class Client:
    def __init__(self, http, key: str):
        if not (key or "").strip():
            raise ElevenLabsError("no_key", "No ElevenLabs API key – add it in Settings → Plugins → ElevenLabs.")
        self.http, self.key = http, key.strip()

    async def _call(self, method: str, path: str, *, retries: int = 2, **kw):
        headers = {"xi-api-key": self.key, **kw.pop("headers", {})}
        for attempt in range(retries + 1):
            try:
                resp = await self.http.request(method, BASE + path, headers=headers, **kw)
            except OSError as exc:
                raise ElevenLabsError("network", f"ElevenLabs can't be reached: {exc}") from exc
            if resp.status == 429 and attempt < retries:   # busy: wait a little and try again
                await _sleep(2 * (attempt + 1))
                continue
            if not resp.ok:
                raise error_for(resp)
            return resp
        raise error_for(resp)

    async def subscription(self) -> dict:
        """{"tier", "character_count", "character_limit", "left", "resets"}."""
        data = (await self._call("GET", "/v1/user/subscription")).json() or {}
        used, limit = int(data.get("character_count") or 0), int(data.get("character_limit") or 0)
        return {"tier": data.get("tier", ""), "character_count": used, "character_limit": limit,
                "left": max(0, limit - used), "resets": data.get("next_character_count_reset_unix")}

    async def voices(self) -> list[dict]:
        """Every voice of the account (own and added from the library), compact."""
        out, token = [], None
        for _ in range(20):
            params = {"page_size": 100, **({"next_page_token": token} if token else {})}
            try:
                data = (await self._call("GET", "/v2/voices", params=params)).json() or {}
            except ElevenLabsError as exc:
                if exc.status != 404 or out:
                    raise
                data = (await self._call("GET", "/v1/voices")).json() or {}   # older API
                data["has_more"] = False
            out += [compact(v) for v in data.get("voices") or []]
            token = data.get("next_page_token")
            if not data.get("has_more") or not token:
                break
        return out

    async def speech(self, voice_id: str, text: str, *, model: str, output_format: str = "mp3_44100_128",
                     language: str = "") -> bytes:
        settings = {"stability": 0.5, "similarity_boost": 0.75}   # v3 takes 0.0 / 0.5 / 1.0 only
        body = {"text": text, "model_id": model, "voice_settings": settings}
        if language:
            body["language_code"] = language
        resp = await self._call("POST", f"/v1/text-to-speech/{voice_id}", params={"output_format": output_format},
                                json=body, headers={"Accept": "audio/mpeg"}, timeout=180)
        if not resp.content:
            raise ElevenLabsError("other", "ElevenLabs sent no audio.")
        return resp.content


def compact(v: dict) -> dict:
    labels = v.get("labels") or {}
    return {"voice_id": v.get("voice_id", ""), "name": v.get("name", ""), "category": v.get("category", ""),
            "description": (v.get("description") or labels.get("description") or "")[:200],
            "labels": {k: str(x) for k, x in labels.items() if x and k in ("gender", "age", "accent", "language",
                                                                          "use_case", "descriptive", "description")},
            "preview_url": v.get("preview_url") or "",
            "models": list(v.get("high_quality_base_model_ids") or [])}


def label_text(v: dict) -> str:
    """"female · young · American · narration" – what a voice is, short."""
    lb = v.get("labels") or {}
    parts = [lb.get(k) for k in ("gender", "age", "accent", "language", "use_case", "descriptive")]
    return " · ".join(p.replace("_", " ") for p in parts if p)


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


def now() -> float:
    return time.time()
