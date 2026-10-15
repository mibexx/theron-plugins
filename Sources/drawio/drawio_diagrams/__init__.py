"""draw.io Diagrams for Theron: 📐 Draw diagram as a process node – a .drawio file and a PNG per run. The picture shows
in the chat; a click opens it large in a window of its own (zoom, open in draw.io). The PNG comes from the plugin's
own renderer, the draw.io desktop app or draw.io in Docker (settings) – all through the plugin interface
(theron_api 1, Theron ≥ 0.20)."""

from __future__ import annotations

import asyncio
import html
import tempfile
from pathlib import Path

from . import exporters
from .node import DiagramNode, draw_png, png_size
from .viewer import viewer

CYAN, DIM, TEXT, LINE, AMBER = "#5ce1ff", "#6f8c99", "#cdeff6", "#1f6f8b", "#ffb547"
CHAT_WIDTH = 520
SAMPLE = """<mxfile host="Theron"><diagram id="t" name="Test"><mxGraphModel><root><mxCell id="0"/>
<mxCell id="1" parent="0"/>
<mxCell id="a" value="Theron" style="rounded=1;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
<mxGeometry x="0" y="0" width="120" height="50" as="geometry"/></mxCell>
<mxCell id="b" value="draw.io" style="ellipse;fillColor=#d5e8d4;strokeColor=#82b366;" vertex="1" parent="1">
<mxGeometry x="200" y="0" width="120" height="50" as="geometry"/></mxCell>
<mxCell id="e" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="a" target="b">
<mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def register(ctx):
    DiagramNode(ctx).register()
    tr = ctx.tr

    # ------------------------------------------------------------------ the chat: the picture, a click → large
    def link(action: str, inner: str, **params) -> str:
        a = ctx.chat.link(action, "§", **params)
        return a.replace("<a ", f'<a style="color:{CYAN}; text-decoration:none; font-weight:bold;" ', 1) \
            .replace(">§</a>", f">{inner}</a>")

    def card(data: dict) -> str:
        png, drawio = data.get("png") or "", data.get("drawio") or ""
        title = html.escape(data.get("title") or Path(png).stem)
        if not Path(png).is_file():
            return (f'<p>📐 <b style="color:{TEXT};">{title}</b> <span style="color:{DIM};">'
                    f'{html.escape(tr("The picture is gone."))}</span></p>')
        w, h = int(data.get("width") or 0), int(data.get("height") or 0)
        if not w or not h:
            w, h = png_size(Path(png))
        shown_w = min(CHAT_WIDTH, w // 2 if w > 2 * CHAT_WIDTH else w) or CHAT_WIDTH
        shown_h = int(h * shown_w / w) if w else 0
        img = (f'<img src="{Path(png).as_uri()}" width="{shown_w}" height="{shown_h}" '
               f'title="{html.escape(tr("Click to see it large"))}">')
        meta = " · ".join(x for x in (data.get("type") if data.get("type") != "auto" else "", f"{w}×{h} px",
                                      data.get("exporter") or "") if x)
        actions = " &nbsp; ".join([link("zoom", "🔍 " + html.escape(tr("Large view")), png=png, drawio=drawio,
                                        title=data.get("title") or "")]
                                  + ([link("open", "✎ " + html.escape(tr("Open in draw.io")), path=drawio)]
                                     if Path(drawio).is_file() else [])
                                  + [link("folder", "📂 " + html.escape(tr("Show folder")), path=png)])
        warn = "".join(f'<br><span style="color:{AMBER}; font-size:11px;">⚠ {html.escape(x)}</span>'
                       for x in data.get("warnings") or [])
        return (f'<p style="margin:2px 0 4px 0;">📐 <b style="color:{TEXT};">{title}</b> '
                f'<span style="color:{DIM}; font-size:11px;">{html.escape(meta)}</span></p>'
                f'<table cellspacing="0" cellpadding="6" style="background:#ffffff; border:1px solid {LINE};"><tr><td>'
                + link("zoom", img, png=png, drawio=drawio, title=data.get("title") or "")
                + f'</td></tr></table><p style="margin:4px 0 0 0;">{actions}{warn}</p>')

    def zoom(params: dict) -> None:
        png = params.get("png") or ""
        if not Path(png).is_file():
            ctx.notify(tr("The picture is gone: {path}", path=png), "error")
            return
        w, h = png_size(Path(png))
        ctx.ui.open_window("📐 " + (params.get("title") or Path(png).stem),
                           lambda view: viewer(ctx, png, params.get("drawio") or ""), id=f"zoom:{png}",
                           width=max(480, min(1280, w // 2 + 40)), height=max(360, min(900, h // 2 + 90)))

    def open_file(params: dict) -> None:
        p = Path(params.get("path") or "")
        if p.is_file():
            ctx.ui.open_url(p.as_uri())

    def open_folder(params: dict) -> None:
        p = Path(params.get("path") or "").parent
        if p.is_dir():
            ctx.ui.open_url(p.as_uri())

    ctx.chat.add_renderer("diagram", card)
    ctx.chat.on_link("zoom", zoom)
    ctx.chat.on_link("open", open_file)
    ctx.chat.on_link("folder", open_folder)

    # ------------------------------------------------------------------ settings: test the way to the PNG, load Docker
    async def test(values: dict):
        how = values.get("exporter") or "builtin"
        folder = Path(tempfile.mkdtemp(prefix="theron-drawio-"))
        drawio, png = folder / "test.drawio", folder / "test.png"
        drawio.write_text(SAMPLE, encoding="utf-8")
        try:
            if how == "desktop":
                app = exporters.find_drawio(values.get("drawio_path") or "")
                if not app:
                    return False, tr("The draw.io desktop app is not installed – install it from "
                                     "https://www.drawio.com or enter its path.")
                await asyncio.to_thread(exporters.desktop, drawio, png, 1, app)
                where = app
            elif how == "docker":
                image = values.get("docker_image") or exporters.DEFAULT_IMAGE
                ok, why = await asyncio.to_thread(exporters.docker_ready, image)
                if not ok:
                    return False, tr("Docker isn't ready: {why}", why=why) + (
                        " – " + tr("click “Load Docker image”.") if "isn't loaded" in why else "")
                await asyncio.to_thread(exporters.docker, drawio, png, 1, image)
                where = image
            else:
                await draw_png(ctx, SAMPLE, png, 1)
                where = tr("the plugin's own renderer")
        except Exception as exc:  # noqa: BLE001 - shown in the dialog
            return False, tr("The test export failed: {error}", error=exc)
        w, h = png_size(png)
        return True, tr("Works – a test diagram became a PNG of {w}×{h} px with {where}.", w=w, h=h, where=where)

    async def pull(values: dict):
        image = values.get("docker_image") or exporters.DEFAULT_IMAGE
        if not exporters.find_docker():
            return False, tr("Docker is not installed – https://www.docker.com/products/docker-desktop/")
        try:
            last = await asyncio.to_thread(exporters.docker_pull, image)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return True, tr("Loaded: {image}. {last}", image=image, last=last)

    async def edited(values: dict, key: str):
        """Choosing “Use the desktop app” (or typing its path): is draw.io there? If not, ask where it is."""
        how = values.get("exporter") or "builtin"
        if how == "docker" and key == "exporter":   # is Docker installed and running, is the image there?
            if not exporters.find_docker():
                return False, tr("Docker is not installed – https://www.docker.com/products/docker-desktop/")
            ok, why = await asyncio.to_thread(exporters.docker_ready, values.get("docker_image")
                                              or exporters.DEFAULT_IMAGE)
            return (True, tr("Docker is ready, the image is loaded.")) if ok else \
                (False, tr("Docker isn't ready: {why}", why=why) + (" – " + tr("click “Load Docker image”.")
                                                                   if "isn't loaded" in why else ""))
        if how != "desktop":
            return None
        typed = (values.get("drawio_path") or "").strip()
        app = exporters.find_drawio(typed) if not typed or Path(typed).expanduser().is_file() else ""
        if typed and not app and key == "drawio_path":
            app = exporters.resolve_app(typed) if Path(typed).expanduser().exists() else ""
        if app:
            try:
                version = await asyncio.to_thread(exporters.desktop_version, app)
                return {"values": {"drawio_path": app}, "ok": True,
                        "text": tr("draw.io {version} found: {path}", version=version, path=app)}
            except Exception as exc:  # noqa: BLE001 - found something, but it doesn't work: ask
                ctx.log.error(f"draw.io check {app}: {exc}")
        picked = await ctx.ui.run(lambda: ctx.ui.ask_files(
            tr("Where is the draw.io app?"), "draw.io (*.app *.exe draw.io drawio *)", multiple=False,
            start="/Applications" if Path("/Applications").is_dir() else ""))
        if not picked:
            return False, tr("draw.io wasn't found – choose the program, or install it from https://www.drawio.com")
        exe = exporters.resolve_app(picked[0])
        try:
            version = await asyncio.to_thread(exporters.desktop_version, exe)
        except Exception as exc:  # noqa: BLE001
            return False, tr("That isn't a working draw.io: {error}", error=exc)
        return {"values": {"drawio_path": exe}, "ok": True,
                "text": tr("draw.io {version} found: {path}", version=version, path=exe)}

    if hasattr(ctx.settings, "on_edit"):
        ctx.settings.on_edit(edited, keys=["exporter", "drawio_path"])
    ctx.settings.add_button("Test", test, tooltip="Turns a small test diagram into a PNG the chosen way.")
    ctx.settings.add_button("Load Docker image", pull, id="pull",
                            tooltip="Fetches the draw.io Docker image (once, about 1 GB).")
