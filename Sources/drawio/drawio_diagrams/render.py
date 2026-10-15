"""The plugin's own PNG export: draws a draw.io page with Qt (QPainter on a QImage – no window, no draw.io app
needed, so it works on a slave and in Docker, too).

It knows what diagrams are mostly made of: rectangles (rounded), ellipses, rhombi, cylinders, hexagons,
parallelograms, notes, documents, clouds, actors, swimlanes / containers, UML lifelines, plain text and images by
nothing; colours, gradients-free fills, dashed lines, shadows, font size / colour / bold, label positions; edges with
waypoints, orthogonal routing, arrow heads (block, classic, open, diamond, oval, ER ends) and labels.
What it can't draw it draws as a rectangle – the .drawio file itself stays exact.
"""

from __future__ import annotations

import math

from .model import Cell, absolute, cells, plain

PAD = 20


def _qt():
    from PySide6 import QtCore, QtGui
    return QtCore, QtGui


def color(value: str | None, default: str | None):
    _, QtGui = _qt()
    if value in (None, ""):
        value = default
    if value in (None, "none", "None"):
        return None
    c = QtGui.QColor(value)
    return c if c.isValid() else (QtGui.QColor(default) if default else None)


def render_png(xml: str, path: str, scale: float = 2.0, background: str = "#ffffff") -> tuple[int, int]:
    """Draw the first page into ``path`` → (width, height) in pixels."""
    QtCore, QtGui = _qt()
    _, cs = cells(xml)
    by_id = {c.id: c for c in cs}
    boxes = {c.id: absolute(c, by_id) for c in cs if c.vertex}
    pts = []
    for x, y, w, h in boxes.values():
        pts += [(x, y), (x + w, y + h)]
    for e in (c for c in cs if c.edge):
        pts += e.points + [p for p in (e.source_point, e.target_point) if p]
    if not pts:
        pts = [(0, 0), (100, 60)]
    min_x, min_y = min(p[0] for p in pts) - PAD, min(p[1] for p in pts) - PAD
    max_x, max_y = max(p[0] for p in pts) + PAD, max(p[1] for p in pts) + PAD
    width, height = int((max_x - min_x) * scale) + 1, int((max_y - min_y) * scale) + 1
    image = QtGui.QImage(max(1, width), max(1, height), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(background) if background else QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(image)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    p.scale(scale, scale)
    p.translate(-min_x, -min_y)
    order = {c.id: i for i, c in enumerate(cs)}
    # containers first (they are behind their children), then the shapes, then the edges on top
    for c in sorted((c for c in cs if c.vertex), key=lambda c: (_depth(c, by_id), order[c.id])):
        _vertex(p, c, boxes[c.id])
    for e in (c for c in cs if c.edge):
        _edge(p, e, by_id, boxes)
    p.end()
    if not image.save(str(path), "PNG"):
        raise OSError(f"can't write {path}")
    return width, height


def _depth(c: Cell, by_id: dict) -> int:
    d, p, seen = 0, by_id.get(c.parent), set()
    while p is not None and p.vertex and p.id not in seen:
        seen.add(p.id)
        d += 1
        p = by_id.get(p.parent)
    return d


# ------------------------------------------------------------------ shapes
def _vertex(p, c: Cell, box) -> None:
    QtCore, QtGui = _qt()
    s = c.style
    x, y, w, h = box
    shape = s.get("shape", "rect")
    if shape in ("text", "label") or "text" in s and shape == "rect":
        _label(p, c, QtCore.QRectF(x, y, w, h))
        return
    if shape == "image":
        return
    fill = color(s.get("fillColor"), "#ffffff")
    stroke = color(s.get("strokeColor"), "#000000")
    pen = QtGui.QPen(stroke) if stroke else QtGui.QPen(QtCore.Qt.PenStyle.NoPen)
    if stroke:
        pen.setWidthF(float(s.get("strokeWidth") or 1))
        if s.get("dashed") == "1":
            pen.setDashPattern([4, 3])
    p.setPen(pen)
    brush = QtGui.QBrush(fill) if fill else QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)
    if fill and s.get("opacity"):
        fill.setAlphaF(max(0.0, min(1.0, float(s["opacity"]) / 100)))
        brush = QtGui.QBrush(fill)
    p.setBrush(brush)
    r = QtCore.QRectF(x, y, w, h)
    if s.get("shadow") == "1" and fill:
        p.save()
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 40))
        p.drawPath(_path(shape, s, r.translated(3, 3)))
        p.restore()
    label_rect = r
    if shape in ("swimlane", "table") or "swimlane" in s:
        start = float(s.get("startSize") or 26)
        horizontal = s.get("horizontal", "1") != "0"
        head = QtCore.QRectF(x, y, w, start) if horizontal else QtCore.QRectF(x, y, start, h)
        p.drawRect(r)
        p.setBrush(QtGui.QBrush(color(s.get("swimlaneFillColor"), None) or fill or QtGui.QColor("#ffffff")))
        p.drawRect(head)
        if not horizontal:
            p.save()
            p.translate(head.center())
            p.rotate(-90)
            _label(p, c, QtCore.QRectF(-head.height() / 2, -head.width() / 2, head.height(), head.width()),
                   valign="middle")
            p.restore()
            return
        _label(p, c, head, valign="middle")
        return
    if shape == "umlLifeline":
        top = float(s.get("size") or 40)
        head = QtCore.QRectF(x, y, w, top)
        p.drawRect(head)
        dash = QtGui.QPen(stroke or QtGui.QColor("#000000"))
        dash.setDashPattern([4, 3])
        p.setPen(dash)
        p.drawLine(QtCore.QPointF(x + w / 2, y + top), QtCore.QPointF(x + w / 2, y + h))
        _label(p, c, head, valign="middle")
        return
    if shape == "umlActor":
        _actor(p, r)
        _label(p, c, QtCore.QRectF(x - 40, y + h, w + 80, 20), valign="top")
        return
    p.drawPath(_path(shape, s, r))
    if shape in ("cylinder", "cylinder3", "datastore"):
        cap = min(h * 0.15, float(s.get("size") or 15))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(x, y, w, cap * 2), 180 * 16, 180 * 16)
        label_rect = QtCore.QRectF(x, y + cap * 2, w, h - cap * 2)
    _label(p, c, label_rect)


