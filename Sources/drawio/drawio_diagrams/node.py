"""📐 Draw diagram – one diagram per run: the .drawio file and a PNG of it.

What it draws: the description in the node (field “Description”), the node's instructions, the orchestrator's
assignment and the hand-overs before it. The kind of diagram is fixed in the node – or “Automatic”: named in the
description (“a sequence diagram of …”, or a line ``DIAGRAM_TYPE: sequence``) or chosen by the AI.

The AI writes the draw.io XML, ``model.check`` looks at it (broken XML, missing ends of arrows, shapes on top of each
other …) and problems go back to it; then the PNG is drawn (draw.io desktop app or the plugin's own renderer).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from . import exporters
from .model import DiagramError, cells, check, extract_xml, plain

TYPES = [
    ("auto", "Automatic – from the description"),
    ("flowchart", "Flowchart"),
    ("sequence", "Sequence diagram"),
    ("class", "UML class diagram"),
    ("activity", "UML activity diagram"),
    ("state", "State diagram"),
    ("usecase", "Use case diagram"),
    ("er", "Entity relationship (ER) diagram"),
    ("architecture", "Architecture / component diagram"),
    ("network", "Network diagram"),
    ("deployment", "Deployment / infrastructure diagram"),
    ("swimlane", "Swimlane process (BPMN-like)"),
    ("orgchart", "Org chart"),
    ("mindmap", "Mind map"),
    ("timeline", "Timeline"),
    ("venn", "Venn diagram"),
]
HOW = {
    "flowchart": "start/end as rounded rectangles or ellipses, steps as rectangles, decisions as rhombi with labelled "
                 "yes/no edges, top to bottom",
    "sequence": "participants as shape=umlLifeline across the top, messages as horizontal edges between the "
                "lifelines (with sourcePoint/targetPoint at the lifelines' x, increasing y), replies dashed",
    "class": "classes as swimlane containers (name in the header) with text children for attributes and methods "
             "(+ public, - private), inheritance with endArrow=block;endFill=0, associations with labels/multiplicity",
    "activity": "initial node (filled ellipse), actions as rounded rectangles, decisions as rhombi, final node",
    "state": "states as rounded rectangles, transitions labelled with the event, a filled start point",
    "usecase": "actors (shape=umlActor) outside a system boundary rectangle, use cases as ellipses inside",
    "er": "entities as swimlane tables with one text row per attribute (PK/FK marked), relations with ER arrow ends "
          "(endArrow=ERmany, startArrow=ERmandOne …)",
    "architecture": "components as rounded rectangles grouped in containers per layer / system, databases as "
                    "shape=cylinder3, external systems dashed, labelled data flows",
    "network": "devices as labelled shapes (cloud for the internet, cylinder for storage), zones as containers",
    "deployment": "nodes / servers / clusters as containers, services inside, databases as cylinders",
    "swimlane": "one horizontal swimlane per role (horizontal=0 lanes stacked), steps inside the lanes, flow left to "
                "right",
    "orgchart": "a tree of rounded rectangles top to bottom, orthogonal edges without arrow heads",
    "mindmap": "the central topic in the middle as an ellipse, branches around it, curved or straight edges without "
               "arrows, one colour per main branch",
    "timeline": "a horizontal line with dated milestones above and below it",
    "venn": "overlapping semi-transparent ellipses (opacity=50) with labels",
}
TYPE_LINE = re.compile(r"^\s*DIAGRAM[_ ]TYPE:\s*([\w-]+)", re.M | re.I)
NAME_OK = re.compile(r"^[\w\-. ]+$")
FIX_ROUNDS = 2
SYSTEM = ("You are an expert in draw.io (diagrams.net) and in visualising information. You write valid, "
          "uncompressed draw.io XML with a clean, readable layout.")


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
    return s[:n].strip("-") or "diagram"


def unique(path: Path) -> Path:
    """path, or path-2 / -3 … – also when the PNG of that name exists."""
    out, n = path, 2
    while out.exists() or out.with_suffix(".png").exists():
        out = path.with_name(f"{path.stem}-{n}{path.suffix}")
        n += 1
    return out


class DiagramNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self) -> None:
        tr = self.ctx.tr
        self.ctx.nodes.register(
            "diagram", label="Draw diagram", icon="📐", run=self.run,
            description="Draws ONE diagram from a description – as a draw.io file and a PNG. The kind (flowchart, "
                        "sequence, class, ER, architecture …) is fixed here or taken from the description.",
            ai_hint="Draw exactly one diagram (flowchart, sequence, UML class, ER, architecture, mind map …) from "
                    "the description in the assignment and the hand-overs; name the kind if it matters, e.g. a line "
                    "'DIAGRAM_TYPE: sequence'. Outputs: diagram (paths in the lines 'DRAWIO_FILE: …' and "
                    "'PNG_FILE: …') or error.",
            outputs=[{"id": "diagram", "label": tr("Diagram"), "color": "success"},
                     {"id": "error", "label": tr("Error"), "color": "error"}],
            fields=[
                {"key": "description", "type": "textarea", "label": "Description",
                 "description": "What the diagram shows. Empty: the assignment of the step and what the steps before "
                                "hand over (e.g. one item of a loop)."},
                {"key": "type", "type": "choice", "label": "Kind of diagram", "default": "auto",
                 "options": [{"value": v, "label": label} for v, label in TYPES],
                 "description": "Fixed here – or Automatic: the kind named in the description (or a line "
                                "DIAGRAM_TYPE: …), else the AI picks the one that fits."},
                {"key": "style", "type": "text", "label": "Look (optional)",
                 "description": "e.g. “colourful”, “black and white”, “our CI: #003366 and #ff9900”."},
                {"key": "direction", "type": "choice", "label": "Direction", "default": "auto",
                 "options": [{"value": "auto", "label": "As it fits"},
                             {"value": "TB", "label": "Top to bottom"},
                             {"value": "LR", "label": "Left to right"}]},
                {"key": "folder", "type": "text", "label": "Output folder", "default": "diagrams",
                 "description": "Where the .drawio file and the PNG go – relative to the project's workspace."},
                {"key": "filename", "type": "text", "label": "File name (optional)",
                 "description": "e.g. login-flow – empty: a name from the diagram's title. Nothing is overwritten."},
                {"key": "scale", "type": "choice", "label": "PNG size", "default": "2",
                 "options": [{"value": "1", "label": "1× (small)"}, {"value": "2", "label": "2× (sharp)"},
                             {"value": "3", "label": "3× (print)"}]},
            ])

    # ------------------------------------------------------------------ the run
    async def run(self, node):
        tr = self.ctx.tr
        cfg = node.config
        material = material_of(node)
        desc = (cfg.get("description") or "").strip()
        if not desc and not material and not (node.instructions or "").strip():
            return node.route("error", tr("There is no description of the diagram – write it into the node or let "
                                          "the step before hand it over."))
        kind = self.kind(cfg, "\n".join((desc, material, node.instructions or "")))
        model = self.ctx.settings.get("model") or "sonnet"
        node.progress(tr("draws the diagram …"))
        prompt = self.prompt(node, desc, material, kind)
        try:
            answer = await self.ctx.ai.ask(prompt, system=SYSTEM, model=model)
        except Exception as exc:  # noqa: BLE001 - no Claude …
            return node.route("error", tr("The AI could not draw the diagram: {error}", error=exc))
        xml, errors, warnings = self.examine(answer)
        for _ in range(FIX_ROUNDS):
            if not errors and not warnings:
                break
            node.progress(tr("fixes {n} problem(s) …", n=len(errors) + len(warnings)))
            problems = "\n".join([f"- ERROR: {e}" for e in errors] + [f"- {w}" for w in warnings])
            fix = (f"{prompt}\n\nYOUR LAST ANSWER:\n{(xml or answer)[:60000]}\n\nIT HAS THESE PROBLEMS:\n{problems}\n\n"
                   "Answer with the corrected, complete draw.io XML only.")
            try:
                answer2 = await self.ctx.ai.ask(fix, system=SYSTEM, model=model)
            except Exception as exc:  # noqa: BLE001
                self.ctx.log.error(f"fix round: {exc}")
                break
            xml2, errors2, warnings2 = self.examine(answer2)
            if xml2 and (len(errors2), len(warnings2)) <= (len(errors), len(warnings)):
                xml, errors, warnings = xml2, errors2, warnings2
            if not errors and not warnings:
                break
        if errors or not xml:
            return node.route("error", tr("The diagram isn't usable: {problems}", problems="; ".join(errors)))

        title = self.title(xml) or kind
        out_dir = self.out_dir(node)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return node.route("error", tr("Can't create the output folder {folder}: {error}", folder=str(out_dir),
                                          error=exc))
        name = (cfg.get("filename") or "").strip()
        name = Path(name).stem if name else slug(title)
        if not NAME_OK.match(name):
            name = slug(name)
        drawio = unique(out_dir / f"{name}.drawio")
        drawio.write_text(xml, encoding="utf-8")
        png = drawio.with_suffix(".png")
        node.progress(tr("exports the PNG …"))
        try:
            size, how = await self.export(drawio, png, float(cfg.get("scale") or 2))
        except Exception as exc:  # noqa: BLE001
            return node.route("error", tr("The diagram is saved ({path}), but the PNG failed: {error}",
                                          path=str(drawio), error=exc))
        node.say(kind="diagram", data={"png": str(png), "drawio": str(drawio), "title": title, "type": kind,
                                       "width": size[0], "height": size[1], "warnings": warnings, "exporter": how},
                 text=f"📐 {title}\n{png}")
        node.progress(f"📐 {png.name}")
        notes = ("\n" + tr("Notes of the check: {notes}", notes="; ".join(warnings))) if warnings else ""
        return node.route("diagram", tr("Diagram “{title}” ({kind}, {w}×{h} px).", title=title, kind=kind,
                                        w=size[0], h=size[1]) + notes
                          + f"\nDRAWIO_FILE: {drawio}\nPNG_FILE: {png}")

    # ------------------------------------------------------------------ pieces
    def kind(self, cfg: dict, text: str) -> str:
        fixed = cfg.get("type") or "auto"
        if fixed != "auto":
            return fixed
        m = TYPE_LINE.search(text)
        if m:
            named = m.group(1).lower().replace("-", "")
            for v, _ in TYPES[1:]:
                if named.startswith(v) or v.startswith(named):
                    return v
        return "auto"

    def prompt(self, node, desc: str, material: str, kind: str) -> str:
        cfg = node.config
        parts = ["Draw exactly ONE diagram as a draw.io file."]
        if desc:
            parts.append(f"DESCRIPTION (from the node):\n{desc}")
        if (node.instructions or "").strip():
            parts.append(f"INSTRUCTIONS FOR THIS STEP:\n{node.instructions.strip()}")
        if material:
            parts.append(f"WHAT THIS STEP GOT (assignment and hand-overs – the description may come from here):\n"
                         f"{material[:30000]}")
        if kind == "auto":
            parts.append("KIND: the one the description asks for – if it names none, the kind that shows this best "
                         "(flowchart, sequence, UML class, activity, state, use case, ER, architecture, network, "
                         "deployment, swimlane process, org chart, mind map, timeline …).")
        else:
            label = dict(TYPES).get(kind, kind)
            parts.append(f"KIND: {label} – {HOW.get(kind, '')}".rstrip(" –"))
        if (cfg.get("style") or "").strip():
            parts.append(f"LOOK: {cfg['style'].strip()}")
        if cfg.get("direction") in ("TB", "LR"):
            parts.append("DIRECTION: " + ("top to bottom" if cfg["direction"] == "TB" else "left to right"))
        parts.append("RULES:\n" + "\n".join(f"- {r}" for r in [
            "Answer with the XML only: <mxfile host=\"Theron\"><diagram id=\"…\" name=\"<short title of the "
            "diagram>\"><mxGraphModel dx=\"1000\" dy=\"800\" grid=\"1\" gridSize=\"10\" guides=\"1\" page=\"1\" "
            "pageWidth=\"1169\" pageHeight=\"827\"><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/> … "
            "</root></mxGraphModel></diagram></mxfile> – uncompressed, no Markdown fences, no text around it.",
            "Every shape: vertex=\"1\", a unique id, parent=\"1\" (or its container), an mxGeometry with x, y, "
            "width, height (as=\"geometry\"). Every edge: edge=\"1\", source and target ids, "
            "<mxGeometry relative=\"1\" as=\"geometry\"/>.",
            "Lay it out cleanly on a grid of 10: no shapes on top of each other, at least 40 px between shapes, "
            "aligned rows / columns, edges without crossing where possible "
            "(edgeStyle=orthogonalEdgeStyle;rounded=0;html=1 for most diagrams).",
            "Readable labels in the description's language: shapes big enough for their text (whiteSpace=wrap;"
            "html=1), fontSize 12–14, a title only if it helps.",
            "Use common draw.io styles only: rounded=1, ellipse, rhombus, shape=cylinder3, shape=umlActor, "
            "shape=umlLifeline, swimlane, shape=note, shape=document, shape=cloud, shape=hexagon, text, "
            "fillColor / strokeColor / fontColor, dashed=1, endArrow / startArrow.",
            "A calm, consistent colour scheme (draw.io's pastel fills with matching strokes, e.g. #dae8fc/#6c8ebf, "
            "#d5e8d4/#82b366, #fff2cc/#d6b656, #f8cecc/#b85450) unless the look says otherwise.",
            "Show what the description says – complete, nothing invented.",
        ]))
        return "\n\n".join(parts)

    def examine(self, answer: str) -> tuple[str, list[str], list[str]]:
        try:
            xml = extract_xml(answer)
        except DiagramError as exc:
            return "", [str(exc)], []
        errors, warnings = check(xml)
        return xml, errors, warnings

    @staticmethod
    def title(xml: str) -> str:
        try:
            name, cs = cells(xml)
        except DiagramError:
            return ""
        if name and not re.fullmatch(r"(?i)page-?\d+", name):
            return name
        texts = [plain(c.value) for c in cs if c.vertex and plain(c.value)]
        return texts[0][:60] if texts else ""

    def out_dir(self, node) -> Path:
        sub = (node.config.get("folder") or "diagrams").strip() or "diagrams"
        ws = (node.project or {}).get("workspace") or ""
        base = Path(ws).expanduser() if ws else self.ctx.data_dir / "output"
        p = Path(sub).expanduser()
        return p if p.is_absolute() else base / p

    async def export(self, drawio: Path, png: Path, scale: float) -> tuple[tuple[int, int], str]:
        """The PNG the way the settings say: the plugin's own renderer, the desktop app or draw.io in Docker."""
        how = self.ctx.settings.get("exporter") or "builtin"
        if how == "desktop":
            await asyncio.to_thread(exporters.desktop, drawio, png, scale, self.ctx.settings.get("drawio_path") or "")
            return png_size(png), "draw.io desktop"
        if how == "docker":
            await asyncio.to_thread(exporters.docker, drawio, png, scale, self.ctx.settings.get("docker_image") or "")
            return png_size(png), "draw.io (Docker)"
        return await draw_png(self.ctx, drawio.read_text(encoding="utf-8"), png, scale), "built-in"


async def draw_png(ctx, xml: str, png: Path, scale: float) -> tuple[int, int]:
    from .render import render_png
    if ctx.ui.available:   # Qt draws text best on the UI thread
        return await ctx.ui.run(render_png, xml, str(png), scale)
    ensure_qt()
    return await asyncio.to_thread(render_png, xml, str(png), scale)


def ensure_qt() -> None:
    """Text needs a QGuiApplication – a slave or the console has none: an off-screen one."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        ensure_qt.app = QGuiApplication([])


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return 0, 0
