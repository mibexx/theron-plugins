#!/usr/bin/env python3
"""Pack every plugin in Sources/ into Plugins/<id>.theronplugin – signed, if a key is there.

    python scripts/build.py                     all plugins
    python scripts/build.py hello-world         only these
    python scripts/build.py --sign KEY          sign with KEY (default: ~/.config/theron/plugin-signing/official.key, if it exists)
    python scripts/build.py --no-sign

Uses the `theron` command when it is installed (theron plugin pack), else the pack script of the plugin skeleton
(https://github.com/mibexx/theron-plugin-sekeleton – scripts/pack.py, path in THERON_PACK_SCRIPT).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES, PLUGINS = ROOT / "Sources", ROOT / "Plugins"
DEFAULT_KEY = Path.home() / ".config" / "theron" / "plugin-signing" / "official.key"


def theron() -> list[str] | None:
    for cmd in (os.environ.get("THERON_CLI"), shutil.which("theron"),
                "/Applications/Theron.app/Contents/MacOS/Theron"):
        if cmd and Path(cmd).exists():
            return [cmd, "cli"] if cmd.endswith("/Theron") else [cmd]
    return None


def pack(folder: Path, key: Path | None) -> Path:
    meta = tomllib.loads((folder / "plugin.toml").read_text(encoding="utf-8"))
    target = PLUGINS / f"{meta['id']}.theronplugin"
    with tempfile.TemporaryDirectory() as tmp:
        cli = theron()
        script = os.environ.get("THERON_PACK_SCRIPT")
        if cli:
            cmd = cli + ["plugin", "pack", str(folder), "--out", tmp] + (["--sign", str(key)] if key else [])
        elif script:
            cmd = [sys.executable, script, "--out", tmp] + (["--sign", str(key)] if key else [])
        else:
            sys.exit("neither `theron` nor THERON_PACK_SCRIPT found")
        subprocess.run(cmd, check=True, cwd=folder, stdout=subprocess.DEVNULL)
        built = next(Path(tmp).glob("*.theronplugin"))
        PLUGINS.mkdir(exist_ok=True)
        shutil.copyfile(built, target)
    (folder / "SIGNATURE.json").unlink(missing_ok=True)   # the signature lives in the package only
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--sign", type=Path)
    ap.add_argument("--no-sign", action="store_true")
    args = ap.parse_args()
    key = None if args.no_sign else (args.sign or (DEFAULT_KEY if DEFAULT_KEY.exists() else None))
    folders = [f for f in sorted(SOURCES.iterdir()) if (f / "plugin.toml").is_file()]
    if args.ids:
        folders = [f for f in folders if f.name in args.ids]
    for folder in folders:
        print(f"✔ {pack(folder, key).relative_to(ROOT)}" + ("  (signed)" if key else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