def _path(shape: str, s: dict, r):
    QtCore, QtGui = _qt()
    path = QtGui.QPainterPath()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    poly = None
    if shape == "ellipse" or shape == "doubleEllipse":
        path.addEllipse(r)
        return path
    if shape == "rhombus":
        poly = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    elif shape == "hexagon":
        d = min(w * 0.2, float(s.get("size") or w * 0.2))
        poly = [(x + d, y), (x + w - d, y), (x + w, y + h / 2), (x + w - d, y + h), (x + d, y + h), (x, y + h / 2)]
    elif shape == "parallelogram":
        d = w * 0.2
        poly = [(x + d, y), (x + w, y), (x + w - d, y + h), (x, y + h)]
    elif shape == "trapezoid":
        d = w * 0.2
        poly = [(x + d, y), (x + w - d, y), (x + w, y + h), (x, y + h)]
    elif shape == "triangle":
        poly = [(x, y), (x + w, y + h / 2), (x, y + h)]
    elif shape in ("note", "card"):
        d = min(15.0, w / 4, h / 4)
        poly = [(x, y), (x + w - d, y), (x + w, y + d), (x + w, y + h), (x, y + h)] if shape == "note" else \
            [(x + d, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y + d)]
    elif shape == "step":
        d = w * 0.15
        poly = [(x, y), (x + w - d, y), (x + w, y + h / 2), (x + w - d, y + h), (x, y + h), (x + d, y + h / 2)]
    elif shape == "process":
        path.addRect(r)
        d = w * 0.1
        path.moveTo(x + d, y)
        path.lineTo(x + d, y + h)
        path.moveTo(x + w - d, y)
        path.lineTo(x + w - d, y + h)
        return path
    elif shape == "document":
        wave = h * 0.15
        path.moveTo(x, y)
        path.lineTo(x + w, y)
        path.lineTo(x + w, y + h - wave)
        path.cubicTo(x + w * 0.75, y + h - wave * 2, x + w * 0.25, y + h + wave * 0.5, x, y + h - wave)
        path.closeSubpath()
        return path
    elif shape in ("cylinder", "cylinder3", "datastore"):
        cap = min(h * 0.15, float(s.get("size") or 15))
        path.moveTo(x, y + cap)
        path.arcTo(QtCore.QRectF(x, y, w, cap * 2), 180, -180)
        path.lineTo(x + w, y + h - cap)
        path.arcTo(QtCore.QRectF(x, y + h - cap * 2, w, cap * 2), 0, -180)
        path.closeSubpath()
        return path
    elif shape == "cloud":
        path.addEllipse(QtCore.QRectF(x, y + h * 0.25, w * 0.5, h * 0.6))
        path.addEllipse(QtCore.QRectF(x + w * 0.25, y, w * 0.5, h * 0.7))
        path.addEllipse(QtCore.QRectF(x + w * 0.5, y + h * 0.2, w * 0.5, h * 0.65))
        path.addEllipse(QtCore.QRectF(x + w * 0.2, y + h * 0.4, w * 0.6, h * 0.6))
        path.setFillRule(QtCore.Qt.FillRule.WindingFill)   # one outline, not four overlapping ellipses
        return path.simplified()
    if poly:
        path.addPolygon(QtGui.QPolygonF([QtCore.QPointF(a, b) for a, b in poly]))
        path.closeSubpath()
        return path
    if s.get("rounded") == "1":
        rad = float(s.get("arcSize") or 15) / 100 * min(w, h)
        if s.get("absoluteArcSize") == "1":
            rad = float(s.get("arcSize") or 10)
        path.addRoundedRect(r, rad, rad)
    else:
        path.addRect(r)
    return path


