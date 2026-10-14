"""ElevenLabs for Theron: 🎙 Choose voice and 🔊 Generate speech as process nodes, ▶ samples and audio files right
in the chat, a "Test" button for the API key – all through the plugin interface (theron_api 1, Theron ≥ 0.17)."""

from __future__ import annotations

import time

from .api import Client, ElevenLabsError
from .chat import ChatView
from .nodes import Nodes
from .player import Player

CACHE_HOURS = 6


class Voices:
    """The account's voices – cached in the plugin's storage, so the node's voice list opens at once."""

    def __init__(self, ctx):
        self.ctx = ctx

    def client(self, key: str | None = None) -> Client:
        return Client(self.ctx.http, self.ctx.settings.get("api_key") if key is None else key)

    def cached(self) -> list[dict]:
        return (self.ctx.storage.get("voices") or {}).get("voices") or []

    async def load(self, client: Client | None = None, fresh: bool = False) -> list[dict]:
        saved = self.ctx.storage.get("voices") or {}
        if not fresh and saved.get("voices") and time.time() - saved.get("at", 0) < CACHE_HOURS * 3600 \
                and saved.get("key") == self._key_hint():
            return saved["voices"]
        voices = await (client or self.client()).voices()
        voices.sort(key=lambda v: (v.get("category") == "premade", v["name"].lower()))   # own voices first
        self.ctx.storage.set("voices", {"voices": voices, "at": time.time(), "key": self._key_hint()})
        return voices

    def _key_hint(self) -> str:
        key = self.ctx.settings.get("api_key") or ""
        return key[-6:]   # notices a new key without storing it twice

    def forget(self) -> None:
        self.ctx.storage.delete("voices")


def register(ctx):
    voices = Voices(ctx)
    player = Player(ctx.data_dir / "samples", on_change=ctx.chat.refresh)
    ChatView(ctx, player).register()
    Nodes(ctx, voices, player).register()
    ctx.player, ctx.voices = player, voices   # for the tests

    async def test(values: dict):
        key = (values.get("api_key") or "").strip()
        if not key:
            return False, ctx.tr("Enter the API key first.")
        client = voices.client(key)
        try:
            sub = await client.subscription()
        except ElevenLabsError as exc:
            if exc.kind != "permissions":
                return False, ctx.tr("ElevenLabs says: {error}", error=exc)
            sub = None
        try:
            found = await client.voices()
        except ElevenLabsError as exc:
            return False, ctx.tr("The key works, but it can't read the voices: {error}", error=exc)
        if key == (ctx.settings.get("api_key") or "").strip():
            voices.forget()
            await voices.load(client, fresh=True)
        if sub is None:
            return True, ctx.tr("Connected · {n} voices. The key may not read the subscription, so the credits "
                                "can't be checked before speaking.", n=len(found))
        return True, ctx.tr("Connected · plan {tier} · {left} of {limit} characters left · {n} voices",
                            tier=sub["tier"] or "?", left=f"{sub['left']:,}", limit=f"{sub['character_limit']:,}",
                            n=len(found))

    ctx.settings.add_button("Test", test, tooltip="Checks the API key with ElevenLabs and shows your credits.")

    def changed(event):
        if "api_key" in (event.get("keys") or []):
            voices.forget()
            if ctx.settings.get("api_key"):
                ctx.spawn(refresh)

    async def refresh():
        try:
            await voices.load(fresh=True)
        except ElevenLabsError as exc:
            ctx.log.error(f"voices: {exc}")

    ctx.settings.on_change(changed)

    @ctx.on_start
    def start():
        if ctx.settings.get("api_key") and not voices.cached():
            ctx.spawn(refresh)

    @ctx.on_stop
    def stop():
        player.stop()
