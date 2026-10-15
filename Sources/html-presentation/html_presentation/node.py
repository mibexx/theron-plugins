"""📽 Build presentation – one presentation (one HTML file) per run.

The options – languages, light / dark / both, slide cursor top / bottom, arrow keys – are fixed in the node or set to
“From the input”: then a line in the description / hand-over decides (``LANGUAGES: de, en`` · ``THEME: both`` ·
``CURSOR: top`` · ``ARROW_KEYS: no`` · ``MULTILINGUAL: yes``), else the AI from the content (e.g. “in German and
English”), else the defaults.

A Claude agent of the plugin writes the deck as JSON (slides × languages, theme colours, CSS of its layouts) – it may
read the templates and the style guide. ``check_deck`` looks at it (every slide in every language, tags closed, no
scripts …); problems go back to the same agent. The frame (16:9 stage, navigation, switches) comes from shell.py.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import templates as T
from .check import check, _Parser, OPTIONAL_END
from .shell import build

AUTO = "input"
DEFAULTS = {"multilingual": False, "theme": "light", "cursor": "bottom", "arrows": True}
LINE = re.compile(r"^\s*(LANGUAGES?|SPRACHEN?|THEME|MODE|CURSOR|ARROW[_ ]KEYS|PFEILTASTEN|MULTILINGUAL|MEHRSPRACHIG)"
                  r"\s*:\s*(.+?)\s*$", re.M | re.I)
YES = {"yes", "ja", "true", "1", "on", "an", "y", "j"}
NO = {"no", "nein", "false", "0", "off", "aus", "n"}
TEMPLATE_LINE = re.compile(r"^\s*TEMPLATE:\s*(.+?)\s*$", re.M)
NAME_OK = re.compile(r"^[\w\-. ]+$")
LANG = re.compile(r"^[a-z]{2}(-[A-Za-z]{2})?$")
FIX_ROUNDS = 2
SYSTEM = ("You are a presentation designer: clear story, one idea per slide, strong headlines, little text, "
          "beautiful and consistent layouts. You write clean HTML fragments and CSS.")


def material_of(node) -> str:
    task, given = (node.task or "").strip(), (node.input or "").strip()
    if not given or task in given:
        return task or given
    if not task or given in task:
        return given
    return f"ASSIGNMENT FOR THIS STEP:\n{task}\n\nHAND-OVERS FROM THE STEPS BEFORE:\n{given}"


def slug(text: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
               .replace("ß", "ss")).strip("-")
    return s[:n].strip("-") or "presentation"


def parse_languages(text: str) -> list[str]:
    out = []
    for part in re.split(r"[,;/\s]+|\bund\b|\band\b", (text or "").strip()):
        p = part.strip().lower()
        p = {"deutsch": "de", "german": "de", "englisch": "en", "english": "en", "französisch": "fr",
             "french": "fr", "spanisch": "es", "spanish": "es", "italienisch": "it", "italian": "it",
             "niederländisch": "nl", "dutch": "nl", "polnisch": "pl", "polish": "pl"}.get(p, p)
        if LANG.match(p) and p not in out:
            out.append(p)
    return out


def from_lines(text: str) -> dict:
    """The options a description / hand-over names in lines like ``THEME: both``."""
    out: dict = {}
    for key, value in LINE.findall(text or ""):
        k, v = key.lower().replace(" ", "_"), value.strip().lower()
        if k.startswith(("language", "sprache")):
            langs = parse_languages(value)
            if langs:
                out["languages"] = langs
        elif k in ("theme", "mode"):
            v = {"hell": "light", "dunkel": "dark", "beide": "both", "beides": "both", "switch": "both"}.get(v, v)
            if v in ("light", "dark", "both"):
                out["theme"] = v
        elif k == "cursor":
            v = {"oben": "top", "unten": "bottom"}.get(v, v)
            if v in ("top", "bottom"):
                out["cursor"] = v
        elif k in ("arrow_keys", "pfeiltasten"):
            if v in YES or v in NO:
                out["arrows"] = v in YES
        elif k in ("multilingual", "mehrsprachig"):
            if v in YES or v in NO:
                out["multilingual"] = v in YES
    return out


def check_deck(deck, languages: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(deck, dict):
        return ["the answer is no JSON object"], []
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return ["no slides"], []
    for i, s in enumerate(slides, 1):
        if not isinstance(s, dict) or not isinstance(s.get("html"), dict):
            errors.append(f"slide {i}: no html per language")
            continue
        for lang in languages:
            body = str(s["html"].get(lang) or "").strip()
            if not body:
                errors.append(f"slide {i}: missing in language {lang}")
                continue
            if re.search(r"(?i)<\s*(script|iframe|object|embed)\b|\son\w+\s*=", body):
                errors.append(f"slide {i} ({lang}): scripts, iframes or event handlers are not allowed")
            p = _Parser()
            try:
                p.feed(f"<html><body>{body}</body></html>")
                p.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"slide {i} ({lang}): the HTML can't be parsed: {exc}")
                continue
            unclosed = p.unclosed + [t for t in p.stack if t not in OPTIONAL_END]
            if unclosed or p.stray:
                errors.append(f"slide {i} ({lang}): " + ", ".join(
                    ([f"unclosed <{t}>" for t in dict.fromkeys(unclosed)] +
                     [f"stray </{t}>" for t in dict.fromkeys(p.stray)])[:5]))
            if len(re.sub(r"<[^>]+>", " ", body).split()) > 140:
                warnings.append(f"slide {i} ({lang}): a lot of text for one slide – split it or shorten it")
            if re.search(r"(?i)<img\b(?![^>]*\balt=)", body):
                warnings.append(f"slide {i} ({lang}): an image without alt text")
    if not isinstance(deck.get("title"), (dict, str)) or not deck.get("title"):
        warnings.append("no title")
    return errors, warnings


class PresentationNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        from_input = {"value": AUTO, "label": "From the input"}
        self.ctx.nodes.register(
            "presentation", label="Build presentation", icon="📽", run=self.run,
            description="Builds ONE presentation as an HTML file: always one 16:9 slide, as large as the screen "
                        "allows – optionally multilingual, light / dark / both, slide cursor and arrow keys. Content, "
                        "style / CI and templates like the HTML Builder.",
            ai_hint="Create one slide presentation (HTML) from the content in the assignment and the hand-overs. "
                    "Options may be named in lines: 'LANGUAGES: de, en', 'THEME: light|dark|both', "
                    "'CURSOR: top|bottom', 'ARROW_KEYS: yes|no', 'TEMPLATE: <file>'. Outputs: presentation (the "
                    "file in a line 'HTML_FILE: …') or error.",
            outputs=[{"id": "presentation", "label": tr("Presentation"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "content", "type": "textarea", "label": "Content",
                 "description": "What the presentation says. Empty: the assignment of the step and what the steps "
                                "before hand over (e.g. one item of a loop)."},
                {"key": "style", "type": "textarea", "label": "Style / CI (optional)",
                 "description": "Colours, fonts, tone, logo URL … – or the path or link of a style guide / CSS."},
                {"key": "template_dir", "type": "text", "label": "Template folder",
                 "description": "Your templates: a folder (absolute, or a name below the plugin's template folder). "
                                "Empty: the folder of the plugin settings. 📂 opens it, ＋ copies files into it.",
                 "buttons": [self.open_folder_button(), self.add_button()]},
                {"key": "template", "type": "choice", "label": "Template", "default": T.AUTO,
                 "options": lambda cfg: T.options(self.ctx, cfg), "buttons": [self.open_template_button()],
                 "description": "A presentation (or document) whose look and layouts the new one follows. Automatic: "
                                "the best fitting one of the folder – or none."},
                {"key": "multilingual", "type": "choice", "label": "Multilingual", "default": AUTO,
                 "options": [from_input, {"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
                 "description": "Several languages with a switch. From the input: if the content asks for it "
                                "(or a line MULTILINGUAL: yes / LANGUAGES: de, en)."},
                {"key": "languages", "type": "text", "label": "Language(s)",
                 "description": "e.g. de or de, en – the first is the start language. Empty: from the input (a line "
                                "LANGUAGES: …), else the language of the content."},
                {"key": "theme", "type": "choice", "label": "Light / dark", "default": AUTO,
                 "options": [from_input, {"value": "light", "label": "Light"}, {"value": "dark", "label": "Dark"},
                             {"value": "both", "label": "Both with a switch"}]},
                {"key": "cursor", "type": "choice", "label": "Slide cursor", "default": AUTO,
                 "options": [from_input, {"value": "top", "label": "Top"}, {"value": "bottom", "label": "Bottom"}],
                 "description": "Progress bar, number and a dot per slide."},
                {"key": "arrows", "type": "choice", "label": "Arrow keys", "default": AUTO,
                 "options": [from_input, {"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
                 "description": "Navigate with ← → (and Page ↑/↓, Space, Home, End). The ‹ › buttons and swiping "
                                "always work."},
                {"key": "folder", "type": "text", "label": "Output folder", "default": "presentations",
                 "description": "Where the presentation goes – relative to the project's workspace."},
                {"key": "filename", "type": "text", "label": "File name (optional)",
                 "description": "e.g. kickoff.html – empty: a name from the title. Nothing is overwritten."},
            ])

    # ------------------------------------------------------------------ buttons (like the HTML Builder)
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

    # ------------------------------------------------------------------ the options
    def options(self, node, text: str) -> tuple[dict, list[str]]:
        """(options, what the AI is to decide). Fixed in the node > a line in the input > the AI > the defaults."""
        cfg = node.config
        named = from_lines(text)
        out: dict = {}
        open_: list[str] = []
        fixed_langs = parse_languages(cfg.get("languages") or "")
        if fixed_langs:
            out["languages"] = fixed_langs
        elif "languages" in named:
            out["languages"] = named["languages"]
        multi = cfg.get("multilingual") or AUTO
        if multi in ("yes", "no"):
            out["multilingual"] = multi == "yes"
        elif "multilingual" in named:
            out["multilingual"] = named["multilingual"]
        elif len(out.get("languages") or []) > 1:
            out["multilingual"] = True
        if out.get("multilingual") is False and out.get("languages"):
            out["languages"] = out["languages"][:1]
        if "languages" not in out:
            open_.append("languages")
        if "multilingual" not in out:
            open_.append("multilingual")
        for key, values in (("theme", ("light", "dark", "both")), ("cursor", ("top", "bottom"))):
            v = cfg.get(key) or AUTO
            if v in values:
                out[key] = v
            elif key in named:
                out[key] = named[key]
            else:
                open_.append(key)
        a = cfg.get("arrows") or AUTO
        if a in ("yes", "no"):
            out["arrows"] = a == "yes"
        elif "arrows" in named:
            out["arrows"] = named["arrows"]
        else:
            open_.append("arrows")
        return out, open_

    @staticmethod
    def settle(opts: dict, chosen: dict, written: list[str] | None = None) -> dict:
        """The options the AI chose for the open ones, checked – else what the slides are written in, else the
        defaults."""
        out = dict(opts)
        if "languages" not in out and not chosen.get("languages") and written:
            chosen = {**chosen, "languages": written}
        if "multilingual" not in out:
            out["multilingual"] = bool(chosen.get("multilingual")) if isinstance(chosen.get("multilingual"), bool) \
                else DEFAULTS["multilingual"]
        if "languages" not in out:
            langs = [x for x in (chosen.get("languages") or []) if isinstance(x, str) and LANG.match(x.lower())]
            out["languages"] = [x.lower() for x in langs] or ["en"]
        if not out["multilingual"]:
            out["languages"] = out["languages"][:1]
        out.setdefault("theme", chosen.get("theme") if chosen.get("theme") in ("light", "dark", "both")
                       else DEFAULTS["theme"])
        out.setdefault("cursor", chosen.get("cursor") if chosen.get("cursor") in ("top", "bottom")
                       else DEFAULTS["cursor"])
        out.setdefault("arrows", chosen.get("arrows") if isinstance(chosen.get("arrows"), bool) else DEFAULTS["arrows"])
        return out

    # ------------------------------------------------------------------ the run
    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        material = material_of(node)
        content = (cfg.get("content") or "").strip()
        if not content and not material and not (node.instructions or "").strip():
            return node.route("error", tr("There is no content for the presentation – write it into the node or let "
                                          "the step before hand it over."))
        try:
            template, choices = self.template(node)
        except ValueError as exc:
            return node.route("error", str(exc))
        opts, open_ = self.options(node, "\n".join((content, material, node.instructions or "")))
        out_dir = self.out_dir(node)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            work = self.ctx.data_dir / "work" / f"run-{node.run_id}-{int(time.time() * 1000)}"
            work.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return node.route("error", tr("Can't create the output folder {folder}: {error}", folder=str(out_dir),
                                          error=exc))
        target = work / "deck.json"
        model = self.ctx.settings.get("model") or "sonnet"
        node.progress(tr("writes the slides …"))
        prompt = self.prompt(node, content, material, template, choices, opts, open_, target)
        try:
            result = await self.ctx.ai.agent(prompt, cwd=str(work), system=SYSTEM, model=model,
                                             tools=["Read", "Glob", "Grep", "Write", "Edit", "WebFetch"],
                                             max_turns=40, on_text=lambda t: self.progress(node, t))
        except Exception as exc:  # noqa: BLE001
            return node.route("error", tr("The AI could not write the presentation: {error}", error=exc))
        if result.is_error:
            return node.route("error", tr("The AI could not write the presentation: {error}",
                                          error=(result.text or "?")[-500:]))
        deck, final, errors, warnings = self.examine(target, opts)
        session = result.session_id
        for _ in range(FIX_ROUNDS):
            if not errors and not warnings:
                break
            node.progress(tr("fixes {n} problem(s) …", n=len(errors) + len(warnings)))
            problems = "\n".join([f"- ERROR: {e}" for e in errors] + [f"- {w}" for w in warnings])
            try:
                fix = await self.ctx.ai.agent(
                    f"The check of {target} found these problems:\n{problems}\n\nFix them in that file (it must stay "
                    "the JSON described before). Change nothing else.", cwd=str(work), system=SYSTEM, model=model,
                    tools=["Read", "Edit", "Write"], max_turns=15, session_id=session,
                    on_text=lambda t: self.progress(node, t))
                session = fix.session_id or session
            except Exception as exc:  # noqa: BLE001
                self.ctx.log.error(f"fix round: {exc}")
                break
            deck, final, errors, warnings = self.examine(target, opts)
            if not errors and len(warnings) <= 1:
                break
        if errors or deck is None:
            return node.route("error", tr("The presentation isn't usable: {problems}", problems="; ".join(errors)))

        page = build(deck, languages=final["languages"], theme=final["theme"], cursor=final["cursor"],
                     arrows=final["arrows"])
        doc_errors, doc_warnings = check(page)
        if doc_errors:
            return node.route("error", tr("The presentation isn't usable: {problems}", problems="; ".join(doc_errors)))
        titles = deck.get("title") or {}
        title = (titles.get(final["languages"][0]) if isinstance(titles, dict) else str(titles)) or "Presentation"
        path = self.unique(out_dir, cfg.get("filename") or "", title)
        path.write_text(page, encoding="utf-8")
        n = len(deck["slides"])
        used = template.name if template else (str(deck.get("template_used") or "") if choices else "")
        used = "" if used.lower() in ("none", "keine", "-") else Path(used).name
        node.say(kind="presentation",
                 data={"path": str(path), "title": title, "slides": n, "languages": final["languages"],
                       "theme": final["theme"], "cursor": final["cursor"], "arrows": final["arrows"],
                       "template": used, "warnings": warnings},
                 text=f"📽 {title} · {n}\n{path}")
        node.progress(f"📽 {path.name}")
        notes = ("\n" + tr("Notes of the check: {notes}", notes="; ".join(warnings))) if warnings else ""
        return node.route("presentation",
                          tr("Presentation “{title}”: {n} slides, {langs}, {theme}, slide cursor {cursor}, arrow keys "
                             "{arrows}.", title=title, n=n, langs=", ".join(final["languages"]), theme=final["theme"],
                             cursor=final["cursor"], arrows=tr("on") if final["arrows"] else tr("off"))
                          + notes + f"\nHTML_FILE: {path}")

    def examine(self, target: Path, opts: dict):
        """(deck, the final options, errors, warnings) of what the agent wrote."""
        if not target.is_file():
            return None, opts, [f"no file {target.name} – write the JSON there"], []
        raw = target.read_text(encoding="utf-8", errors="replace")
        raw = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip())
        try:
            deck = json.loads(raw)
        except ValueError as exc:
            return None, opts, [f"{target.name} is no valid JSON: {exc}"], []
        written = []
        if isinstance(deck, dict) and isinstance(deck.get("slides"), list) and deck["slides"] \
                and isinstance(deck["slides"][0], dict) and isinstance(deck["slides"][0].get("html"), dict):
            written = [k for k in deck["slides"][0]["html"] if isinstance(k, str)]
        final = self.settle(opts, (deck.get("options") or {}) if isinstance(deck, dict) else {}, written)
        errors, warnings = check_deck(deck, final["languages"])
        return deck, final, errors, warnings

    def prompt(self, node, content, material, template, choices, opts, open_, target) -> str:
        cfg = node.config
        parts = ["Create ONE slide presentation."]
        if content:
            parts.append(f"CONTENT (from the node):\n{content}")
        if (node.instructions or "").strip():
            parts.append(f"INSTRUCTIONS FOR THIS STEP:\n{node.instructions.strip()}")
        if material:
            parts.append(f"WHAT THIS STEP GOT (assignment and hand-overs – the content may come from here):\n"
                         f"{material[:40000]}")
        if (cfg.get("style") or "").strip():
            parts.append(f"STYLE / CI: {cfg['style'].strip()}\n(If this names a file or a link, read it first and "
                         "follow it: colours, fonts, tone, logo.)")
        if template is not None:
            parts.append(f"TEMPLATE: {template}\nRead it first and follow its look, slide layouts and structure "
                         "closely – with the new content.")
        elif choices:
            parts.append("TEMPLATES you may follow:\n" + "\n".join(f"- {p}" for p in choices[:60])
                         + "\nIf one clearly fits, read it and follow its look and layouts; put its file name into "
                           '"template_used" (else "none").')
        fixed = []
        if "languages" in opts:
            fixed.append(f"languages: {', '.join(opts['languages'])} (the first is the start language)")
        for k in ("theme", "cursor", "arrows"):
            if k in opts:
                fixed.append(f"{k}: {opts[k]}")
        if fixed:
            parts.append("FIXED OPTIONS: " + "; ".join(fixed))
        if open_:
            parts.append("DECIDE FROM THE CONTENT (and say it in \"options\"): " + ", ".join(open_)
                         + " – multilingual only if the content asks for several languages; languages as ISO codes "
                           "(the content's own language if nothing is said); theme light / dark / both; cursor "
                           "top / bottom; arrows true / false (default: light, bottom, true).")
        parts.append(f"""WRITE the file {target} (Write tool) with this JSON – nothing else in it:
{{
  "title": {{"<lang>": "title of the presentation", …}},
  "options": {{"multilingual": bool, "languages": ["de", …], "theme": "light|dark|both", "cursor": "top|bottom",
              "arrows": bool}},
  "theme": {{"light": {{"bg": "#…", "fg": "#…", "muted": "#…", "accent": "#…", "surface": "#…", "border": "#…"}},
            "dark": {{ the same six colours for the dark mode }}}},
  "font_family": "CSS font-family list", "font_url": "optional https://fonts.googleapis.com/css2?… link",
  "css": "CSS of your slide layouts – every selector starts with .slide (e.g. .slide.title, .slide .cols)",
  "template_used": "file name or none",
  "slides": [{{"layout": "title|section|content|two-cols|quote|image|… (your CSS classes)",
              "html": {{"<lang>": "<h1>…</h1><p>…</p>", …}}}}, …]
}}
RULES:
- One slide = a 1920×1080 stage (16:9, padding is set). One idea per slide, big type (headlines 64–96 px, text
  32–40 px), at most ~6 bullet points, no walls of text. A title slide first, a closing slide last.
