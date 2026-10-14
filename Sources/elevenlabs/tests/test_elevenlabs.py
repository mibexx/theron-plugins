"""ElevenLabs plugin against a fake ElevenLabs and a fake AI – run with Theron's Python:
    QT_QPA_PLATFORM=offscreen python -m pytest Sources/elevenlabs/tests"""
import asyncio
import json
import os
import time
import urllib.parse
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent

from theron import plugins  # noqa: E402
from theron.engine.orchestrator import Engine  # noqa: E402
from theron.plugins.http import Response  # noqa: E402
from theron.store import Store  # noqa: E402

VOICES = [
    {"voice_id": "Rach000000000001", "name": "Rachel", "category": "premade", "preview_url": "https://x/rachel.mp3",
     "labels": {"gender": "female", "age": "young", "accent": "american", "use_case": "narration"},
     "description": "Calm, warm narrator", "high_quality_base_model_ids": ["eleven_v3"]},
    {"voice_id": "Adam000000000002", "name": "Adam", "category": "premade", "preview_url": "https://x/adam.mp3",
     "labels": {"gender": "male", "age": "middle aged", "accent": "american", "descriptive": "deep"},
     "description": "Deep voice"},
    {"voice_id": "Hann000000000003", "name": "Hanna", "category": "cloned", "preview_url": "",
     "labels": {"gender": "female", "accent": "german", "language": "de"}, "description": "Deutsche Sprecherin"},
]


