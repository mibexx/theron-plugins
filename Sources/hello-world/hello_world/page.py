from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class HelloPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        title = QLabel("HELLO WORLD")
        title.setObjectName("h1")
        text = QLabel(ctx.tr("Hello from the plugin “{name}” {version}.", name=ctx.name, version=ctx.version))
        text.setObjectName("dim")
        for w in (title, text):
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
