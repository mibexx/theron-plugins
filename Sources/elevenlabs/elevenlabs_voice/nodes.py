"""The two process nodes: 🎙 Choose voice and 🔊 Generate speech."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from .api import MODELS, V3, Client, ElevenLabsError, label_text

VOICE_LINE = re.compile(r"ELEVENLABS_VOICE:\s*([A-Za-z0-9]{8,40})")
TAGS = re.compile(r"\[[a-zA-Z][a-zA-Z \-']{1,30}\]")
EMOTION_TAGS = ("[excited]", "[happy]", "[curious]", "[sarcastic]", "[serious]", "[calm]", "[sad]", "[angry]",
                "[whispers]", "[shouts]", "[laughs]", "[chuckles]", "[sighs]", "[gasps]", "[pause]", "[hesitates]")
FORMATS = ["mp3_44100_128", "mp3_44100_192", "mp3_22050_32", "pcm_44100", "opus_48000_128"]
EXT = {"mp3": ".mp3", "pcm": ".wav", "opus": ".opus"}


# what Choose voice hands on before the material it passes through: "Voice: …" + the ELEVENLABS_VOICE line (+ ---)
VOICE_LINES = re.compile(r"^(?:Voice|Stimme): .*\n(?=ELEVENLABS_VOICE:)|^.*ELEVENLABS_VOICE:.*$\n?(?:\n?---\n)?", re.M)


def material_of(node) -> str:
    """What the node works on: the orchestrator's assignment for this step AND the hand-overs before it – the
    hand-over alone may be just "Voice: …" from Choose voice, the assignment alone misses the script."""
    task, given = (node.task or "").strip(), (node.input or "").strip()
    if not given or task in given:
        return task or given
    if not task or given in task:
        return given
    return f"ASSIGNMENT FOR THIS STEP:\n{task}\n\nHAND-OVERS FROM THE STEPS BEFORE:\n{given}"


def json_in(text: str):
    """The first JSON object / list in an AI answer (with or without ``` fences)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = text.find(opener), text.rfind(closer)
        if a >= 0 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except ValueError:
                continue
    return None


def slug(text: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].strip("-") or "part"


def split_text(text: str, limit: int) -> list[str]:
    """Long text → parts below ``limit`` characters, cut after sentences (a sentence too long by itself: after
    words)."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    pieces = []
    for sentence in re.split(r"(?<=[.!?…])\s+|\n{2,}", text):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    parts, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > limit:
            parts.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        parts.append(cur)
    return parts


class Nodes:
    def __init__(self, ctx, voices, player=None):
        self.ctx, self.voices, self.player = ctx, voices, player

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "voice", label="Choose voice", icon="🎙", run=self.choose,
            description="Picks an ElevenLabs voice – you choose it in the chat, the node picks it by the mood of the "
                        "text, or it is fixed here. Plays a sample in the chat.",
            ai_hint="Pick the ElevenLabs voice for spoken audio (before 'Generate speech'). Hands the voice on.",
            outputs=[{"id": "voice", "label": tr("Voice"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "mode", "type": "choice", "label": "Mode", "default": "manual",
                 "options": [{"value": "manual", "label": "Manual – I choose in the chat"},
                             {"value": "auto", "label": "Automatic – by mood and preselection"},
                             {"value": "fixed", "label": "Fixed – the voice below"}]},
                {"key": "voice_id", "type": "choice", "label": "Voice", "show_if": {"mode": "fixed"},
                 "options": self.voice_options, "buttons": [self.sample_button()],
                 "description": "Your ElevenLabs voices (reloaded when the API key changes)."},
                {"key": "preselection", "type": "text", "label": "Preselection", "show_if": {"mode": ["manual", "auto"]},
                 "description": "What fits, e.g. “female, German, warm” – narrows the list (manual) and guides the "
                                "choice (automatic). Empty = all voices."},
            ])
        self.ctx.nodes.register(
            "speech", label="Generate speech", icon="🔊", run=self.speak,
            description="Turns the incoming text (e.g. a video script) into speech with ElevenLabs – the AI picks what "
                        "is spoken and splits it into parts; hands on the paths of the audio files.",
            ai_hint="Generate spoken audio files with ElevenLabs from the incoming text (e.g. narration of a video "
                    "script). Outputs: files (paths) or error (no API key, no credits, …).",
            outputs=[{"id": "files", "label": tr("Audio files"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "emotions", "type": "bool", "label": "Emotions (v3 audio tags)", "default": True,
                 "description": "Speaks with feeling: the AI adds tags like [excited] or [whispers] (Eleven v3). "
                                "If the voice can't speak v3, the parts are spoken without them."},
                {"key": "model", "type": "choice", "label": "Model without emotions", "default": "eleven_multilingual_v2",
                 "show_if": {"emotions": False},
                 "options": [{"value": "eleven_multilingual_v2", "label": "Multilingual v2 – best quality"},
                             {"value": "eleven_turbo_v2_5", "label": "Turbo v2.5 – fast"},
                             {"value": "eleven_flash_v2_5", "label": "Flash v2.5 – fastest, half the credits"}]},
                {"key": "voice_id", "type": "choice", "label": "Voice",
                 "options": lambda cfg: [{"value": "", "label": "From “Choose voice” before"}] + self.voice_options(cfg),
                 "buttons": [self.sample_button()],
                 "description": "Empty: the voice the node “Choose voice” handed over."},
                {"key": "folder", "type": "text", "label": "Folder", "default": "audio",
                 "description": "Where the files go – relative to the project's workspace."},
                {"key": "output_format", "type": "choice", "label": "Format", "default": "mp3_44100_128",
                 "options": FORMATS},
                {"key": "language", "type": "text", "label": "Language (optional)",
                 "description": "ISO code like de or en – only needed when ElevenLabs guesses wrong."},
            ])

    # ------------------------------------------------------------------ ▶ sample next to the voice field
    def sample_of(self, cfg: dict) -> str:
        voice = next((v for v in self.voices.cached() if v["voice_id"] == (cfg.get("voice_id") or "")), None)
        return (voice or {}).get("preview_url") or ""

    def sample_button(self) -> dict:
        def label(cfg):
            url = self.sample_of(cfg)
            return "■ Stop" if url and self.player and self.player.playing() == url else "▶ Sample"

        async def press(cfg):
            if not cfg.get("voice_id"):
                return False, self.ctx.tr("Choose a voice first.")
            url = self.sample_of(cfg)
            if not url:
                return False, self.ctx.tr("ElevenLabs has no sample of this voice.")
            try:
                await asyncio.to_thread(self.player.toggle, url)
            except Exception as exc:  # noqa: BLE001 – no player on this system, download failed …
                return False, self.ctx.tr("Can't play the sample: {error}", error=exc)
            return None

        return {"id": "sample", "label": label, "run": press, "tooltip": "Plays the voice's sample from ElevenLabs."}

    def voice_options(self, cfg: dict) -> list[dict]:
        return [{"value": v["voice_id"], "label": f"{v['name']} – {label_text(v)}".rstrip(" –")}
                for v in self.voices.cached()]

    # ================================================================== 🎙 Choose voice
    async def choose(self, node):
        tr = self.ctx.tr
        try:
            client = self.voices.client()
            voices = await self.voices.load(client)
        except ElevenLabsError as exc:
            return node.route("error", tr("ElevenLabs: {error}", error=exc))
        if not voices:
            return node.route("error", tr("Your ElevenLabs account has no voices."))
        mode = node.config.get("mode") or "manual"
        reason = ""
        if mode == "fixed":
            voice = next((v for v in voices if v["voice_id"] == node.config.get("voice_id")), None)
            if voice is None:
                return node.route("error", tr("The fixed voice is not in your ElevenLabs account (any more) – pick "
                                              "one in the node."))
            reason = tr("Fixed in the node.")
        else:
            pre = (node.config.get("preselection") or "").strip()
            pool = narrow(voices, pre) if pre else voices
            if mode == "auto":
                node.progress(tr("picks a voice …"))
                voice, reason = await self.pick_auto(node, pool or voices, pre)
            else:
                voice = await self.pick_manual(node, pool or voices, pre and not pool)
                if voice is None:
                    return node.route("error", tr("No voice chosen."))
                reason = tr("Chosen by you.")
        self.ctx.storage.set(f"voice:{node.run_id}", voice)
        node.say(kind="voice", data={"voice": voice, "reason": reason},
                 text=tr("Voice: **{name}** ({labels})", name=voice["name"], labels=label_text(voice)))
        node.progress(f"🎙 {voice['name']}")
        # the material goes on with the voice: the next node (e.g. Generate speech) still gets the script
        passed = VOICE_LINES.sub("", material_of(node)).strip()
        return node.route("voice", tr("Voice: {name} – {labels}. {reason}", name=voice["name"],
                                      labels=label_text(voice), reason=reason)
                          + f"\nELEVENLABS_VOICE: {voice['voice_id']} ({voice['name']})"
                          + (f"\n\n---\n{passed}" if passed else ""))

    async def pick_auto(self, node, voices: list[dict], pre: str) -> tuple[dict, str]:
        listing = "\n".join(f"{v['voice_id']} | {v['name']} | {label_text(v)} | {v.get('description', '')}"
                            for v in voices[:120])
        material = "\n\n".join(x for x in (node.instructions, material_of(node)) if x)[:6000]
        prompt = (f"Pick the ONE voice that fits best to speak this material – its mood, audience, language and "
                  f"the speaker it needs.\nPreselection by the user: {pre or '(none)'}\n\n"
                  f"VOICES (id | name | labels | description):\n{listing}\n\nMATERIAL:\n{material}\n\n"
                  'Answer only JSON: {"voice_id": "...", "reason": "one short sentence in the material\'s language"}')
        try:
            data = json_in(await self.ctx.ai.ask(prompt, system="You cast voices for audio productions.")) or {}
        except Exception as exc:  # noqa: BLE001 - no AI: the first voice of the preselection
            self.ctx.log.error(f"auto voice: {exc}")
            data = {}
        voice = next((v for v in voices if v["voice_id"] == data.get("voice_id")), None)
        if voice is None:
            return voices[0], self.ctx.tr("The first voice of the preselection (the AI gave no usable answer).")
        return voice, str(data.get("reason") or "")

    async def pick_manual(self, node, voices: list[dict], nothing_matched: bool) -> dict | None:
        tr = self.ctx.tr
        shown = voices[:40]
        title = (tr("Nothing matched the preselection – all voices:") if nothing_matched else
                 tr("{n} voices – listen to the samples, then answer with a number or a name.", n=len(shown)))
        node.say(kind="voices", data={"voices": shown, "title": title},
                 text="\n".join(f"{i}. {v['name']} – {label_text(v)}" for i, v in enumerate(shown, 1)))
        options = [v["name"] for v in shown] if len(shown) <= 6 else []
        question = tr("Which voice should speak? (number or name)")
        for _ in range(3):
            node.progress(tr("✋ waits for your choice"))
            answer = (await node.ask(question, options)).strip()
            voice = await self.match(answer, shown)
            if voice is not None:
                return voice
            question = tr("“{answer}” is none of the voices – please answer with a number from 1 to {n} or a "
                          "name.", answer=answer[:60], n=len(shown))
        return None

    async def match(self, answer: str, voices: list[dict]) -> dict | None:
        a = answer.lower().strip(" .!#")
        if a.isdigit() and 1 <= int(a) <= len(voices):
            return voices[int(a) - 1]
        for test in (lambda v: v["name"].lower() == a, lambda v: v["name"].lower().split(" ")[0] == a.split(" ")[0],
                     lambda v: a and a in v["name"].lower()):
            hits = [v for v in voices if test(v)]
            if len(hits) == 1:
                return hits[0]
        if len(a) < 3:
            return None
        listing = "\n".join(f"{i}. {v['name']} – {label_text(v)}" for i, v in enumerate(voices, 1))
        try:   # "the deep male one" → the AI maps it
            data = json_in(await self.ctx.ai.ask(
                f"The user picks a voice from this list:\n{listing}\n\nTheir answer: {answer}\n\n"
                'Which one do they mean? Answer only JSON: {"number": N} – or {"number": 0} if it is unclear.')) or {}
            n = int(data.get("number") or 0)
        except Exception:  # noqa: BLE001
            return None
        return voices[n - 1] if 1 <= n <= len(voices) else None

    # ================================================================== 🔊 Generate speech
    async def speak(self, node):
        tr = self.ctx.tr
        cfg = node.config
        try:
            client = self.voices.client()
        except ElevenLabsError as exc:
            return node.route("error", str(exc))
        voice_id = (cfg.get("voice_id") or "").strip()
        if not voice_id:
            for h in reversed(node.handovers):
                m = VOICE_LINE.search(h.get("text") or "")
                if m:
                    voice_id = m.group(1)
                    break
        if not voice_id:
            voice_id = (self.ctx.storage.get(f"voice:{node.run_id}") or {}).get("voice_id", "")
        if not voice_id:
            return node.route("error", tr("No voice: put “Choose voice” before this node or pick a voice in it."))
        voice = next((v for v in self.voices.cached() if v["voice_id"] == voice_id), {"voice_id": voice_id,
                                                                                       "name": voice_id})
        emotions = bool(cfg.get("emotions"))
        model = V3 if emotions else (cfg.get("model") or "eleven_multilingual_v2")

        node.progress(tr("writes the spoken text …"))
        try:
            segments = await self.segments(node, emotions)
        except Exception as exc:  # noqa: BLE001
            return node.route("error", tr("The AI could not prepare the text: {error}", error=exc))
        if not segments:
            return node.route("error", tr("There is nothing to speak in what came in."))
        parts = [(name, piece) for name, text in segments for piece in split_text(text, MODELS[model])]
        need = sum(len(p) for _, p in parts)
        try:
            sub = await client.subscription()
        except ElevenLabsError as exc:
            if exc.kind in ("invalid_key", "quota"):
                return node.route("error", tr("ElevenLabs: {error}", error=exc))
            sub = None   # the key may not read the subscription – ElevenLabs says so when it runs out
        if sub and sub["character_limit"] and need > sub["left"]:
            return node.route("error", tr("Not enough ElevenLabs credits: the text needs about {need} characters, "
                                          "{left} are left (plan {tier}).", need=f"{need:,}", left=f"{sub['left']:,}",
                                          tier=sub["tier"] or "?"))

        folder = self.folder(node)
        ext = EXT.get(cfg.get("output_format", "mp3").split("_")[0], ".mp3")
        files, note = [], ""
        for i, (name, text) in enumerate(parts, 1):
            node.progress(tr("speaks part {i} of {n} …", i=i, n=len(parts)))
            if model != V3:
                text = TAGS.sub("", text).strip()
            try:
                audio = await client.speech(voice_id, text, model=model, output_format=cfg.get("output_format")
                                            or "mp3_44100_128", language=(cfg.get("language") or "").strip())
            except ElevenLabsError as exc:
                if model == V3 and exc.kind in ("model", "voice", "other") and exc.status in (400, 422):
                    model = "eleven_multilingual_v2"   # the voice can't speak v3: without the tags
                    note = tr("This voice can't speak Eleven v3 – spoken with Multilingual v2, without emotion tags.")
                    text = TAGS.sub("", text).strip()
                    try:
                        audio = await client.speech(voice_id, text, model=model,
                                                    output_format=cfg.get("output_format") or "mp3_44100_128",
                                                    language=(cfg.get("language") or "").strip())
                    except ElevenLabsError as exc2:
                        return self.failed(node, exc2, files)
                else:
                    return self.failed(node, exc, files)
            if ext == ".wav" and not audio.startswith(b"RIFF"):
                audio = wav_from_pcm(audio, int((cfg.get("output_format") or "pcm_44100").split("_")[1]))
            path = unique(folder / f"{node.run_id:04d}-{i:02d}-{slug(name)}{ext}")
            path.write_bytes(audio)
            files.append({"path": str(path), "text": text, "note": f"{len(text):,} " + tr("characters")})
        node.say(kind="audio", data={"title": tr("{n} audio files · {voice}", n=len(files), voice=voice["name"]),
                                     "files": files},
                 text="\n".join(f["path"] for f in files) + (f"\n\n{note}" if note else ""))
        listing = "\n".join(f"- {f['path']}  ({_short(f['text'], 80)})" for f in files)
        return node.route("files", tr("{n} audio files with the voice {voice}:", n=len(files), voice=voice["name"])
                          + f"\n{listing}" + (f"\n\n{note}" if note else "")
                          + "\n\nAUDIO_FILES:\n" + "\n".join(f["path"] for f in files))

    def failed(self, node, exc: ElevenLabsError, files: list[dict]):
        tr = self.ctx.tr
        done = (tr(" Already made: {files}", files=", ".join(Path(f["path"]).name for f in files)) if files else "")
        why = {"quota": tr("Not enough ElevenLabs credits."), "invalid_key": tr("ElevenLabs refused the API key."),
               "permissions": tr("The API key is missing a permission (Text to Speech)."),
               "voice": tr("ElevenLabs doesn't know the voice.")}.get(exc.kind, "")
        return node.route("error", f"{why} {exc}".strip() + done)

    async def segments(self, node, emotions: bool) -> list[tuple[str, str]]:
        """The AI picks what is spoken and splits it into parts (scenes, speakers …)."""
        material = VOICE_LINES.sub("", material_of(node)).strip()
        tags = (f"Add Eleven v3 audio tags where they help the delivery, sparingly (e.g. {', '.join(EMOTION_TAGS)}); "
                "tags are English words in square brackets right before the words they colour. "
                if emotions else "Do NOT add any tags, brackets or stage directions. ")
        prompt = ("Prepare the spoken audio for this material. Take only what a speaker says out loud (e.g. the "
                  "narration / voice-over of a video script) – no scene descriptions, headings, camera notes or "
                  "markup. Keep the language and the wording; fix only what is hard to speak (numbers, abbreviations, "
                  f"symbols). {tags}Split it into parts in the material's order (one per scene or section), each with "
                  "a short English name.\n"
                  + (f"\nINSTRUCTIONS FROM THE USER:\n{node.instructions}\n" if node.instructions else "")
                  + f"\nMATERIAL:\n{material[:30000]}\n\n"
                  'Answer only JSON: {"parts": [{"name": "intro", "text": "…"}, …]}')
        data = json_in(await self.ctx.ai.ask(prompt, system="You prepare scripts for voice recordings.",
                                             model="sonnet"))
        parts = data.get("parts") if isinstance(data, dict) else data if isinstance(data, list) else None
        if not isinstance(parts, list):
            raise ValueError("no parts in the AI's answer")
        out = []
        for p in parts:
            if isinstance(p, dict) and str(p.get("text") or "").strip():
                text = str(p["text"]).strip()
                out.append((str(p.get("name") or f"part-{len(out) + 1}"), text if emotions else TAGS.sub("", text)))
        return out

    def folder(self, node) -> Path:
        sub = (node.config.get("folder") or "audio").strip() or "audio"
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else self.ctx.data_dir
        target = Path(sub).expanduser() if Path(sub).expanduser().is_absolute() else base / sub
        target.mkdir(parents=True, exist_ok=True)
        return target


SYNONYMS = {"weiblich": "female", "männlich": "male", "frau": "female", "mann": "male", "deutsch": "german",
            "englisch": "english", "jung": "young", "alt": "old", "ruhig": "calm", "tief": "deep",
            "britisch": "british", "amerikanisch": "american", "erzähler": "narration", "erzählerin": "narration"}


def narrow(voices: list[dict], pre: str) -> list[dict]:
    """Voices whose name / labels / description have every word of the preselection (German words too):
    "female, German, warm"."""
    words = [SYNONYMS.get(w, w) for w in re.split(r"[,;/\s]+", pre.lower()) if len(w) > 1]
    out = []
    for v in voices:
        hay = " ".join([v["name"], label_text(v), v.get("description", "")]).lower()
        tokens = set(re.findall(r"[a-zäöüß0-9]+", hay))
        if all(w in tokens or (len(w) >= 5 and w in hay) for w in words):
            out.append(v)
    return out


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        p = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not p.exists():
            return p
    return path


def wav_from_pcm(pcm: bytes, rate: int) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"
