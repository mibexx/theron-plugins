"""The draw.io file: read what the AI wrote, check it, and turn it into cells the renderer can draw.

A .drawio file is ``<mxfile><diagram name="…"><mxGraphModel><root><mxCell …/>…`` – cells are vertices (shapes) and
edges (arrows) with a ``style`` ("rounded=1;fillColor=#dae8fc;…") and an ``mxGeometry``. draw.io may store the model
compressed (deflate + base64 + URL encoding) – both are read.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field


@dataclass
class Cell:
    id: str
    value: str = ""
    style: dict = field(default_factory=dict)
    vertex: bool = False
    edge: bool = False
    parent: str = ""
    source: str = ""
    target: str = ""
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    points: list[tuple[float, float]] = field(default_factory=list)
    source_point: tuple[float, float] | None = None
    target_point: tuple[float, float] | None = None
    offset: tuple[float, float] = (0, 0)   # an edge label's offset
    rel_x: float = 0                        # an edge label's position along the edge (-1 … 1)


class DiagramError(ValueError):
    pass


def parse_style(text: str) -> dict:
    out = {}
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out["shape" if "shape" not in out else part.strip()] = part.strip()   # "ellipse;" / "text;" / "rhombus;"
    return out


def extract_xml(text: str) -> str:
    """The <mxfile> (or a bare <mxGraphModel>) out of an AI answer – fences and talk around it are dropped."""
    text = re.sub(r"```(?:xml)?", "", text or "")
    for start, end in (("<mxfile", "</mxfile>"), ("<mxGraphModel", "</mxGraphModel>")):
        a, b = text.find(start), text.rfind(end)
        if a >= 0 and b > a:
            xml = text[a:b + len(end)]
            if start == "<mxGraphModel":
                xml = f'<mxfile host="Theron"><diagram id="d1" name="Page-1">{xml}</diagram></mxfile>'
            return xml
    raise DiagramError("no <mxfile> in the answer")


def _model(diagram: ET.Element) -> ET.Element:
    model = diagram.find("mxGraphModel")
    if model is not None:
        return model
    raw = (diagram.text or "").strip()
    if not raw:
        raise DiagramError("the <diagram> is empty")
    try:   # compressed: base64 → raw deflate → URL-encoded XML
        xml = urllib.parse.unquote(zlib.decompress(base64.b64decode(raw), -15).decode("utf-8"))
        return ET.fromstring(xml)
    except Exception as exc:  # noqa: BLE001
        raise DiagramError(f"the compressed diagram can't be read: {exc}") from exc


def cells(xml: str, page: int = 0) -> tuple[str, list[Cell]]:
    """(page name, the cells) of one page."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DiagramError(f"the XML is broken: {exc}") from exc
    diagrams = root.findall("diagram") if root.tag == "mxfile" else []
    if root.tag == "mxGraphModel":
        model, name = root, ""
    elif diagrams:
        d = diagrams[min(page, len(diagrams) - 1)]
        model, name = _model(d), d.get("name", "")
    else:
        raise DiagramError("no <diagram> in the <mxfile>")
    r = model.find("root")
    if r is None:
        raise DiagramError("no <root> in the <mxGraphModel>")
    out = []
    for el in r:
        if el.tag not in ("mxCell", "object", "UserObject"):
            continue
        cell_el = el if el.tag == "mxCell" else el.find("mxCell")
        if cell_el is None:
            continue
        c = Cell(id=el.get("id") or cell_el.get("id") or "",
                 value=el.get("label", "") if el.tag != "mxCell" else (cell_el.get("value") or ""),
                 style=parse_style(cell_el.get("style", "")), vertex=cell_el.get("vertex") == "1",
                 edge=cell_el.get("edge") == "1", parent=cell_el.get("parent", ""),
                 source=cell_el.get("source", ""), target=cell_el.get("target", ""))
        g = cell_el.find("mxGeometry")
        if g is not None:
            c.x, c.y = _f(g.get("x")), _f(g.get("y"))
            c.w, c.h = _f(g.get("width")), _f(g.get("height"))
            for p in g:
                if p.tag == "mxPoint":
                    pt = (_f(p.get("x")), _f(p.get("y")))
                    role = p.get("as")
                    if role == "sourcePoint":
                        c.source_point = pt
                    elif role == "targetPoint":
                        c.target_point = pt
                    elif role == "offset":
                        c.offset = pt
                elif p.tag == "Array" and p.get("as") == "points":
                    c.points = [(_f(q.get("x")), _f(q.get("y"))) for q in p.findall("mxPoint")]
            if c.edge:
                c.rel_x = c.x
        out.append(c)
    return name, out