class FakeElevenLabs:
    def __init__(self):
        self.key = "good"
        self.used, self.limit = 1000, 10000
        self.calls = []
        self.subscription_allowed = True
        self.v3_voices = {"Rach000000000001", "Hann000000000003"}

    async def request(self, method, url, *, params=None, headers=None, json=None, **kw):
        path = urllib.parse.urlparse(url).path
        self.calls.append((method, path, dict(params or {}), json))

        def answer(status, body):
            raw = body if isinstance(body, bytes) else __import__("json").dumps(body).encode()
            return Response(url, status, {}, raw)
        if (headers or {}).get("xi-api-key") != self.key:
            return answer(401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
        if path == "/v1/user/subscription":
            if not self.subscription_allowed:
                return answer(401, {"detail": {"status": "missing_permissions",
                                               "message": "The API key is missing the permission user_read"}})
            return answer(200, {"tier": "creator", "character_count": self.used, "character_limit": self.limit})
        if path == "/v2/voices":
            return answer(200, {"voices": VOICES, "has_more": False})
        if path.startswith("/v1/text-to-speech/"):
            voice = path.rsplit("/", 1)[1]
            if json["model_id"] == "eleven_v3" and voice not in self.v3_voices:
                return answer(400, {"detail": {"status": "model_not_supported",
                                               "message": "This voice does not support model eleven_v3"}})
            if self.used + len(json["text"]) > self.limit:
                return answer(401, {"detail": {"status": "quota_exceeded", "message": "You exceeded your quota"}})
            self.used += len(json["text"])
            return answer(200, b"ID3audio:" + json["text"].encode())
        return answer(404, {"detail": "not found"})


class FakeAi:
    def __init__(self):
        self.prompts = []
        self.voice = "Adam000000000002"

    async def ask(self, prompt, system="", model="haiku"):
        self.prompts.append(prompt)
        if "Prepare the spoken audio" in prompt:
            tagged = "with Eleven v3 audio tags" not in prompt and "Add Eleven v3" in prompt
            return json.dumps({"parts": [
                {"name": "Intro", "text": ("[excited] " if tagged else "") + "Welcome to the show."},
                {"name": "Outro scene", "text": "Thanks for watching."}]})
        if "cast" in system or "Pick the ONE voice" in prompt:
            return f'```json\n{{"voice_id": "{self.voice}", "reason": "A deep voice for a serious topic."}}\n```'
        if "Which one do they mean" in prompt:
            return '{"number": 2}' if "deep" in prompt.lower() else '{"number": 0}'
        return "{}"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERON_DATA", str(tmp_path / "data"))
    store = Store(tmp_path / "t.db")
    pm = plugins.reset(tmp_path / "plugins")
    pm.store = store
    pm.install(plugins.pack(HERE, tmp_path / "elevenlabs.theronplugin"))
    pm.loaded = False
    pm.load(store, "desktop")
    info = pm.plugins["elevenlabs"]
    assert info.state == "loaded", info.error
    ctx = pm.ctx("elevenlabs")
    ctx.http = fake = FakeElevenLabs()
    ctx.ai = ai = FakeAi()
    ctx.settings.update({"api_key": "good"})
    return store, pm, ctx, fake, ai, tmp_path


def make_run(store, pm, tmp, voice_cfg=None, speech_cfg=None):
    v, s = pm.node("elevenlabs/voice"), pm.node("elevenlabs/speech")
    voice_cfg = {**v.defaults(), **(voice_cfg or {})}
    speech_cfg = {**s.defaults(), **(speech_cfg or {})}
    pid = store.save("process", {"name": "Video", "start": "v", "steps": [
        {"id": "v", "type": "plugin", "plugin_node": v.id, "plugin_config": voice_cfg, "plugin_outputs": "ports",
         "plugin_ports": v.ports(voice_cfg), "plugin_routes": {"voice": "s", "error": "end"}},
        {"id": "s", "type": "plugin", "plugin_node": s.id, "plugin_config": speech_cfg, "plugin_outputs": "ports",
         "plugin_ports": s.ports(speech_cfg), "plugin_routes": {"files": "end", "error": "end"}}]})
    proj = store.save("project", {"name": "Video", "workspace": str(tmp / "ws"), "process_id": pid})
    (tmp / "ws").mkdir(exist_ok=True)
    ctrl = Engine(store).controller(store.create_run(proj, "Video about owls"))
    store.update_run(ctrl.run_id, inbox={"v": [{"id": "h1", "from": "Writer", "agent": "Writer",
                                                "text": "SCRIPT\nScene 1 (drone shot)\nNARRATOR: Welcome to the show."}]})
    return ctrl


def plugin_events(store, run_id):
    return [e for e in store.events(run_id) if e["type"] == "plugin_message"]


async def answer_when_asked(store, ctrl, answers):
    """Answers the node's questions in the chat, one after the other."""
    asked = []
    for text in answers:
        for _ in range(500):
            pending = store.run(ctrl.run_id).get("pending_input")
            if pending and pending["request_id"] not in asked:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("no question came")
        asked.append(pending["request_id"])
        ctrl.answer(pending["request_id"], text, "app")
    return asked


# ------------------------------------------------------------------ settings: Test
def test_the_test_button_checks_the_key_and_shows_the_credits(env):
    store, pm, ctx, fake, ai, tmp = env
    (button,) = pm.settings_buttons_for("elevenlabs")
    assert button.label == "Test"
    run = lambda values: asyncio.run(button.run(values))  # noqa: E731
    assert run({"api_key": ""}) == (False, "Enter the API key first.")
    ok, text = run({"api_key": "good"})
    assert ok and "plan creator" in text and "9,000 of 10,000 characters left" in text and "3 voices" in text
    assert [v["name"] for v in ctx.voices.cached()] == ["Hanna", "Adam", "Rachel"]   # own voices first
    ok, text = run({"api_key": "wrong"})
    assert not ok and "Invalid API key" in text
    fake.subscription_allowed = False
    ok, text = run({"api_key": "good"})
    assert ok and "can't be checked" in text


def test_the_test_button_in_the_settings_dialog(env):
    from PySide6.QtWidgets import QApplication
    from theron.ui.plugins_ui import PluginSettingsDialog
    app = QApplication.instance() or QApplication([])
    store, pm, ctx, fake, ai, tmp = env
    dlg = PluginSettingsDialog(store, pm.plugins["elevenlabs"])
    assert [b.text() for b in dlg.button_widgets] == ["Test"]
    dlg.inputs["api_key"][1].setText("wrong")
    dlg.button_widgets[0].click()
    deadline = time.time() + 5
    while time.time() < deadline and not dlg.result.text().startswith(("✔", "✖")):
        app.processEvents()
        time.sleep(0.02)
    assert dlg.result.text().startswith("✖") and "Invalid API key" in dlg.result.text()


# ------------------------------------------------------------------ 🎙 Choose voice
def test_fixed_voice(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    asyncio.run(ctrl._execute(0, "make audio"))
    inbox = store.run(ctrl.run_id)["inbox"]["s"]
    assert "ELEVENLABS_VOICE: Rach000000000001 (Rachel)" in inbox[0]["text"]
    (ev,) = plugin_events(store, ctrl.run_id)
    assert ev["kind"] == "voice" and ev["data"]["voice"]["name"] == "Rachel"
    assert ctx.storage.get(f"voice:{ctrl.run_id}")["voice_id"] == "Rach000000000001"


def test_fixed_voice_that_is_gone_goes_to_error(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Gone"})
    out = asyncio.run(ctrl._execute(0, "make audio"))
    assert "Output “Error”" in out and "s" not in (store.run(ctrl.run_id).get("inbox") or {})


def test_automatic_voice_by_mood_and_preselection(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "auto", "preselection": "male"})
    asyncio.run(ctrl._execute(0, "make audio"))
    prompt = next(p for p in ai.prompts if "Pick the ONE voice" in p)
    assert "Adam" in prompt and "Rachel" not in prompt and "Welcome to the show" in prompt   # only the preselection
    (ev,) = plugin_events(store, ctrl.run_id)
    assert ev["data"]["voice"]["name"] == "Adam" and ev["data"]["reason"] == "A deep voice for a serious topic."


def test_manual_voice_in_the_chat(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "manual", "preselection": "weiblich"})

    async def main():
        job = asyncio.ensure_future(ctrl._execute(0, "make audio"))
        await answer_when_asked(store, ctrl, ["Klaus", "2"])
        return await job
    asyncio.run(main())
    evs = plugin_events(store, ctrl.run_id)
    assert evs[0]["kind"] == "voices" and [v["name"] for v in evs[0]["data"]["voices"]] == ["Hanna", "Rachel"]
    asks = [e for e in store.events(ctrl.run_id) if e["type"] == "input_request"]
    assert asks[0]["options"] == ["Hanna", "Rachel"] and "Which voice" in asks[0]["question"]
    assert "“Klaus” is none of the voices" in asks[1]["question"]
    assert evs[-1]["kind"] == "voice" and evs[-1]["data"]["voice"]["name"] == "Rachel"


def test_manual_answer_in_own_words(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "manual"})

    async def main():
        job = asyncio.ensure_future(ctrl._execute(0, "make audio"))
        await answer_when_asked(store, ctrl, ["the deep one please"])
        return await job
    asyncio.run(main())
    assert plugin_events(store, ctrl.run_id)[-1]["data"]["voice"]["name"] == "Adam"


