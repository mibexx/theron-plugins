"""The template folder: documents the AI follows (layout, structure, look) – HTML pages, Markdown or text, PDFs,
Word files, screenshots, a CSS of the CI …

Which folder: the node's own (field “Template folder”), else the plugin setting, else the plugin's data folder
``templates``. A relative name is a sub-folder of that data folder (e.g. ``newsletter``) – so the editor and the run
find the same files, whatever project runs the process.
"""

from __future__ import annotations

import shutil
from pathlib import Path

KINDS = {".html": "HTML", ".htm": "HTML", ".md": "Markdown", ".txt": "Text", ".pdf": "PDF", ".docx": "Word",
         ".css": "CSS", ".png": "Image", ".jpg": "Image", ".jpeg": "Image", ".webp": "Image", ".gif": "Image",
         ".svg": "SVG"}
FILTER = "Templates (" + " ".join(f"*{e}" for e in KINDS) + ")"
AUTO, NONE = "auto", ""


def folder(ctx, cfg: dict) -> Path:
    raw = (cfg.get("template_dir") or ctx.settings.get("template_dir") or "").strip()
    base = ctx.data_dir / "templates"
    if not raw:
        return base
    p = Path(raw).expanduser()
    return p if p.is_absolute() else base / p


def listing(path: Path) -> list[Path]:
    """The templates in the folder (sub-folders too, hidden files not), sorted by name."""
    if not path.is_dir():
        return []
    return sorted((f for f in path.rglob("*") if f.is_file() and f.suffix.lower() in KINDS
                   and not any(part.startswith(".") for part in f.relative_to(path).parts)),
                  key=lambda f: str(f.relative_to(path)).lower())


def options(ctx, cfg: dict) -> list[dict]:
    tr = ctx.tr
    base = folder(ctx, cfg)
    found = listing(base)
    out = [{"value": AUTO, "label": tr("Automatic – the best fitting one of the folder ({n})", n=len(found))},
           {"value": NONE, "label": tr("None")}]
    for f in found:
        rel = str(f.relative_to(base))
        out.append({"value": rel, "label": f"{rel}  ·  {KINDS[f.suffix.lower()]}"})
    return out


def add(paths: list[str], target: Path) -> list[str]:
    """Copy files into the template folder (a name that exists gets -2, -3 …) → the names."""
    target.mkdir(parents=True, exist_ok=True)
    added = []
    for raw in paths:
        src = Path(raw)
        if not src.is_file():
            continue
        dest = target / src.name
        n = 2
        while dest.exists():
            dest = target / f"{src.stem}-{n}{src.suffix}"
            n += 1
        shutil.copy2(src, dest)
        added.append(dest.name)
    return added