def check(xml: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a draw.io file – errors: it can't be opened or drawn; warnings: it looks bad."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        _, cs = cells(xml)
    except DiagramError as exc:
        return [str(exc)], []
    ids = [c.id for c in cs]
    by_id = {c.id: c for c in cs}
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append("duplicate cell ids: " + ", ".join(dup[:8]))
    if "" in ids:
        errors.append("a cell without id")
    vertices = [c for c in cs if c.vertex]
    edges = [c for c in cs if c.edge]
    if not vertices:
        errors.append("the diagram has no shapes")
    for c in cs:
        if c.parent and c.parent not in by_id:
            errors.append(f"cell {c.id}: its parent {c.parent} doesn't exist")
    for c in vertices:
        if c.w <= 0 or c.h <= 0:
            errors.append(f"shape {c.id} ({_short(c.value)}): no width/height in its mxGeometry")
    for e in edges:
        for end, ref, pt in (("source", e.source, e.source_point), ("target", e.target, e.target_point)):
            if ref and ref not in by_id:
                errors.append(f"edge {e.id}: its {end} {ref} doesn't exist")
            elif not ref and pt is None:
                errors.append(f"edge {e.id}: no {end} (neither a cell nor a point)")
    # shapes on top of each other (siblings only – a shape in a container is meant to be inside)
    boxes = [(c, absolute(c, by_id)) for c in vertices if c.w > 0 and c.h > 0
             and c.style.get("shape") not in ("text",) and "text" not in c.style
             and not _container(c, cs)]
    overlaps = []
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1:]:
            if a.parent == b.parent and _overlap(ra, rb) > 0.25 * min(ra[2] * ra[3], rb[2] * rb[3]):
                overlaps.append(f"{_short(a.value) or a.id} / {_short(b.value) or b.id}")
    if overlaps:
        warnings.append("shapes overlap: " + "; ".join(overlaps[:6]))
    return errors, warnings


def absolute(c: Cell, by_id: dict) -> tuple[float, float, float, float]:
    """A vertex's box on the page – children of containers (groups, swimlanes) are relative to them."""
    x, y = c.x, c.y
    p = by_id.get(c.parent)
    seen = set()
    while p is not None and p.vertex and p.id not in seen:
        seen.add(p.id)
        x, y = x + p.x, y + p.y
        p = by_id.get(p.parent)
    return x, y, c.w, c.h


def _container(c: Cell, cs: list[Cell]) -> bool:
    return any(o.parent == c.id for o in cs) or "swimlane" in c.style or c.style.get("shape") == "swimlane" \
        or c.style.get("container") == "1" or c.style.get("group") is not None


def _overlap(a, b) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def plain(value: str) -> str:
    """A cell's label as text (labels may be HTML: <b>, <br>, &nbsp; …)."""
    text = re.sub(r"(?i)<br\s*/?>|</(?:div|p|li)>", "\n", value or "")
    text = re.sub(r"<[^>]+>", "", text)
    import html
    return html.unescape(text).replace("\xa0", " ").strip()


def _short(v: str, n: int = 24) -> str:
    t = " ".join(plain(v).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
