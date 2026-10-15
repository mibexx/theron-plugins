"""🧱 Build HTML – one clean HTML document per run of the node.

What it works on: the description in the node (field “Content”), the node's instructions, the orchestrator's assignment
for this step and the hand-overs before it – in a loop each round brings its own. Optional: audience, style / CI and a
template (from the template folder, chosen automatically or fixed; a hand-over may name one with ``TEMPLATE: path``).

A Claude agent of the plugin writes the file (it may read the templates – also PDFs and images – but writes only the
document), then ``check.py`` looks at it; problems go back to the same agent once more. Output ✔ “Document”: the path
(``HTML_FILE: …``), title and size – ✖ “Error”: why not.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import templates as T
from .check import check, title_of

TEMPLATE_LINE = re.compile(r"^\s*TEMPLATE:\s*(.+?)\s*$", re.M)
USED_LINE = re.compile(r"TEMPLATE_USED:\s*(.+?)\s*$", re.M)
HTML_LINE = re.compile(r"HTML_FILE:\s*(.+?\.html?)\s*$", re.M | re.I)
NAME_OK = re.compile(r"^[\w\-. ]+$")
FIX_ROUNDS = 2

SYSTEM = ("You are a meticulous web designer and front-end developer. You write clean, modern, accessible, "
          "semantic HTML5 documents that look professional – in one self-contained file.")


def material_of(node) -> str:
    """The orchestrator's assignment for this step AND the hand-overs before it (one alone may miss the content)."""
    task, given = (node.task or "").strip(), (node.input or "").strip()
    if not given or task in given:
        return task or given
    if not task or given in task:
        return given
    return f"ASSIGNMENT FOR THIS STEP:\n{task}\n\nHAND-OVERS FROM THE STEPS BEFORE:\n{given}"