def test_no_key_goes_to_error(env):
    store, pm, ctx, fake, ai, tmp = env
    ctx.settings.set("api_key", "")
    ctrl = make_run(store, pm, tmp)
    out = asyncio.run(ctrl._execute(0, "x"))
    assert "Output “Error”" in out and "No ElevenLabs API key" in out


# ------------------------------------------------------------------ 🔊 Generate speech
def run_both(store, ctrl):
    asyncio.run(ctrl._execute(0, "make audio"))
    return asyncio.run(ctrl._execute(1, "make audio"))


def test_speech_with_emotions_writes_the_files_and_hands_on_the_paths(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    out = run_both(store, ctrl)
    assert "Output “Audio files”" in out
    tts = [c for c in fake.calls if c[1].startswith("/v1/text-to-speech/")]
    assert [c[3]["model_id"] for c in tts] == ["eleven_v3", "eleven_v3"]
    assert tts[0][3]["text"] == "[excited] Welcome to the show." and tts[0][2]["output_format"] == "mp3_44100_128"
    files = sorted((tmp / "ws" / "audio").iterdir())
    assert [f.name for f in files] == [f"{ctrl.run_id:04d}-01-intro.mp3", f"{ctrl.run_id:04d}-02-outro-scene.mp3"]
    assert files[0].read_bytes() == b"ID3audio:[excited] Welcome to the show."
    ev = plugin_events(store, ctrl.run_id)[-1]
    assert ev["kind"] == "audio" and [f["path"] for f in ev["data"]["files"]] == [str(f) for f in files]
    run = store.run(ctrl.run_id)
    result = next(e for e in store.events(ctrl.run_id) if e["type"] == "plugin" and e["node"] == "elevenlabs/speech")
    assert result["ok"] and result["outputs"] == ["files"]
    assert run["steps"]["s"]["status"] == "done"


def test_a_voice_without_v3_is_spoken_without_tags(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Adam000000000002"})
    run_both(store, ctrl)
    tts = [c[3] for c in fake.calls if c[1].startswith("/v1/text-to-speech/")]
    assert [t["model_id"] for t in tts] == ["eleven_v3", "eleven_multilingual_v2", "eleven_multilingual_v2"]
    assert tts[1]["text"] == "Welcome to the show."
    assert "can't speak Eleven v3" in plugin_events(store, ctrl.run_id)[-1]["text"]


def test_without_emotions_no_tags_and_the_chosen_model(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"},
                    {"emotions": False, "model": "eleven_flash_v2_5", "folder": "vo", "output_format": "pcm_44100"})
    run_both(store, ctrl)
    tts = [c[3] for c in fake.calls if c[1].startswith("/v1/text-to-speech/")]
    assert {t["model_id"] for t in tts} == {"eleven_flash_v2_5"} and "[" not in tts[0]["text"]
    prompt = next(p for p in ai.prompts if "Prepare the spoken audio" in p)
    assert "Do NOT add any tags" in prompt
    files = sorted((tmp / "ws" / "vo").iterdir())
    assert files[0].suffix == ".wav" and files[0].read_bytes()[:4] == b"RIFF"


def test_speech_gets_the_orchestrators_assignment_and_the_script_through_choose_voice(env):
    """No instructions in the node: the step's assignment from the orchestrator and the script the writer handed to
    Choose voice both reach Generate speech (the hand-over of Choose voice alone is just the voice)."""
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    asyncio.run(ctrl._execute(0, "pick the narrator"))
    asyncio.run(ctrl._execute(1, "Speak only the NARRATOR lines, calm and slow"))
    prompt = next(p for p in ai.prompts if "Prepare the spoken audio" in p)
    assert "Speak only the NARRATOR lines, calm and slow" in prompt
    assert "NARRATOR: Welcome to the show." in prompt and "ELEVENLABS_VOICE" not in prompt.split("MATERIAL:")[1]


def test_not_enough_credits_goes_to_error_before_speaking(env):
    store, pm, ctx, fake, ai, tmp = env
    fake.used = fake.limit - 10
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    out = run_both(store, ctrl)
    assert "Output “Error”" in out and "Not enough ElevenLabs credits" in out
    assert not [c for c in fake.calls if c[1].startswith("/v1/text-to-speech/")]


def test_credits_running_out_while_speaking(env):
    store, pm, ctx, fake, ai, tmp = env
    fake.subscription_allowed = False          # can't check before …
    fake.used = fake.limit - 40                # … and the second part doesn't fit any more
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    out = run_both(store, ctrl)
    assert "Output “Error”" in out and "Not enough ElevenLabs credits" in out and "Already made" in out


def test_speech_without_a_voice(env):
    store, pm, ctx, fake, ai, tmp = env
    ctrl = make_run(store, pm, tmp)
    store.update_run(ctrl.run_id, inbox={"s": [{"id": "h", "from": "W", "agent": "W", "text": "Hello"}]})
    out = asyncio.run(ctrl._execute(1, "x"))
    assert "Output “Error”" in out and "No voice" in out


# ------------------------------------------------------------------ the chat
def test_chat_blocks_paths_and_the_play_button(env, monkeypatch):
    from theron.ui.cockpit import event_html, md_html, open_chat_link
    import importlib
    store, pm, ctx, fake, ai, tmp = env
    P = importlib.import_module(pm.plugins["elevenlabs"].module.__name__ + ".player")
    started = []

    class Proc:
        def __init__(self, cmd, **kw):
            started.append(cmd)
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False
    monkeypatch.setattr(P.subprocess, "Popen", Proc)
    monkeypatch.setattr(P.sys, "platform", "darwin")
    refreshed = []
    ctx.player.on_change = lambda: refreshed.append(1)
    f = tmp / "a.mp3"
    f.write_bytes(b"ID3")
    html = event_html({"type": "plugin_message", "plugin": "elevenlabs", "name": "🔊 Speech", "text": str(f),
                       "kind": "audio", "data": {"title": "1 file", "files": [{"path": str(f), "text": "Hi"}]}})
    assert "▶ a.mp3" in html and "theron-plugin://elevenlabs/play?src=" in html
    md = md_html(f"Done: {f} and /nope/missing.mp3")
    assert md.count("theron-plugin://elevenlabs/play") == 1 and "/nope/missing.mp3" in md
    voices = event_html({"type": "plugin_message", "plugin": "elevenlabs", "name": "🎙", "kind": "voices",
                         "data": {"voices": [{"name": "Rachel", "preview_url": "https://x/r.mp3", "labels": {}}]}})
    assert "Rachel" in voices and "▶ Sample" in voices
    open_chat_link(f"theron-plugin://elevenlabs/play?src={urllib.parse.quote(str(f))}")
    for _ in range(100):
        if started:
            break
        time.sleep(0.02)
    assert started == [["afplay", str(f)]] and ctx.player.playing() == str(f) and refreshed
    assert "■ a.mp3" in event_html({"type": "plugin_message", "plugin": "elevenlabs", "name": "x", "kind": "audio",
                                    "data": {"files": [{"path": str(f)}]}})
    ctx.player.toggle(str(f))
    assert ctx.player.playing() == ""


def test_the_voice_field_lists_the_cached_voices_only_when_fixed(env):
    from theron.plugins.context import field_options, field_visible
    store, pm, ctx, fake, ai, tmp = env
    node = pm.node("elevenlabs/voice")
    field = next(f for f in node.fields if f["key"] == "voice_id")
    assert field_options(field, {}) == []                       # nothing loaded yet
    asyncio.run(ctx.voices.load())
    assert [o["label"] for o in field_options(field, {})][0] == "Hanna – female · german · de"
    assert field_visible(field, {"mode": "fixed"}) and not field_visible(field, {"mode": "manual"})
    speech = pm.node("elevenlabs/speech")
    model = next(f for f in speech.fields if f["key"] == "model")
    assert not field_visible(model, speech.defaults()) and field_visible(model, {"emotions": False})


def test_splitting_long_text(env):
    import importlib
    pm = env[1]
    nodes = importlib.import_module(pm.plugins["elevenlabs"].module.__name__ + ".nodes")
    narrow, split_text = nodes.narrow, nodes.split_text
    text = " ".join(f"Sentence number {i} is here." for i in range(200))
    parts = split_text(text, 500)
    assert all(len(p) <= 500 for p in parts) and " ".join(parts) == text
    assert split_text("x" * 1200, 500) == ["x" * 500, "x" * 500, "x" * 200]
    voices = [{"name": "A", "labels": {"gender": "male"}}, {"name": "B", "labels": {"gender": "female"}}]
    assert [v["name"] for v in narrow(voices, "männlich")] == ["A"]
    assert [v["name"] for v in narrow(voices, "female")] == ["B"]


def test_the_sample_button_next_to_the_voice_field_in_the_editor(env, monkeypatch):
    """▶ next to the voice in the node's panel plays the voice's sample, ■ stops it – the plugin's own player."""
    import importlib

    from PySide6.QtWidgets import QApplication, QPushButton

    from theron.ui import pickers
    from theron.ui.plugins_ui import FieldButtons
    from theron.ui.process_editor import ProcessEditor
    store, pm, ctx, fake, ai, tmp = env
    app = QApplication.instance() or QApplication([])
    P = importlib.import_module(pm.plugins["elevenlabs"].module.__name__ + ".player")
    started = []

    class Proc:
        def __init__(self, cmd, **kw):
            started.append(cmd)
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False
    monkeypatch.setattr(P.subprocess, "Popen", Proc)
    monkeypatch.setattr(P.sys, "platform", "darwin")
    sample = tmp / "rachel.mp3"
    sample.write_bytes(b"ID3")
    monkeypatch.setattr(ctx.player, "local", lambda src: sample if src == "https://x/rachel.mp3" else Path("/nope"))
    asyncio.run(ctx.voices.load())
    pickers.ModelCatalog.refresh = lambda self, *a, **k: None
    pickers.ModelCatalog.init(store)
    ctrl = make_run(store, pm, tmp, {"mode": "fixed", "voice_id": "Rach000000000001"})
    proc = store.get("process", store.get("project", store.run(ctrl.run_id)["project_id"])["process_id"])
    ed = ProcessEditor(store)
    ed.load(proc)
    n = next(x for x in ed.nodes if x.step and x.step["id"] == "v")
    ed.current = n
    ed._show_plugin(n)
    buttons = ed.pl_fields.findChildren(FieldButtons)
    assert len(buttons) == 1   # only the voice field has one (and the speech node's voice field, not shown here)
    button = buttons[0].findChildren(QPushButton)[0]

    def wait(cond):
        for _ in range(200):
            app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False
    assert button.text() == "▶ Sample"
    button.click()
    assert wait(lambda: started) and started == [["afplay", str(sample)]]
    assert wait(lambda: button.text() == "■ Stop")
    button.click()
    assert wait(lambda: button.text() == "▶ Sample") and ctx.player.playing() == ""
    # no voice chosen: the button says so instead of playing
    kind, combo = ed.pl_inputs["voice_id"]
    combo.addItem("–", "")
    combo.setCurrentIndex(combo.count() - 1)
    button.click()
    assert wait(lambda: "Choose a voice first." in buttons[0].result.text())
