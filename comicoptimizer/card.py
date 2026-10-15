"""Card di un fumetto nella griglia."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .style import set_variant

# --- UI ---

# dizionario status come costante di modulo
_STATUS_MAP = {
    0: ("DA SISTEMARE", "#b71c1c", "white"),
    1: ("OK",           "#1b5e20", "#a5d6a7"),
    2: ("RIPARATO",     "#fbc02d", "black"),
    3: ("CONVERTITO",   "#00c853", "white"),
    4: ("SALTATO",      "#455a64", "white"),
    5: ("DANNEGGIATO",  "#000000", "#ff1744"),
}

class ComicCard(QFrame):
    edit_requested    = pyqtSignal(str)
    repair_requested  = pyqtSignal(str)
    remove_requested  = pyqtSignal(str)
    trash_requested   = pyqtSignal(str)
    rename_requested  = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.file_path   = path
        self.setFixedSize(195, 385)
        self.status_code = -1
        self.selected    = False
        self.update_style()

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 5)

        self.status = QLabel("...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self.status)

        self.thumb = QLabel("...")
        self.thumb.setFixedSize(175, 230)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.page_badge = QLabel("-", self.thumb)
        self.page_badge.setFixedWidth(175)
        self.page_badge.setFixedHeight(24)
        self.page_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_badge.setStyleSheet(
            "background: rgba(0, 229, 255, 180); color: black; font-weight: 900; "
            "font-size: 11px; border-top: 1px solid white; border-bottom: 1px solid white;"
        )
        self.page_badge.move(0, 105)
        l.addWidget(self.thumb)

        self.name = QLabel(os.path.basename(path))
        self.name.setWordWrap(True)
        self.name.setStyleSheet("font-size: 9px; color: #eee;")
        self.name.setMaximumHeight(35)
        l.addWidget(self.name)

        btns = QHBoxLayout()
        btns.setSpacing(2)
        self.btn_e = QPushButton("Edita")
        self.btn_e.clicked.connect(lambda: self.edit_requested.emit(self.file_path))
        self.btn_r = QPushButton("Fix")
        set_variant(self.btn_r, "primary")
        self.btn_d = QPushButton("X")
        self.btn_d.setFixedWidth(34)
        set_variant(self.btn_d, "danger")
        for _b in (self.btn_e, self.btn_r, self.btn_d):
            _b.setProperty("sz", "small")
        for _b in (self.btn_e, self.btn_r, self.btn_d):
            set_variant(_b, _b.property("variant"))
        self.btn_d.clicked.connect(lambda: self.remove_requested.emit(self.file_path))
        btns.addWidget(self.btn_e)
        btns.addWidget(self.btn_r)
        btns.addWidget(self.btn_d)
        l.addLayout(btns)

    def set_pages(self, c):
        self.page_badge.setText(f"{c} PAGINE")

    def update_style(self):
        b, bg = ("2px solid #00e5ff", "#3a3a3a") if self.selected else ("1px solid #444", "#2a2a2a")
        self.setStyleSheet(f"ComicCard {{ background: {bg}; border-radius: 14px; border: {b}; }}")

    # Il click non è gestito qui: passa alla griglia (_DragSelector in main_window),
    # che distingue il click (seleziona questa card) dal trascinamento (riquadro).

    def set_status(self, code):
        self.status_code = code
        txt, bg, fg = _STATUS_MAP.get(code, ("...", "#555", "white"))
        self.status.setText(txt)
        self.status.setStyleSheet(
            f"background: {bg}; color: {fg}; font-weight: bold; padding: 4px; "
            "border-top-left-radius: 13px; border-top-right-radius: 13px;"
        )
        if code == 4:
            self.btn_r.setText("Dupe")
            set_variant(self.btn_r, "muted")
            try:
                self.btn_r.clicked.disconnect()
            except Exception:
                pass
            self.btn_r.clicked.connect(lambda: self.trash_requested.emit(self.file_path))
        else:
            self.btn_r.setText("Fix")
            set_variant(self.btn_r, "primary")
            try:
                self.btn_r.clicked.disconnect()
            except Exception:
                pass
            self.btn_r.clicked.connect(lambda: self.repair_requested.emit(self.file_path))

    def set_pixmap(self, pix):
        self.thumb.setPixmap(pix.scaled(175, 230, Qt.AspectRatioMode.KeepAspectRatioByExpanding))

    def mouseDoubleClickEvent(self, e):
        # doppio click sul nome: rinomina; sul resto della card: editor
        if self.name.geometry().contains(e.position().toPoint()):
            self.rename_requested.emit(self.file_path)
        else:
            self.edit_requested.emit(self.file_path)
