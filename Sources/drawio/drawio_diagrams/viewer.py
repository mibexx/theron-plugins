"""The large view of a diagram – a window of its own (``ctx.ui.open_window``): fit to the window or 100 %, zoom with
the buttons or Ctrl/⌘ + mouse wheel, open the .drawio file in draw.io, show the folder."""

from __future__ import annotations

from pathlib import Path

STEPS = (0.1, 0.15, 0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)


def viewer(ctx, png: str, drawio: str = ""):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

    tr = ctx.tr

    class Viewer(QWidget):
        def __init__(self):
            super().__init__()
            self.pixmap = QPixmap(png)
            self.zoom, self.fit = 1.0, True
            lay = QVBoxLayout(self)
            lay.setContentsMargins(8, 8, 8, 8)
            bar = QHBoxLayout()
            self.buttons = {}
            for key, text, tip in (("fit", tr("Fit"), tr("Fit into the window")), ("one", "100 %", tr("Real size")),
                                   ("out", "−", tr("Smaller")), ("in", "+", tr("Larger"))):
                b = QPushButton(text)
                b.setObjectName("ghost")
                b.setToolTip(tip)
                b.clicked.connect(lambda _=False, k=key: self.act(k))
                bar.addWidget(b)
                self.buttons[key] = b
            self.level = QLabel()
            bar.addWidget(self.level)
            bar.addStretch(1)
            if drawio and Path(drawio).is_file():
                edit = QPushButton("✎ " + tr("Open in draw.io"))
                edit.setObjectName("ghost")
                edit.clicked.connect(lambda: ctx.ui.open_url(Path(drawio).as_uri()))
                bar.addWidget(edit)
            folder = QPushButton("📂")
            folder.setObjectName("ghost")
            folder.setToolTip(tr("Show folder"))
            folder.clicked.connect(lambda: ctx.ui.open_url(Path(png).parent.as_uri()))
            bar.addWidget(folder)
            lay.addLayout(bar)
            self.area = QScrollArea()
            self.area.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.area.setStyleSheet("QScrollArea { background: #ffffff; border: none; }")
            self.image = QLabel()
            self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image.setStyleSheet("background: #ffffff;")
            self.area.setWidget(self.image)
            self.area.setWidgetResizable(False)
            self.area.viewport().installEventFilter(self)
            lay.addWidget(self.area, 1)
            self.show_image()

        def fit_zoom(self) -> float:
            if self.pixmap.isNull():
                return 1.0
            vp = self.area.viewport().size()
            return max(0.05, min(4.0, (vp.width() - 4) / self.pixmap.width(), (vp.height() - 4) / self.pixmap.height()))

        def act(self, key: str) -> None:
            if key == "fit":
                self.fit = True
            elif key == "one":
                self.fit, self.zoom = False, 1.0
            else:
                cur = self.fit_zoom() if self.fit else self.zoom
                bigger = [s for s in STEPS if s > cur + 1e-3]
                smaller = [s for s in STEPS if s < cur - 1e-3]
                self.fit = False
                self.zoom = (bigger[0] if bigger else STEPS[-1]) if key == "in" else (smaller[-1] if smaller else STEPS[0])
            self.show_image()

        def show_image(self) -> None:
            if self.pixmap.isNull():
                self.image.setText(tr("The picture can't be read."))
                return
            z = self.fit_zoom() if self.fit else self.zoom
            shown = self.pixmap.scaled(max(1, int(self.pixmap.width() * z)), max(1, int(self.pixmap.height() * z)),
                                       Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image.setPixmap(shown)
            self.image.resize(shown.size())
            self.level.setText(f"{round(z * 100)} %")

        def resizeEvent(self, event):  # noqa: N802
            super().resizeEvent(event)
            if self.fit:
                self.show_image()

        def eventFilter(self, obj, event):  # noqa: N802 - Ctrl/⌘ + wheel zooms
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.act("in" if event.angleDelta().y() > 0 else "out")
                return True
            return False

        def mouseDoubleClickEvent(self, event):  # noqa: N802 - double click: fit ↔ 100 %
            self.act("one" if self.fit else "fit")

    return Viewer()
