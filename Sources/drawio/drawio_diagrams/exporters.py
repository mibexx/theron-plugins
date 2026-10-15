"""The three ways to the PNG (setting “draw.io”):

builtin   the plugin draws it itself (render.py) – nothing to install, works on a slave and in Docker, too
desktop   the installed draw.io app:  draw.io -x -f png -s 2 -b 10 -o out.png in.drawio
docker    draw.io headless in a container (rlespinasse/drawio-desktop-headless), the folder mounted as /data
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_IMAGE = "rlespinasse/drawio-desktop-headless:latest"
TIMEOUT = 180


class ExportError(RuntimeError):
    pass


def find_drawio(setting: str = "") -> str:
    for cand in (setting, os.environ.get("DRAWIO_PATH", ""), "/Applications/draw.io.app/Contents/MacOS/draw.io",
                 str(Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io"),
                 shutil.which("drawio") or "", shutil.which("draw.io") or "", "/usr/bin/drawio", "/opt/drawio/drawio",
                 r"C:\Program Files\draw.io\draw.io.exe"):
        if cand and Path(cand).expanduser().is_file():
            return str(Path(cand).expanduser())
    return ""


def resolve_app(path: str) -> str:
    """What the user picked → the program: a macOS .app bundle → its executable inside."""
    p = Path(path).expanduser()
    if p.suffix == ".app" and p.is_dir():
        inner = sorted((p / "Contents" / "MacOS").glob("*"))
        named = [q for q in inner if q.name.lower().replace(".", "") == "drawio"]
        return str((named or inner or [p])[0])
    return str(p)


def desktop_version(exe: str) -> str:
    """The version of a draw.io program – raises ExportError if it isn't one that works."""
    if not exe or not Path(exe).is_file():
        raise ExportError(f"not a program: {exe}")
    r = _run([exe, "--version"], timeout=60)
    out = (r.stdout or "").strip().splitlines()
    version = next((line.strip() for line in out if line.strip()[:1].isdigit()), "")
    if r.returncode != 0 or not version:
        raise ExportError(f"{Path(exe).name} doesn't answer like draw.io: "
                          + ((r.stderr or r.stdout or "").strip()[-200:] or f"exit {r.returncode}"))
    return version


def find_docker() -> str:
    """docker – also where an app started from the Finder doesn't look (its PATH is short)."""
    for cand in (shutil.which("docker") or "", "/usr/local/bin/docker", "/opt/homebrew/bin/docker",
                 "/Applications/Docker.app/Contents/Resources/bin/docker", "/usr/bin/docker",
                 r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"):
        if cand and Path(cand).is_file():
            return cand
    return ""


def _run(cmd: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(
        ("/usr/local/bin", "/opt/homebrew/bin", "/Applications/Docker.app/Contents/Resources/bin"))}
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"{Path(cmd[0]).name} took longer than {timeout} s") from exc
    except OSError as exc:
        raise ExportError(str(exc)) from exc


def _cli_args(scale: float) -> list[str]:
    return ["-x", "-f", "png", "-s", f"{scale:g}", "-b", "10"]


def desktop(drawio: Path, png: Path, scale: float, app: str = "") -> None:
    exe = find_drawio(app)
    if not exe:
        raise ExportError("the draw.io desktop app is not installed (or set its path in the plugin settings)")
    r = _run([exe, *_cli_args(scale), "-o", str(png), str(drawio)])
    if not png.is_file():
        raise ExportError(f"draw.io made no PNG: {(r.stderr or r.stdout).strip()[-300:]}")


def docker_ready(image: str) -> tuple[bool, str]:
    exe = find_docker()
    if not exe:
        return False, "Docker is not installed"
    r = _run([exe, "info", "--format", "{{.ServerVersion}}"], timeout=20)
    if r.returncode != 0:
        return False, "Docker doesn't run: " + (r.stderr or r.stdout).strip()[-200:]
    r = _run([exe, "image", "inspect", "--format", "{{.Id}}", image], timeout=20)
    if r.returncode != 0:
        return False, f"the image {image} isn't loaded yet"
    return True, r.stdout.strip()[:19]


def docker_pull(image: str) -> str:
    exe = find_docker()
    if not exe:
        raise ExportError("Docker is not installed")
    r = _run([exe, "pull", image], timeout=1800)
    if r.returncode != 0:
        raise ExportError("docker pull failed: " + (r.stderr or r.stdout).strip()[-300:])
    return (r.stdout.strip().splitlines() or [""])[-1]


def docker(drawio: Path, png: Path, scale: float, image: str = "") -> None:
    image = image or DEFAULT_IMAGE
    ok, why = docker_ready(image)
    if not ok:
        raise ExportError(why)
    folder = drawio.parent.resolve()
    if png.parent.resolve() != folder:
        raise ExportError("the PNG must go next to the .drawio file")
    cmd = [find_docker(), "run", "--rm", "--network", "none", "-v", f"{folder}:/data", "-w", "/data"]
    if hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]   # the PNG belongs to the user
    cmd += [image, *_cli_args(scale), "-o", f"/data/{png.name}", f"/data/{drawio.name}"]
    r = _run(cmd)
    if not png.is_file():
        raise ExportError(f"draw.io in Docker made no PNG: {(r.stderr or r.stdout).strip()[-300:]}")
