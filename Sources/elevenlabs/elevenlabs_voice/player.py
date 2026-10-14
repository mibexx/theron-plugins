"""Plays audio for the ▶ buttons in the chat – with what the computer has (no extra packages): macOS afplay,
Windows MCI (winmm), Linux ffplay / mpg123 / PipeWire / PulseAudio. One sound at a time; a URL (a voice's sample)
is downloaded once into the plugin's cache folder."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

ALIAS = "theron_elevenlabs"


class Player:
    def __init__(self, cache: Path, on_change: Callable[[], None] | None = None):
        self.cache = cache
        self.on_change = on_change or (lambda: None)   # ▶ ↔ ■ in the chat
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._current = ""
        self._serial = 0

    # ------------------------------------------------------------------ files
    def local(self, src: str) -> Path:
        if src.startswith(("http://", "https://")):
            ext = Path(urllib.parse.urlparse(src).path).suffix[:6] or ".mp3"
            target = self.cache / (hashlib.sha1(src.encode()).hexdigest()[:20] + ext)
            if not target.exists() or not target.stat().st_size:
                self.cache.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(src, headers={"User-Agent": "Theron ElevenLabs plugin"})
                with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
                    part = target.with_suffix(target.suffix + ".part")
                    part.write_bytes(r.read())
                    part.replace(target)
            return target
        return Path(src).expanduser()

    # ------------------------------------------------------------------ state
    def playing(self) -> str:
        with self._lock:
            if not self._current:
                return ""
            if self._proc is not None and self._proc.poll() is not None:
                return ""
            if sys.platform.startswith("win") and _mci_mode() != "playing":
                return ""
            return self._current

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()
        self.on_change()

    def _stop_locked(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        if sys.platform.startswith("win") and self._current:
            _mci(f"close {ALIAS}")
        self._proc, self._current = None, ""

    def toggle(self, src: str) -> bool:
        """▶ plays ``src``, ■ (a click on the one playing) stops it. True = plays now."""
        if self.playing() == src:
            self.stop()
            return False
        self.play(src)
        return True

    def play(self, src: str) -> None:
        path = self.local(src)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        with self._lock:
            self._stop_locked()
            if sys.platform == "darwin":
                self._proc = subprocess.Popen(["afplay", str(path)])
            elif sys.platform.startswith("win"):
                kind = "mpegvideo" if path.suffix.lower() == ".mp3" else "waveaudio"
                if _mci(f'open "{path}" type {kind} alias {ALIAS}') or _mci(f"play {ALIAS}"):
                    _mci(f"close {ALIAS}")
                    raise RuntimeError("Windows can't play the file (MCI)")
            else:
                cmd = linux_command(path)
                if cmd is None:
                    raise RuntimeError("No audio player found – install ffmpeg (ffplay) or mpg123.")
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._current = src
            self._serial += 1
            serial = self._serial
        self.on_change()
        threading.Thread(target=self._watch, args=(serial,), daemon=True).start()

    def _watch(self, serial: int) -> None:
        """When the sound ends by itself, ■ turns back into ▶."""
        while True:
            time.sleep(0.5)
            with self._lock:
                if serial != self._serial or not self._current:
                    return
            if not self.playing():
                with self._lock:
                    if serial == self._serial:
                        self._stop_locked()
                self.on_change()
                return


def linux_command(path: Path) -> list[str] | None:
    for cmd in (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"], ["pw-play"], ["paplay"]):
        if shutil.which(cmd[0]):
            return [*cmd, str(path)]
    return None


def _mci(command: str) -> int:
    import ctypes
    return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)


def _mci_mode() -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(64)
    ctypes.windll.winmm.mciSendStringW(f"status {ALIAS} mode", buf, 64, None)
    return buf.value


def _ssl():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()