def _actor(p, r) -> None:
    QtCore, _ = _qt()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    head = min(w, h / 4)
    p.drawEllipse(QtCore.QRectF(x + w / 2 - head / 2, y, head, head))
    p.drawLine(QtCore.QPointF(x + w / 2, y + head), QtCore.QPointF(x + w / 2, y + h * 0.65))
    p.drawLine(QtCore.QPointF(x, y + h * 0.4), QtCore.QPointF(x + w, y + h * 0.4))
    p.drawLine(QtCore.QPointF(x + w / 2, y + h * 0.65), QtCore.QPointF(x, y + h))
    p.drawLine(QtCore.QPointF(x + w / 2, y + h * 0.65), QtCore.QPointF(x + w, y + h))


def _font(s: dict):
    _, QtGui = _qt()
    f = QtGui.QFont(s.get("fontFamily") or "Helvetica")
    f.setPixelSize(max(6, int(float(s.get("fontSize") or 12))))
    style = int(float(s.get("fontStyle") or 0))
    f.setBold(bool(style & 1))
    f.setItalic(bool(style & 2))
    f.setUnderline(bool(style & 4))
    return f


def _label(p, c: Cell, r, valign: str | None = None) -> None:
    QtCore, QtGui = _qt()
    text = plain(c.value)
    if not text or c.style.get("noLabel") == "1":
        return
    s = c.style
    p.save()
    p.setFont(_font(s))
    p.setPen(color(s.get("fontColor"), "#000000") or QtGui.QColor("#000000"))
    align = {"left": QtCore.Qt.AlignmentFlag.AlignLeft, "right": QtCore.Qt.AlignmentFlag.AlignRight}.get(
        s.get("align", "center"), QtCore.Qt.AlignmentFlag.AlignHCenter)
    v = valign or s.get("verticalAlign", "middle")
    align |= {"top": QtCore.Qt.AlignmentFlag.AlignTop, "bottom": QtCore.Qt.AlignmentFlag.AlignBottom}.get(
        v, QtCore.Qt.AlignmentFlag.AlignVCenter)
    pos = s.get("verticalLabelPosition")
    if pos == "bottom":
        r = QtCore.QRectF(r.x() - 40, r.bottom() + 2, r.width() + 80, 40)
        align = QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop
    elif pos == "top":
        r = QtCore.QRectF(r.x() - 40, r.top() - 42, r.width() + 80, 40)
        align = QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom
    sp = float(s.get("spacing") or 2)
    inner = r.adjusted(sp + float(s.get("spacingLeft") or 2), sp + float(s.get("spacingTop") or 0),
                       -(sp + float(s.get("spacingRight") or 2)), -(sp + float(s.get("spacingBottom") or 0)))
    p.drawText(inner, int(align) | int(QtCore.Qt.TextFlag.TextWordWrap), text)
    p.restore()


