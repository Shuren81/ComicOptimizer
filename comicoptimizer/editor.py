"""Editor avanzato delle pagine di un fumetto."""

import math
import os
import shutil

from PIL import Image
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .dialogs import NoWheelSpinBox, fit_dialog_to_screen
from .images import _to_saveable_rgb, webp_quality
from .logsetup import log
from .style import set_variant


class PagePreview(QDialog):
    """Pagina in grande: frecce ← → per scorrere, Esc o click fuori per chiudere."""
    def __init__(self, paths, index, parent=None):
        # Popup: Qt la chiude da sola con un click fuori dalla finestra
        super().__init__(parent, Qt.WindowType.Popup)
        self.paths, self.index = paths, index
        fit_dialog_to_screen(self, 1000, 1400, min_w=300, min_h=300)
        self.move(QApplication.primaryScreen().availableGeometry().center() - self.rect().center())

        v = QVBoxLayout(self)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored: la pagina si adatta alla finestra invece di allargarla
        self.img.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.info = QLabel()
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 13px;")
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        row = QHBoxLayout()
        for b, d, tip in ((self.btn_prev, -1, "Pagina precedente (←)"),
                          (self.btn_next, 1, "Pagina successiva (→)")):
            b.setProperty("sz", "small")
            set_variant(b, "accent")
            b.setToolTip(tip)
            # senza focus: altrimenti il pulsante si prende le frecce della tastiera
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _, d=d: self.step(d))
        row.addWidget(self.btn_prev)
        row.addWidget(self.info, 1)
        row.addWidget(self.btn_next)
        v.addWidget(self.img, 1)
        v.addLayout(row)
        self.show_page()

    def show_page(self):
        p = self.paths[self.index]
        self._pix = QPixmap(p)
        self.info.setText(f"{self.index + 1} / {len(self.paths)}  —  {os.path.basename(p)}")
        self.btn_prev.setEnabled(self.index > 0)
        self.btn_next.setEnabled(self.index < len(self.paths) - 1)
        self._fit()

    def _fit(self):
        if not self._pix.isNull():
            self.img.setPixmap(self._pix.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def step(self, delta):
        self.index = max(0, min(self.index + delta, len(self.paths) - 1))
        self.show_page()

    def keyPressEvent(self, e):
        delta = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(e.key())
        if delta:
            self.step(delta)
        else:
            super().keyPressEvent(e)   # Esc chiude

class LibroAnimato(QWidget):
    """Un fumetto aperto che sfoglia le pagine in loop, mentre le miniature si caricano."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 70)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avanza)
        self._timer.start(30)

    def _avanza(self):
        self._t = (self._t + 0.06) % 2
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, top, w, h = self.width() / 2, 8, 46, 54
        p.setPen(QColor("#00bcd4"))
        p.setBrush(QColor("#263238"))
        p.drawRect(QRectF(cx - w, top, w, h))         # pagina di sinistra
        p.drawRect(QRectF(cx, top, w, h))             # pagina di destra
        # la pagina che gira: da destra a sinistra, larghezza che segue il coseno
        x = w * math.cos(math.pi * min(self._t, 1))
        p.setBrush(QColor("#ffeb3b") if x > 0 else QColor("#fff59d"))
        p.drawRect(QRectF(cx + min(0, x), top, abs(x), h))


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
        self.attesa = QWidget()                       # animazione finché le miniature non sono pronte
        a = QHBoxLayout(self.attesa)
        a.addStretch()
        a.addWidget(LibroAnimato())
        self.attesa_testo = QLabel("Carico le pagine…")
        a.addWidget(self.attesa_testo)
        a.addStretch()
        v.addWidget(self.attesa)
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
        # miniature poche alla volta: con fumetti enormi la finestra resta viva (prima Linux
        # diceva "non risponde" mentre le leggeva tutte insieme)
        self._da_caricare = list(self.page_widgets)
        self._mini = QTimer(self)                     # figlio dell'editor: chiuso l'editor, si ferma
        self._mini.timeout.connect(self._carica_miniature)
        self._mini.start(0)

    def _carica_miniature(self):
        for w in self._da_caricare[:4]:
            reader = QImageReader(w.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():                        # decodifica già rimpicciolita: molto più veloce
                reader.setScaledSize(size.scaled(QSize(140, 175), Qt.AspectRatioMode.KeepAspectRatio))
            w.img.setPixmap(QPixmap.fromImage(reader.read()))
        del self._da_caricare[:4]
        totale = len(self.page_widgets)
        self.attesa_testo.setText(f"Carico le pagine… {totale - len(self._da_caricare)}/{totale}")
        if not self._da_caricare:
            self._mini.stop()
            self.attesa.hide()

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
        w.setObjectName("pagina")
        w.setFixedSize(160, 310)
        w.setStyleSheet("QFrame#pagina { background: #333; border-radius: 10px; }")
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
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if is_new:                                    # le pagine del fumetto arrivano da _carica_miniature
            img.setPixmap(QPixmap(p).scaled(140, 175, Qt.AspectRatioMode.KeepAspectRatio))
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

        w.mouseDoubleClickEvent = lambda e: self.preview(w)
        w.mousePressEvent = lambda e: self.seleziona(w) if e.button() == Qt.MouseButton.LeftButton else None
        w.contextMenuEvent = lambda e: self.menu(w, e.globalPos())

        w.img     = img
        w.scelta  = False
        w.path    = p
        w.spin    = sp
        w.is_new  = is_new   # flag: aggiunta in questa sessione
        self.page_widgets.append(w)

    def seleziona(self, w, scelta=None):
        """Un click seleziona o toglie la pagina (bordo azzurro): le selezionate si esportano."""
        w.scelta = not w.scelta if scelta is None else scelta
        w.setStyleSheet("QFrame#pagina { background: #333; border-radius: 10px; %s }"
                        % ("border: 3px solid #00bcd4;" if w.scelta else ""))

    def menu(self, w, dove):
        if not w.scelta:                              # tasto destro su una pagina non scelta: solo quella
            for x in self.page_widgets:
                self.seleziona(x, x is w)
        scelte = [x.path for x in self.page_widgets if x.scelta]
        m = QMenu(self)
        m.addAction(f"Esporta immagini ({len(scelte)})…", lambda: self.esporta(scelte))
        m.exec(dove)

    def esporta(self, percorsi, cartella=None):
        """Copia le pagine in una cartella scelta, mai sovrascrivendo. Restituisce i file scritti."""
        cartella = cartella or QFileDialog.getExistingDirectory(self, "Esporta immagini in…")
        if not cartella:
            return []
        scritti = []
        for p in percorsi:
            base, ext = os.path.splitext(os.path.basename(p))
            dst, n = os.path.join(cartella, base + ext), 1
            while os.path.exists(dst):
                dst, n = os.path.join(cartella, f"{base} ({n}){ext}"), n + 1
            shutil.copy2(p, dst)
            scritti.append(dst)
        log.info(f"Editor: esportate {len(scritti)} immagini in '{cartella}'")
        return scritti

    def preview(self, w):
        """Doppio click: la pagina in grande, nell'ordine attuale dell'editor."""
        PagePreview([x.path for x in self.page_widgets], self.page_widgets.index(w), self).exec()

    def add_ext(self):
        """Accetta tutte le estensioni immagine comuni."""
        exts = "Immagini (*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tiff *.tif *.avif)"
        fs, _ = QFileDialog.getOpenFileNames(self, "Aggiungi immagini", "", exts)
        for f in fs:
            # numero davanti: due immagini con lo stesso nome (o 01.png e 01.jpg) restano distinte
            dst = os.path.join(self.temp_dir, f"ext_{len(self._added_paths)}_{os.path.basename(f)}")
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
                                img.save(converted, "WEBP", quality=webp_quality())
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
