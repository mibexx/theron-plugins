"""A small Chrome DevTools Protocol client: starts the user's own Chrome / Chromium / Edge / Brave with a profile of the
plugin and drives it over the DevTools websocket (``websockets`` – part of every Theron build). No Playwright, no
WebDriver: the browser runs without automation switches, like one a person opened."""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATES = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Chromium.app/Contents/MacOS/Chromium",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
               "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    "Windows": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "Linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
              "brave-browser"],
}


class CdpError(RuntimeError):
    pass


def find_browser(configured: str = "") -> str:
    """The browser binary: the configured one, else the first installed of CANDIDATES ('' = none)."""
    for c in ([configured] if configured.strip() else []) + CANDIDATES.get(platform.system(), []):
        c = os.path.expandvars(os.path.expanduser(c.strip()))
        if os.path.isabs(c):
            if os.path.isfile(c):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    return ""


def has_display() -> bool:
    if platform.system() != "Linux":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def in_container() -> bool:
    return os.path.exists("/.dockerenv") or bool(os.environ.get("KUBERNETES_SERVICE_HOST")) \
        or os.environ.get("THERON_CHROME_NO_SANDBOX") == "1"


class Session:
    """One page (tab) – commands go to its flattened target session."""

    def __init__(self, browser: "Browser", session_id: str, target_id: str):
        self.browser, self.id, self.target_id = browser, session_id, target_id
        self.events: asyncio.Queue = asyncio.Queue()

    async def send(self, method: str, params: dict | None = None, timeout: float = 30):
        return await self.browser.send(method, params, session=self.id, timeout=timeout)

    async def eval(self, expression: str, timeout: float = 30):
        r = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                 "awaitPromise": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            raise CdpError(str(r["exceptionDetails"].get("exception", {}).get("description")
                               or r["exceptionDetails"].get("text"))[:300])
        return (r.get("result") or {}).get("value")

    async def close(self) -> None:
        try:
            await self.browser.send("Target.closeTarget", {"targetId": self.target_id}, timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self.browser.sessions.pop(self.id, None)


class Browser:
    """``async with Browser(path, profile, headless=…) as b: page = await b.new_page()``"""

    def __init__(self, path: str, profile: Path, *, headless: bool = True, window: str = "offscreen",
                 language: str = "", size: tuple[int, int] = (1440, 900)):
        self.path, self.profile, self.headless, self.window = path, Path(profile), headless, window
        self.language, self.size = language, size
        self.proc = None
        self.ws = None
        self.ids = itertools.count(1)
        self.waiting: dict[int, asyncio.Future] = {}
        self.sessions: dict[str, Session] = {}
        self.reader = None
        self.version: dict = {}

    def args(self, port_file_dir: Path) -> list[str]:
        w, h = self.size
        a = [self.path, f"--user-data-dir={self.profile}", "--remote-debugging-port=0",
             "--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled",
             "--disable-features=Translate,OptimizationHints,MediaRouter", "--password-store=basic",
             "--use-mock-keychain", f"--window-size={w},{h}", "--hide-crash-restore-bubble"]
        if self.language:
            a.append(f"--lang={self.language}")
        if self.headless:
            a.append("--headless=new")
        elif self.window == "offscreen":
            a.append("--window-position=-32000,-32000")
        if platform.system() == "Linux" and in_container():
            a += ["--no-sandbox", "--disable-dev-shm-usage"]
        a.append("about:blank")
        return a

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.stop()

    async def start(self, timeout: float = 30) -> None:
        import websockets
        self.profile.mkdir(parents=True, exist_ok=True)
        port_file = self.profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        kw = {}
        if platform.system() == "Windows":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["start_new_session"] = True
        self.proc = subprocess.Popen(self.args(self.profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, **kw)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if self.proc.poll() is not None:
                raise CdpError(f"The browser quit at once (exit code {self.proc.returncode}) – is the profile "
                               f"in use by another browser window? {self.profile}")
            if port_file.is_file():
                lines = port_file.read_text().split("\n")
                if len(lines) >= 2 and lines[0].strip().isdigit():
                    break
            if loop.time() > deadline:
                await self.stop()
                raise CdpError("The browser didn't open its DevTools port in time.")
            await asyncio.sleep(0.1)
        url = f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}"
        self.ws = await websockets.connect(url, max_size=256 * 1024 * 1024, ping_interval=None, open_timeout=15)
        self.reader = asyncio.create_task(self._read())
        self.version = await self.send("Browser.getVersion")

    async def stop(self) -> None:
        ws = self.ws
        if ws is not None:
            try:
                await self.send("Browser.close", timeout=5)
            except Exception:  # noqa: BLE001
                pass
            self.ws = None
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self.reader:
            self.reader.cancel()
            self.reader = None
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            for _ in range(30):
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            if proc.poll() is None:
                try:
                    if platform.system() == "Windows":
                        proc.kill()
                    else:
                        os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self.waiting.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CdpError(msg["error"].get("message", "CDP error")))
                        else:
                            fut.set_result(msg.get("result") or {})
                elif msg.get("sessionId") in self.sessions:
                    self.sessions[msg["sessionId"]].events.put_nowait(msg)
        except Exception:  # noqa: BLE001 – connection gone
            pass
        for fut in self.waiting.values():
            if not fut.done():
                fut.set_exception(CdpError("The browser connection closed."))
        self.waiting.clear()

    async def send(self, method: str, params: dict | None = None, *, session: str | None = None,
                   timeout: float = 30):
        if self.ws is None:
            raise CdpError("The browser is not running.")
        i = next(self.ids)
        msg = {"id": i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        fut = asyncio.get_running_loop().create_future()
        self.waiting[i] = fut
        await self.ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.waiting.pop(i, None)

    async def new_page(self) -> Session:
        target = (await self.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        sid = (await self.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        s = Session(self, sid, target)
        self.sessions[sid] = s
        return s

    async def show(self, target_id: str, w: int = 1280, h: int = 900) -> None:
        """Brings the (off-screen) window of a page onto the screen."""
        win = await self.send("Browser.getWindowForTarget", {"targetId": target_id})
        await self.send("Browser.setWindowBounds", {"windowId": win["windowId"],
                                                    "bounds": {"left": 80, "top": 60, "width": w, "height": h,
                                                               "windowState": "normal"}})
        await self.send("Target.activateTarget", {"targetId": target_id})