- Every slide in EVERY language of "languages" – the same content, translated well.
- Colours only through the CSS variables var(--bg), var(--fg), var(--muted), var(--accent), var(--surface),
  var(--border) – so light and dark both work. Good contrast in both.
- Clean HTML fragments: every tag closed, alt text on images, no <script>, <iframe>, inline event handlers or
  <html>/<body>. Images only by https URL (or none) – use CSS shapes, gradients, emoji or inline SVG for visuals.
- Real content – no lorem ipsum, no placeholders.
- When the file is written, answer with one short sentence.""")
        return "\n\n".join(parts)

    def template(self, node):
        cfg = node.config
        m = TEMPLATE_LINE.search(material_of(node))
        if m:
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
        sub = (node.config.get("folder") or "presentations").strip() or "presentations"
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else self.ctx.data_dir / "output"
        p = Path(sub).expanduser()
        return p if p.is_absolute() else base / p

    @staticmethod
    def unique(out_dir: Path, raw: str, title: str) -> Path:
        name = Path(raw.strip()).stem if raw.strip() else slug(title)
        if not NAME_OK.match(name):
            name = slug(name)
        path, n = out_dir / f"{name}.html", 2
        while path.exists():
            path = out_dir / f"{name}-{n}.html"
            n += 1
        return path

    def progress(self, node, text: str) -> None:
        line = " ".join((text or "").split())
        if line:
            node.progress(line[:90])