# ------------------------------------------------------------------ edges
def _edge(p, e: Cell, by_id: dict, boxes: dict) -> None:
    QtCore, QtGui = _qt()
    s = e.style
    src, dst = boxes.get(e.source), boxes.get(e.target)
    if src is None and e.source_point is None or dst is None and e.target_point is None:
        return
    off = (0.0, 0.0)
    parent = by_id.get(e.parent)
    if parent is not None and parent.vertex:   # waypoints are relative to the edge's parent container
        px, py, _, _ = boxes.get(parent.id, (0, 0, 0, 0))
        off = (px, py)
    pts = [(x + off[0], y + off[1]) for x, y in e.points]
    sp = _anchor(src, s, "exit") if src else (e.source_point[0] + off[0], e.source_point[1] + off[1])
    tp = _anchor(dst, s, "entry") if dst else (e.target_point[0] + off[0], e.target_point[1] + off[1])
    first = pts[0] if pts else (tp if tp else _center(dst))
    last = pts[-1] if pts else (sp if sp else _center(src))
    a = sp or _clip(src, first)
    b = tp or _clip(dst, last)
    line = [a] + pts + [b]
    if "orthogonal" in (s.get("edgeStyle") or "") or s.get("edgeStyle") in ("elbowEdgeStyle", "entityRelationEdgeStyle"):
        line = _orthogonal(line, src, dst, sp is None, tp is None)
    stroke = color(s.get("strokeColor"), "#000000") or QtGui.QColor("#000000")
    pen = QtGui.QPen(stroke)
    pen.setWidthF(float(s.get("strokeWidth") or 1))
    if s.get("dashed") == "1":
        pen.setDashPattern([4, 3])
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    path = QtGui.QPainterPath(QtCore.QPointF(*line[0]))
    for q in line[1:]:
        path.lineTo(QtCore.QPointF(*q))
    p.drawPath(path)
    solid = QtGui.QPen(stroke)
    solid.setWidthF(pen.widthF())
    p.setPen(solid)
    _arrow(p, line[-2], line[-1], s.get("endArrow", "classic"), s.get("endFill", "1") != "0", stroke)
    _arrow(p, line[1], line[0], s.get("startArrow", "none"), s.get("startFill", "1") != "0", stroke)
    text = plain(e.value)
    if text:
        mx, my = _along(line, (e.rel_x + 1) / 2 if e.rel_x else 0.5)
        mx, my = mx + e.offset[0], my + e.offset[1]
        p.setFont(_font(s))
        fm = QtGui.QFontMetricsF(p.font())
        lines = text.split("\n")
        tw = max(fm.horizontalAdvance(t) for t in lines) + 6
        th = fm.height() * len(lines) + 2
        box = QtCore.QRectF(mx - tw / 2, my - th / 2, tw, th)
        above = s.get("verticalAlign") == "bottom"     # draw.io: the label sits on top of the line
        below = s.get("verticalAlign") == "top"
        if above or below:
            box.moveTop(my - th - 1 if above else my + 1)
        bg = color(s.get("labelBackgroundColor"), None if above or below else "#ffffff")
        if bg:
            p.fillRect(box, bg)
        p.setPen(color(s.get("fontColor"), "#000000"))
        p.drawText(box, int(QtCore.Qt.AlignmentFlag.AlignCenter), text)


def _center(b):
    x, y, w, h = b
    return x + w / 2, y + h / 2


def _anchor(b, s: dict, kind: str):
    """exitX/exitY (entryX/entryY): a fixed point on the shape's border."""
    if f"{kind}X" not in s or f"{kind}Y" not in s:
        return None
    x, y, w, h = b
    try:
        return x + w * float(s[f"{kind}X"]), y + h * float(s[f"{kind}Y"])
    except ValueError:
        return None


def _clip(b, toward):
    """Where the line from the shape's centre toward a point leaves the shape's box."""
    cx, cy = _center(b)
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    _, _, w, h = b
    tx = (w / 2) / abs(dx) if dx else math.inf
    ty = (h / 2) / abs(dy) if dy else math.inf
    t = min(tx, ty)
    return cx + dx * t, cy + dy * t


