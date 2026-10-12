"""Editor avanzato delle pagine di un fumetto."""

import os
import shutil

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .dialogs import NoWheelSpinBox, fit_dialog_to_screen
from .images import _to_saveable_rgb
from .logsetup import log
from .style import set_variant


class AdvancedEditor(QDialog):
    def __init__(self, file_path, temp_dir, image_list, parent=None):
        super().__init__(parent)
        self.file_path    = file_path
        self.temp_dir     = temp_dir
        self.page_widgets = []
        self._added_paths = set()   # path delle immagini aggiunte in questa sessione
        self.setWindowTitle(f"Editor: {os.path.basename(file_path)}")
        fit_dialog_to_screen(self, 1100, 850, min_w=650, min_h=420)

        v = QVBoxLayout(self)
        self.scroll  = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_c  = QWidget()
        self.grid_l  = QGridLayout(self.grid_c)
        self.scroll.setWidget(self.grid_c)
        v.addWidget(self.scroll)

        btns  = QHBoxLayout()
        b_can = QPushButton("ANNULLA")
        b_can.setMinimumSize(130, 42)
        set_variant(b_can, "danger")
        b_can.clicked.connect(self.reject)
        b_add = QPushButton("AGGIUNGI")
        b_add.setMinimumSize(150, 42)
        set_variant(b_add, "info")
        b_add.clicked.connect(self.add_ext)
        b_sav = QPushButton("SALVA")
        b_sav.setMinimumSize(200, 42)
        set_variant(b_sav, "success")
        b_sav.clicked.connect(self.accept)
        btns.addWidget(b_can)
        btns.addStretch()
        btns.addWidget(b_add)
        btns.addStretch()
        btns.addWidget(b_sav)
        v.addLayout(btns)

        for i, p in enumerate(image_list):
            self.add_page(p, i + 1)
        self.refresh()

    def _dominant_format(self):
        """
        Determina il formato prevalente tra le immagini originali (non aggiunte).
        Restituisce 'webp' o 'jpg'. In caso di parità o dubbio, restituisce 'jpg'.
        """
        webp_count = 0
        jpg_count  = 0
        for w in self.page_widgets:
            if w.path in self._added_paths:
                continue   # ignora le nuove aggiunte per il conteggio
            ext = os.path.splitext(w.path)[1].lower()
            if ext == '.webp':
                webp_count += 1
            elif ext in ('.jpg', '.jpeg'):
                jpg_count += 1
        return 'webp' if webp_count > jpg_count else 'jpg'

    def add_page(self, p, pos, is_new=False):
        w = QFrame()
        w.setFixedSize(160, 310)
        w.setStyleSheet("QFrame { background: #333; border-radius: 10px; }")
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(3)

        btn_del = QPushButton("X")
        btn_del.setFixedSize(22, 22)
        btn_del.setProperty("sz", "tiny")
        set_variant(btn_del, "danger")
        btn_del.clicked.connect(lambda: (self.page_widgets.remove(w), w.deleteLater(), self.refresh()))
        l.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignRight)

        img = QLabel()
        img.setFixedSize(140, 175)
        pix = QPixmap(p)
        img.setPixmap(pix.scaled(140, 175, Qt.AspectRatioMode.KeepAspectRatio))
        l.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)

        # Banda colorata con il nome del file
        ext  = os.path.splitext(p)[1].lower()
        name = os.path.basename(p)
        if ext == '.webp':
            badge_bg, badge_fg = "#1b5e20", "#a5d6a7"   # verde
        elif ext in ('.jpg', '.jpeg'):
            badge_bg, badge_fg = "#f9a825", "#000"       # giallo
        else:
            badge_bg, badge_fg = "#b71c1c", "#fff"       # rosso

        name_lbl = QLabel(name)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setFixedWidth(152)
        name_lbl.setStyleSheet(
            f"background: {badge_bg}; color: {badge_fg}; "
            "font-size: 8px; font-weight: bold; "
            "padding: 2px 3px; border-radius: 3px;"
        )
        l.addWidget(name_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        sp = NoWheelSpinBox()
        sp.setRange(1, 9999)
        sp.setValue(pos)
        sp.editingFinished.connect(lambda: self.reorder(w))
        l.addWidget(sp)

        w.path    = p
        w.spin    = sp
        w.is_new  = is_new   # flag: aggiunta in questa sessione
        self.page_widgets.append(w)

    def add_ext(self):
        """Accetta tutte le estensioni immagine comuni."""
        exts = "Immagini (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif *.avif)"
        fs, _ = QFileDialog.getOpenFileNames(self, "Aggiungi immagini", "", exts)
        for f in fs:
            dst = os.path.join(self.temp_dir, f"ext_{os.path.basename(f)}")
            shutil.copy2(f, dst)
            self._added_paths.add(dst)
            self.add_page(dst, len(self.page_widgets) + 1, is_new=True)
        self.refresh()

    def reorder(self, moved_w):
        target_idx = max(0, min(moved_w.spin.value() - 1, len(self.page_widgets) - 1))
        self.page_widgets.remove(moved_w)
        self.page_widgets.insert(target_idx, moved_w)
        self.refresh()

    def refresh(self):
        for i in reversed(range(self.grid_l.count())):
            w = self.grid_l.itemAt(i).widget()
            if w:
                w.setParent(None)
        for i, w in enumerate(self.page_widgets):
            w.spin.blockSignals(True)
            w.spin.setValue(i + 1)
            w.spin.blockSignals(False)
            self.grid_l.addWidget(w, i // 6, i % 6)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.focusWidget():
                self.focusWidget().clearFocus()
            return
        super().keyPressEvent(e)

    def get_paths(self):
        """
        Restituisce i path finali. Le immagini aggiunte nella sessione
        vengono convertite nel formato prevalente delle immagini originali
        (jpg o webp) prima di essere restituite.
        """
        if not self._added_paths:
            return [w.path for w in self.page_widgets]

        fmt = self._dominant_format()
        result = []
        for w in self.page_widgets:
            p = w.path
            if p in self._added_paths:
                ext_now = os.path.splitext(p)[1].lower()
                target_ext = f".{fmt}"
                if ext_now != target_ext:
                    # Converti nel formato prevalente
                    converted = os.path.join(
                        self.temp_dir,
                        os.path.splitext(os.path.basename(p))[0] + f"_conv{target_ext}"
                    )
                    try:
                        with Image.open(p) as img:
                            img = _to_saveable_rgb(img)
                            if fmt == 'webp':
                                img.save(converted, "WEBP", quality=85)
                            else:
                                img.save(converted, "JPEG", quality=92, optimize=True)
                        log.info(f"Editor: convertita '{os.path.basename(p)}' → "
                                 f"'{os.path.basename(converted)}' (formato prevalente: {fmt})")
                        p = converted
                    except Exception as e:
                        log.error(f"Editor: conversione fallita per '{p}': {e}")
                        # usa il file originale se la conversione fallisce
            result.append(p)
        return result