def slug(text: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("-")
    return s[:n].strip("-") or "document"


class HtmlNode:
    def __init__(self, ctx):
        self.ctx = ctx

    # ------------------------------------------------------------------ the node and its fields
    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "html", label="Build HTML", icon="🧱", run=self.run,
            description="Builds ONE clean, self-contained HTML document from a description of its content – "
                        "optionally for an audience, in a style / CI and after a template. For several documents put "
                        "it behind a loop.",
            ai_hint="Create exactly one HTML document (web page, report, newsletter, landing page …) from the "
                    "description in the assignment and the hand-overs. Name the audience and the style if they "
                    "matter; a template file can be named with a line 'TEMPLATE: <path>'. Outputs: document (the "
                    "file's path in a line 'HTML_FILE: …') or error.",
            outputs=[{"id": "document", "label": tr("Document"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "content", "type": "textarea", "label": "Content",
                 "description": "What the document is about and what goes in it. Empty: the assignment of the step "
                                "and what the steps before hand over (e.g. one item of a loop)."},
                {"key": "audience", "type": "text", "label": "Audience (optional)",
                 "description": "Who reads it, e.g. “customers without technical background”, “investors”."},
                {"key": "style", "type": "textarea", "label": "Style / CI (optional)",
                 "description": "Colours, fonts, tone, logo URL … – or the path or link of a style guide / CSS."},
                {"key": "template_dir", "type": "text", "label": "Template folder",
                 "description": "Your templates: a folder (absolute, or a name below the plugin's template folder). "
                                "Empty: the folder of the plugin settings. 📂 opens it, ＋ copies files into it.",
                 "buttons": [self.open_folder_button(), self.add_button()]},
                {"key": "template", "type": "choice", "label": "Template", "default": T.AUTO,
                 "options": lambda cfg: T.options(self.ctx, cfg), "buttons": [self.open_template_button()],
                 "description": "The document whose layout and structure the new one follows. Automatic: the AI "
                                "takes the best fitting one of the folder – or none if nothing fits."},
                {"key": "folder", "type": "text", "label": "Output folder", "default": "html",
                 "description": "Where the document goes – relative to the project's workspace."},
                {"key": "filename", "type": "text", "label": "File name (optional)",
                 "description": "e.g. offer.html – empty: a name from the title. An existing file is never "
                                "overwritten (-2, -3 … are added)."},
                {"key": "self_contained", "type": "bool", "label": "Self-contained (no external files)",
                 "default": True,
                 "description": "CSS inline in the file, no scripts or stylesheets from elsewhere – it opens "
                                "anywhere, also offline and as an e-mail attachment. Web fonts and images by URL "
                                "stay allowed."},
            ])

    # ------------------------------------------------------------------ buttons next to the fields
    def open_folder_button(self) -> dict:
        async def run(cfg):
            path = T.folder(self.ctx, cfg)
            path.mkdir(parents=True, exist_ok=True)
            self.ctx.ui.open_url(path.as_uri())
            return None
        return {"id": "open", "label": "📂", "run": run, "tooltip": "Open the template folder"}

    def add_button(self) -> dict:
        async def run(cfg):
            path = T.folder(self.ctx, cfg)
            picked = await self.ctx.ui.run(self.ctx.ui.ask_files, self.ctx.tr("Add templates"), T.FILTER)
            if not picked:
                return None
            added = T.add(picked, path)
            return True, self.ctx.tr("Added to {folder}: {names}", folder=str(path), names=", ".join(added))
        return {"id": "add", "label": "＋", "run": run, "tooltip": "Copy files into the template folder"}

    def open_template_button(self) -> dict:
        async def run(cfg):
            name = cfg.get("template") or ""
            if name in (T.AUTO, T.NONE):
                return False, self.ctx.tr("Choose a template first.")
            path = T.folder(self.ctx, cfg) / name
            if not path.is_file():
                return False, self.ctx.tr("The template is not there (any more): {path}", path=str(path))
            self.ctx.ui.open_url(path.as_uri())
            return None
        return {"id": "show", "label": "👁", "run": run, "tooltip": "Open the chosen template"}

    # ------------------------------------------------------------------ the run
    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        material = material_of(node)
        content = (cfg.get("content") or "").strip()
        if not content and not material and not (node.instructions or "").strip():
            return node.route("error", tr("There is no description of the content – write it into the node "
                                          "(Content) or let the step before hand it over."))
        try:
            template, choices = self.template(node)
        except ValueError as exc:
            return node.route("error", str(exc))
        out_dir = self.out_dir(node)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return node.route("error", tr("Can't create the output folder {folder}: {error}", folder=str(out_dir),
                                          error=exc))
        fixed = self.fixed_name(cfg.get("filename") or "", out_dir)
        before = {p.name for p in out_dir.glob("*.htm*")}
        started = time.time()

        node.progress(tr("writes the HTML document …"))
        prompt = self.prompt(node, content, material, template, choices, out_dir, fixed)
        model = self.ctx.settings.get("model") or "sonnet"
        try:
            result = await self.ctx.ai.agent(prompt, cwd=str(out_dir), system=SYSTEM, model=model,
                                             tools=["Read", "Glob", "Grep", "Write", "Edit", "WebFetch"],
                                             max_turns=40, on_text=lambda t: self.progress(node, t))
        except Exception as exc:  # noqa: BLE001 - no Claude, no subscription …
            return node.route("error", tr("The AI could not write the document: {error}", error=exc))
        if result.is_error:
            return node.route("error", tr("The AI could not write the document: {error}",
                                          error=(result.text or "?")[-500:]))

        path = self.find(result.text, out_dir, before, fixed, started)
        if path is None:
            return node.route("error", tr("The AI wrote no HTML file into {folder}.", folder=str(out_dir))
                              + (f"\n\n{result.text[-800:]}" if result.text else ""))

        errors, warnings = check(self.read(path))
        session = result.session_id
        for _ in range(FIX_ROUNDS):
            if not errors and not warnings:
                break
            node.progress(tr("fixes {n} problem(s) …", n=len(errors) + len(warnings)))
            problems = "\n".join(f"- ERROR: {e}" for e in errors) + "\n" + "\n".join(f"- {w}" for w in warnings)
            try:
                fix = await self.ctx.ai.agent(
                    f"The check of {path} found these problems:\n{problems.strip()}\n\nFix them in that file (Edit). "
                    "Change nothing else. Answer with the line HTML_FILE: <path> at the end.",
                    cwd=str(out_dir), system=SYSTEM, model=model, tools=["Read", "Edit", "Write"], max_turns=15,
                    session_id=session, on_text=lambda t: self.progress(node, t))
                session = fix.session_id or session
            except Exception as exc:  # noqa: BLE001
                self.ctx.log.error(f"fix round: {exc}")
                break
            errors, warnings = check(self.read(path))
            if not errors and len(warnings) <= 1:
                break
        if errors:
            return node.route("error", tr("The HTML document {path} isn't clean: {problems}", path=str(path),
                                          problems="; ".join(errors)))

        html_text = self.read(path)
        title = title_of(html_text) or path.stem
        size = path.stat().st_size
        used = template.name if template else ""
        if template is None and choices:   # automatic: which one the AI took
            m = USED_LINE.search(result.text or "")
            name = Path(m.group(1).strip().strip("`'\"")).name if m else ""
            used = name if name and name.lower() not in ("none", "keine", "-") else ""
        node.say(kind="html", data={"path": str(path), "title": title, "size": size, "template": used,
                                    "warnings": warnings},
                 text=f"🧱 {title}\n{path}")
        node.progress(f"🧱 {path.name}")
        notes = ("\n" + tr("Notes of the check: {notes}", notes="; ".join(warnings))) if warnings else ""
        return node.route("document",
                          tr("HTML document “{title}” ({size} KB){template}.", title=title,
                             size=max(1, round(size / 1024)),
                             template=(tr(", after the template {name}", name=used) if used else ""))
                          + notes + f"\nHTML_FILE: {path}")

    # ------------------------------------------------------------------ pieces
    def template(self, node) -> tuple[Path | None, list[Path]]:
        """The fixed template, or (None, the folder's templates) for the AI to choose from."""
        cfg = node.config
        m = TEMPLATE_LINE.search(material_of(node))
        if m:   # a hand-over names one
            p = Path(m.group(1).strip().strip("\"'`")).expanduser()
            if not p.is_absolute():
                p = T.folder(self.ctx, cfg) / p
            if not p.is_file():
                raise ValueError(self.ctx.tr("The template named in the hand-over is not there: {path}", path=str(p)))
            return p, []
        choice = cfg.get("template", T.AUTO)
        base = T.folder(self.ctx, cfg)
        if choice == T.NONE:
            return None, []
        if choice in (T.AUTO, None):
            return None, T.listing(base)
        p = base / choice
        if not p.is_file():
            raise ValueError(self.ctx.tr("The template “{name}” is not in {folder} (any more) – choose another one in "
                                         "the node.", name=choice, folder=str(base)))
        return p, []

    def out_dir(self, node) -> Path:
        sub = (node.config.get("folder") or "html").strip() or "html"
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else self.ctx.data_dir / "output"
        p = Path(sub).expanduser()
        return p if p.is_absolute() else base / p

    @staticmethod
    def fixed_name(raw: str, out_dir: Path) -> str:
        """The configured file name, made safe and unique – '' when the AI names the file."""
        raw = Path(raw.strip()).name if raw.strip() else ""
        if not raw:
            return ""
        if not NAME_OK.match(raw):
            raw = slug(Path(raw).stem) + ".html"
        if not raw.lower().endswith((".html", ".htm")):
            raw += ".html"
        name, n = raw, 2
        while (out_dir / name).exists():
            name = f"{Path(raw).stem}-{n}{Path(raw).suffix}"
            n += 1
        return name

    def prompt(self, node, content, material, template, choices, out_dir, fixed) -> str:
        cfg = node.config
        parts = ["Create exactly ONE HTML document."]
        if content:
            parts.append(f"CONTENT (from the node):\n{content}")
        if (node.instructions or "").strip():
            parts.append(f"INSTRUCTIONS FOR THIS STEP:\n{node.instructions.strip()}")
        if material:
            parts.append(f"WHAT THIS STEP GOT (assignment and hand-overs – the content may come from here):\n"
                         f"{material[:40000]}")
        if (cfg.get("audience") or "").strip():
            parts.append(f"AUDIENCE: {cfg['audience'].strip()} – write and design for them (wording, depth, tone).")
        if (cfg.get("style") or "").strip():
            parts.append(f"STYLE / CI: {cfg['style'].strip()}\n(If this names a file or a link, read it first and "
                         "follow it: colours, fonts, spacing, tone, logo.)")
        if template is not None:
            parts.append(f"TEMPLATE: {template}\nRead it first. Follow its layout, structure, sections and look "
                         "closely – but with the new content (don't copy its text).")
        elif choices:
            listing = "\n".join(f"- {p}" for p in choices[:60])
            parts.append(f"TEMPLATES you may follow:\n{listing}\nIf one clearly fits this document (kind, purpose), "
                         "read it and follow its layout, structure and look with the new content. If none fits, use "
                         "none. Say which one you used (or none) in one line: TEMPLATE_USED: <path or none>.")
        target = (f"Write it to exactly this file: {out_dir / fixed}" if fixed else
                  f"Write it as a NEW .html file into {out_dir} with a short, meaningful kebab-case name from the "
                  "title (an existing file must not be overwritten – add -2, -3 … then).")
        rules = [
            target,
            "Clean HTML5: <!DOCTYPE html>, <html lang> in the content's language, <meta charset=\"utf-8\">, a "
            "viewport meta tag, a <title>, exactly one <h1>, semantic elements (header, main, section, article, "
            "nav, footer), every tag closed, alt text on images, good contrast, readable on phones and desktops.",
            ("Self-contained: all CSS in one <style> in the head; no external stylesheets or scripts (web fonts and "
             "images by URL are fine); no JavaScript unless the content really needs it."
             if cfg.get("self_contained", True) else
             "You may link external stylesheets or scripts from well-known CDNs if they help."),
            "Write real, complete content – no lorem ipsum, no placeholders, no TODOs. Keep the language of the "
            "content.",
            "Do not create or change any other file.",
            "When done, answer with a two-sentence summary and, as the last line: HTML_FILE: <absolute path>",
        ]
        parts.append("RULES:\n" + "\n".join(f"- {r}" for r in rules))
        return "\n\n".join(parts)

    @staticmethod
    def find(text: str, out_dir: Path, before: set[str], fixed: str, started: float) -> Path | None:
        """The file the agent wrote: the configured one, the HTML_FILE line, or the new .html in the folder."""
        if fixed and (out_dir / fixed).is_file():
            return out_dir / fixed
        for m in reversed(list(HTML_LINE.finditer(text or ""))):
            p = Path(m.group(1).strip().strip("`'\"")).expanduser()
            p = p if p.is_absolute() else out_dir / p
            if p.is_file():
                return p
        new = [p for p in out_dir.glob("*.htm*") if p.name not in before or p.stat().st_mtime >= started - 1]
        return max(new, key=lambda p: p.stat().st_mtime) if new else None

    @staticmethod
    def read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def progress(self, node, text: str) -> None:
        line = " ".join((text or "").split())
        if line and "HTML_FILE" not in line:
            node.progress(line[:90])