def _orthogonal(line, src, dst, free_start: bool, free_end: bool):
    """Turn a straight connection into horizontal / vertical segments (what orthogonalEdgeStyle looks like)."""
    if len(line) > 2:   # waypoints given: connect them with right angles
        out = [line[0]]
        for q in line[1:]:
            px, py = out[-1]
            if px != q[0] and py != q[1]:
                out.append((q[0], py) if abs(q[0] - px) > abs(q[1] - py) else (px, q[1]))
            out.append(q)
        return out
    if src is None or dst is None:
        return line
    (sx, sy, sw, sh), (tx, ty, tw, th) = src, dst
    scx, scy, tcx, tcy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
    a, b = line
    if tx > sx + sw or tx + tw < sx:   # side by side: out of the side, in at the side
        a = (sx + sw, scy) if tcx > scx else (sx, scy)
        b = (tx, tcy) if tcx > scx else (tx + tw, tcy)
        if not free_start:
            a = line[0]
        if not free_end:
            b = line[1]
        if abs(a[1] - b[1]) < 1:
            return [a, b]
        mid = (a[0] + b[0]) / 2
        return [a, (mid, a[1]), (mid, b[1]), b]
    a = (scx, sy + sh) if tcy > scy else (scx, sy)   # above / below each other
    b = (tcx, ty) if tcy > scy else (tcx, ty + th)
    if not free_start:
        a = line[0]
    if not free_end:
        b = line[1]
    if abs(a[0] - b[0]) < 1:
        return [a, b]
    mid = (a[1] + b[1]) / 2
    return [a, (a[0], mid), (b[0], mid), b]


def _along(line, t: float):
    lengths = [math.dist(line[i], line[i + 1]) for i in range(len(line) - 1)]
    total = sum(lengths) or 1
    goal = total * t
    for i, seg in enumerate(lengths):
        if goal <= seg or i == len(lengths) - 1:
            f = goal / seg if seg else 0
            return (line[i][0] + (line[i + 1][0] - line[i][0]) * f, line[i][1] + (line[i + 1][1] - line[i][1]) * f)
        goal -= seg
    return line[-1]


def _arrow(p, frm, to, kind: str, filled: bool, stroke) -> None:
    QtCore, QtGui = _qt()
    if not kind or kind == "none":
        return
    ang = math.atan2(to[1] - frm[1], to[0] - frm[0])
    size = 9.0

    def at(dist, side):
        return QtCore.QPointF(to[0] - dist * math.cos(ang) + side * math.sin(ang),
                              to[1] - dist * math.sin(ang) - side * math.cos(ang))
    tip = QtCore.QPointF(*to)
    p.save()
    p.setBrush(QtGui.QBrush(stroke if filled else QtGui.QColor("#ffffff")))
    if kind in ("block", "classic", "classicThin", "blockThin"):
        pts = [tip, at(size, size * 0.45), at(size * (0.7 if kind.startswith("classic") else 1), 0),
               at(size, -size * 0.45)]
        p.drawPolygon(QtGui.QPolygonF(pts))
    elif kind in ("open", "openThin", "async"):
        p.drawPolyline(QtGui.QPolygonF([at(size, size * 0.45), tip, at(size, -size * 0.45)]))
    elif kind in ("diamond", "diamondThin"):
        side = size * (0.3 if kind == "diamondThin" else 0.45)
        p.drawPolygon(QtGui.QPolygonF([tip, at(size, side), at(size * 2, 0), at(size, -side)]))
    elif kind in ("oval", "circle", "dot"):
        c = at(size / 2, 0)
        p.drawEllipse(c, size / 2.5, size / 2.5)
    elif kind.startswith("ER"):   # ERone, ERmany, ERmandOne, ERzeroToMany, ERoneToMany, ERzeroToOne
        if "Many" in kind or kind == "ERmany":
            p.drawLine(at(0, size * 0.5), at(size, 0))
            p.drawLine(at(0, -size * 0.5), at(size, 0))
        if "mandOne" in kind or "oneTo" in kind or kind == "ERone":
            p.drawLine(at(size * 1.2, size * 0.5), at(size * 1.2, -size * 0.5))
        if "mandOne" in kind:
            p.drawLine(at(size * 0.7, size * 0.5), at(size * 0.7, -size * 0.5))
        if "zero" in kind:
            p.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
            p.drawEllipse(at(size * 1.7, 0), size * 0.35, size * 0.35)
    else:
        p.drawPolygon(QtGui.QPolygonF([tip, at(size, size * 0.45), at(size, -size * 0.45)]))
    p.restore()
