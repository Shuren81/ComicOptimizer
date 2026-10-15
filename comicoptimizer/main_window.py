"""Finestra principale."""

import logging
import os
import random
import shutil
import subprocess
import sys
import threading

from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PyQt6.QtGui import QCursor, QKeySequence, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRubberBand,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import config
from .archives import detect_real_format, get_archive_file_list
from .card import ComicCard
from .cbz import cbz_status
from .config import APP_VERSION, CARD_MARGIN, CARD_SPACING, CARD_W, COLS_DEFAULT, COLS_MAX, IS_MAC, IS_WIN
from .dialogs import LogWindow, MergeDialog, RenameDialog, StopDialog
from .editor import AdvancedEditor
from .logsetup import LOG_PATH, _qt_log_handler, log
from .pdf import HAS_PDF
from .style import _VisibilityWatcher, set_variant
from .utils import (
    _trash_file_cross_platform,
    find_comicinfo,
    find_tool,
    fmt_duration,
    fmt_size,
    folder_has_loose_and_subs,
    get_natural_sort_key,
)
from .workers import (
    AnalysisWorker,
    BatchPrepWorker,
    ImportWorker,
    LoadingWorker,
    ProcessingWorker,
    ThumbWorker,
)

# --- SELEZIONE CON IL MOUSE ---

class _DragSelector(QObject):
    """
    Filtro sulla griglia delle card. Click su una card: la seleziona o deseleziona
    (Shift: intervallo). Trascinamento: riquadro che aggiunge alla selezione le card
    toccate (con Ctrl le toglie); vicino al bordo la griglia scorre da sola.
    """
    EDGE = 30   # px dal bordo della griglia visibile in cui parte lo scorrimento

    def __init__(self, win):
        super().__init__(win)
        self.win    = win
        self.band   = QRubberBand(QRubberBand.Shape.Rectangle, win.grid_w)
        self.origin = None
        self.drag   = False
        self.timer  = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._autoscroll)
        win.grid_w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self.origin = ev.position().toPoint()
            self.drag   = False
            self.mods   = ev.modifiers()
            return True
        if t == QEvent.Type.MouseMove and self.origin is not None:
            pos = ev.position().toPoint()
            if not self.drag and (pos - self.origin).manhattanLength() >= QApplication.startDragDistance():
                self.drag    = True
                self.initial = {c: c.selected for c in self.win.cards.values()}
                self.band.show()
                self.timer.start()
            if self.drag:
                self._update(pos)
            return True
        if t == QEvent.Type.MouseButtonRelease and self.origin is not None:
            if self.drag:
                self.band.hide()
                self.timer.stop()
            else:
                card = self._card_at(self.origin)
                if card:
                    card.selected = not card.selected
                    card.update_style()
                    self.win.handle_selection(card, self.mods)
            self.origin = None
            return True
        return False

    def _card_at(self, pos):
        w = self.win.grid_w.childAt(pos)
        while w is not None and not isinstance(w, ComicCard):
            w = w.parentWidget()
        return w

    def _update(self, pos):
        rect = QRect(self.origin, pos).normalized()
        self.band.setGeometry(rect)
        remove = bool(self.mods & Qt.KeyboardModifier.ControlModifier)
        for c, was in self.initial.items():
            hit = c.parent() is self.win.grid_w and c.geometry().intersects(rect)
            sel = (was and not hit) if remove else (was or hit)
            if sel != c.selected:
                c.selected = sel
                c.update_style()
        self.win._update_sel_buttons()

    def _autoscroll(self):
        vp  = self.win.scroll.viewport()
        y   = vp.mapFromGlobal(QCursor.pos()).y()
        bar = self.win.scroll.verticalScrollBar()
        if y < self.EDGE:
            bar.setValue(bar.value() - max(4, (self.EDGE - y) // 2))
        elif y > vp.height() - self.EDGE:
            bar.setValue(bar.value() + max(4, (y - vp.height() + self.EDGE) // 2))
        else:
            return
        self._update(self.win.grid_w.mapFromGlobal(QCursor.pos()))

# --- LISTA VUOTA ---

_HINT_CARDS = "Clicca sulle card o trascina il mouse per selezionarle"
_HINT_CARDS_TIP = ("Shift+click: seleziona un intervallo\n"
                   "Ctrl+trascina: toglie dalla selezione\n"
                   "Ctrl+A: seleziona tutto · Esc: deseleziona")
_EMPTY_HINTS = [
    "Nessun fumetto all'orizzonte: trascinali nella finestra e cominciamo.",
    "Griglia vuota, processore annoiato. Dammi qualche fumetto.",
    "Lancia qui i tuoi fumetti (con delicatezza): al resto penso io.",
    "Qui c'è un silenzio da biblioteca. Trascina dentro un po' di fumetti.",
    "Pronto quando vuoi: trascina file o cartelle in un punto qualsiasi.",
]

class _EmptyArea(QWidget):
    """Lista vuota: disegno al neon adattato allo spazio, con la scritta sopra."""
    def __init__(self, text, art_path):
        super().__init__()
        self.art = QPixmap(art_path)   # se manca resta solo la scritta
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        QVBoxLayout(self).addWidget(self.label)

    def paintEvent(self, e):
        if self.art.isNull():
            return
        art = self.art.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        QPainter(self).drawPixmap((self.width() - art.width()) // 2,
                                  (self.height() - art.height()) // 2, art)

# --- MAIN WINDOW ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ComicOptimizer v{APP_VERSION}")
        self.setAcceptDrops(True)
        self.cards           = {}
        self.last_clicked    = None
        self._threads_lock   = threading.Lock()
        self._active_threads = set()
        self.current_worker  = None
        self.skip_trash_confirm = False
        self.keep_log        = False   # default: cancella il log alla chiusura
        self._closing        = False
        self._tray           = None    # icona di sistema, creata alla prima notifica
        self._loose_last     = set()   # cartelle con le immagini sciolte dopo le sottocartelle
        self._log_window = LogWindow(self)
        self.init_ui()
        self.check_deps()

        # Dimensione iniziale (4 card di larghezza, meno se lo schermo è stretto)
        # e schermata vuota: niente pulsanti, frase d'invito
        self._was_empty = None
        self.refresh_grid()

        frasi = [
            "Il mio processore scalpita...",
            "Pronto a triturare PDF e immagini.",
            "Caffè caricato, iniziamo?",
            "I tuoi fumetti sono in buone mani.",
            "Ottimizzazione? È il mio secondo nome.",
            "Nessun supereroe è stato maltrattato durante la conversione.",
            "Più leggeri di un balloon, promesso.",
            "Pagine in fila per due, col resto di WebP.",
            "Prometto di non leggere gli spoiler.",
            "Riordino fumetti meglio di quanto tu riordini la camera.",
            "Il disordine ha i minuti contati.",
            "CBR, CBZ, PDF... per me pari sono.",
            "Ho visto librerie peggiori. Poche, ma le ho viste.",
            "Pronto a fare spazio sul disco (e nel cuore).",
            "Anche Batman aveva bisogno di un Alfred. Eccomi.",
            "Le pagine perse non sono mai state un'opzione.",
            "Rinomino, unisco, comprimo. Tu rilassati.",
        ]
        self.ironic_lbl.setText(random.choice(frasi))
        log.info(f"ComicOptimizer v{APP_VERSION} avviato.")

    # --- Helpers thread-safe per active_threads ---
    @property
    def active_threads(self):
        return self._active_threads

    def _add_thread(self, t):
        with self._threads_lock:
            self._active_threads.add(t)

    def _discard_thread(self, t):
        with self._threads_lock:
            self._active_threads.discard(t)

    # FIX #14: closeEvent per terminare i thread prima di chiudere
    def closeEvent(self, event):
        self._closing = True
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.abort_now()
            # lascia al worker il tempo di cancellare le cartelle temporanee
            self.current_worker.wait(15000)
        if self._tray:
            self._tray.hide()
        with self._threads_lock:
            threads = list(self._active_threads)
        for t in threads:
            t.quit()
            t.wait(2000)

        # Gestione file di log alla chiusura
        _log_path = LOG_PATH
        log.info("ComicOptimizer chiuso.")

        # Rimuovi l'handler Qt dal logger PRIMA che Qt distrugga l'oggetto C++.
        # Senza questo, logging.shutdown() (chiamato da atexit) prova ad accedere
        # all'handler dopo la distruzione e genera RuntimeError.
        try:
            log.removeHandler(_qt_log_handler)
            logging.getLogger().removeHandler(_qt_log_handler)
        except Exception:
            pass

        # Cancella il file di log se l'utente non vuole mantenerlo
        if not self.chk_keep_log.isChecked():
            try:
                # Chiudi prima il FileHandler per rilasciare il file
                for h in logging.getLogger().handlers[:] + log.handlers[:]:
                    if isinstance(h, logging.FileHandler):
                        h.close()
                        logging.getLogger().removeHandler(h)
                        log.removeHandler(h)
                if os.path.exists(_log_path):
                    os.remove(_log_path)
            except Exception:
                pass

        event.accept()

    def keyPressEvent(self, e):
        """L: finestra di log · F2: rinomina · Ctrl+A: seleziona tutto · Esc: deseleziona."""
        if e.key() == Qt.Key.Key_L and not e.modifiers():
            self._toggle_log()
        elif e.key() == Qt.Key.Key_F2:
            self.rename_selected()
        elif e.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all(True)
        elif e.key() == Qt.Key.Key_Escape:
            self.select_all(False)
        else:
            super().keyPressEvent(e)

    def _toggle_log(self):
        if self._log_window.isVisible():
            self._log_window.hide()
        else:
            self._log_window.show()
            self._log_window.raise_()

    # --- Larghezza adattiva ---

    def _win_width_for_cols(self, cols):
        """Calcola la larghezza della finestra per esattamente `cols` colonne di card."""
        return (cols * CARD_W
                + (cols + 1) * CARD_SPACING
                + 2 * CARD_MARGIN
                + 2)   # bordi finestra

    # ~ def _cols_for_count(self, n):
        # ~ """
        # ~ Restituisce il numero di colonne ottimale per `n` card.
        # ~ - Minimo COLS_DEFAULT (4) se ci sono almeno 4 card
        # ~ - Massimo COLS_MAX (7), indipendentemente dalla risoluzione
        # ~ """
        # ~ if n <= 0:
            # ~ return COLS_DEFAULT
        # ~ cols = min(n, COLS_MAX)
        # ~ cols = max(cols, min(n, COLS_DEFAULT))
        # ~ return cols
    def _cols_for_count(self, n):
        """
        Restituisce il numero di colonne ottimale per `n` card.
        - Minimo: COLS_DEFAULT (4)
        - Massimo: COLS_MAX (7)
        - Mai più di quelle che entrano nello schermo (anche sotto il minimo)
        """
        # Se n è piccolo (0,1,2,3), restituisce 4.
        # Se n è tra 4 e 7, restituisce n.
        # Se n è superiore a 7, restituisce 7.
        return min(max(COLS_DEFAULT, min(n, COLS_MAX)), self._cols_fit_screen())

    def _cols_fit_screen(self):
        """Quante colonne di card entrano nella larghezza dello schermo (almeno 1)."""
        avail = QApplication.primaryScreen().availableGeometry().width()
        cols = COLS_MAX
        # + 12: la barra di scorrimento verticale della griglia (vedi STYLESHEET)
        while cols > 1 and self._win_width_for_cols(cols) + 12 > avail:
            cols -= 1
        return cols

    def _refit_width(self):
        """Riadatta la larghezza quando compaiono/spariscono i pulsanti della barra."""
        n = len(self.cards)
        self._apply_window_width(self._cols_for_count(n))

    def _apply_window_width(self, cols):
        """Ridimensiona la finestra alla larghezza giusta per `cols` colonne."""
        screen = QApplication.primaryScreen().availableGeometry()
        # La larghezza deve bastare anche per le barre dei pulsanti sopra e sotto
        # alla griglia (altrimenti su schermi stretti alcuni pulsanti finiscono
        # fuori dalla finestra, senza modo di raggiungerli).
        min_bars_w = max(self.top_bar_w.minimumSizeHint().width(),
                         self.footer_w.minimumSizeHint().width())
        w = min(max(self._win_width_for_cols(cols), min_bars_w + 30), screen.width())
        h = self.height() if self.isVisible() else min(800, screen.height())
        self.setFixedWidth(w)
        if not self._banner.isNull():
            m = self.centralWidget().layout().contentsMargins()
            self.title_lbl.setPixmap(self._banner.scaledToWidth(
                w - m.left() - m.right(), Qt.TransformationMode.SmoothTransformation))
        self.setMinimumHeight(min(600, screen.height()))
        self.setMaximumHeight(screen.height())
        if not self.isVisible():
            self.resize(w, min(h, screen.height()))

    def check_deps(self):
        m = []
        if IS_WIN or IS_MAC:
            # su Windows e Mac basta 7-Zip (incluso nell'app): legge anche i RAR/RAR5
            if not find_tool('7z'):
                m.append("7-Zip")
            if not HAS_PDF:
                m.append("PyMuPDF")
            if m:
                QMessageBox.warning(
                    self, "Dipendenze mancanti",
                    "Mancano: " + ", ".join(m) +
                    "\n\nInstalla 7-Zip da https://www.7-zip.org"
                    + (" (oppure: brew install sevenzip)" if IS_MAC else "")
                    + ("\ne PyMuPDF con: pip install pymupdf" if not HAS_PDF else "")
                )
            return
        if not find_tool('7z'):
            m.append("p7zip-full")
        if not find_tool('unrar'):
            m.append("unrar")
        if not HAS_PDF:
            m.append("python3-pymupdf")
        if m:
            QMessageBox.warning(
                self, "Dipendenze mancanti",
                "Mancano: " + ", ".join(m) +
                "\n\nsudo apt install p7zip-full unrar\npip install pymupdf send2trash"
            )

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.title_lbl = QLabel()
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner = QPixmap(os.path.join(config.RES_DIR, "comicoptimizer_banner.png"))
        if self._banner.isNull():
            # banner mancante: la vecchia scritta
            self.title_lbl.setText("ComicOptimizer, by Shuren")
            self.title_lbl.setStyleSheet(
                "font-size: 34px; font-weight: 900; color: #00e5ff; "
                "padding: 10px; background: #1a1a1a; border-bottom: 2px solid #00d4ff; "
                "border-top-left-radius: 14px; border-top-right-radius: 14px;"
            )
        layout.addWidget(self.title_lbl)

        top_bar = QHBoxLayout()
        self.btn_clear = QPushButton("PULISCI LISTA")
        self.btn_clear.setMinimumHeight(42)
        self.btn_clear.clicked.connect(self.clear_all)

        self.btn_all = QPushButton("SISTEMA TUTTO")
        self.btn_all.setMinimumHeight(42)
        set_variant(self.btn_all, "primary")
        self.btn_all.clicked.connect(self.repair_all_trigger)

        self.btn_sel_all = QPushButton("SELEZIONA TUTTO")
        self.btn_sel_all.setMinimumHeight(42)
        self.btn_sel_all.setToolTip("Ctrl+A seleziona tutto, Esc toglie la selezione")
        self.btn_sel_all.setVisible(False)
        self.btn_sel_all.clicked.connect(
            lambda: self.select_all(not all(c.selected for c in self.cards.values())))

        self.btn_sel = QPushButton("SISTEMA SELEZIONATI")
        self.btn_sel.setMinimumHeight(42)
        set_variant(self.btn_sel, "info")
        self.btn_sel.setVisible(False)
        self.btn_sel.clicked.connect(self.repair_selected)

        self.btn_trash_sel = QPushButton("CESTINA SELEZIONATI")
        self.btn_trash_sel.setMinimumHeight(42)
        set_variant(self.btn_trash_sel, "danger")
        self.btn_trash_sel.setVisible(False)
        self.btn_trash_sel.clicked.connect(self.trash_selected)

        self.btn_merge = QPushButton("UNISCI SELEZIONATI")
        self.btn_merge.setMinimumHeight(42)
        set_variant(self.btn_merge, "accent")
        self.btn_merge.setVisible(False)
        self.btn_merge.clicked.connect(self.merge_selected)

        self.btn_rename = QPushButton("RINOMINA SELEZIONATI")
        self.btn_rename.setMinimumHeight(42)
        self.btn_rename.setToolTip("Rinomina i fumetti selezionati (F2)")
        self.btn_rename.setVisible(False)
        self.btn_rename.clicked.connect(self.rename_selected)

        self.btn_trash_dupes = QPushButton("PULISCI DUPLICATI")
        self.btn_trash_dupes.setMinimumHeight(42)
        set_variant(self.btn_trash_dupes, "muted")
        self.btn_trash_dupes.setVisible(False)
        self.btn_trash_dupes.clicked.connect(self.trash_all_duplicates)

        top_bar.setSpacing(8)
        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.btn_all)
        top_bar.addWidget(self.btn_sel_all)
        top_bar.addWidget(self.btn_sel)
        top_bar.addWidget(self.btn_merge)
        top_bar.addWidget(self.btn_rename)
        top_bar.addWidget(self.btn_trash_sel)
        top_bar.addWidget(self.btn_trash_dupes)
        top_bar.addStretch()

        self.status_stack = QStackedWidget()
        self.status_stack.setFixedHeight(50)
        self.status_stack.setMinimumWidth(230)
        idle_w = QWidget()
        idle_l = QVBoxLayout(idle_w)
        idle_l.setContentsMargins(0, 0, 0, 0)
        idle_l.setSpacing(2)
        self.hint_lbl = QLabel(_HINT_CARDS)
        self.hint_lbl.setToolTip(_HINT_CARDS_TIP)
        self.hint_lbl.setStyleSheet("color: #00e5ff; font-size: 11px; font-weight: bold")
        self.hint_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.ironic_lbl = QLabel("Pronto ad operare.")
        self.ironic_lbl.setStyleSheet("color: #aaa; font-style: italic")
        self.ironic_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        idle_l.addWidget(self.hint_lbl)
        idle_l.addWidget(self.ironic_lbl)
        self.status_stack.addWidget(idle_w)

        work_w = QWidget()
        work_l = QHBoxLayout(work_w)
        work_l.setContentsMargins(0, 0, 0, 0)
        work_l.setSpacing(10)
        vl = QVBoxLayout()
        vl.setSpacing(2)
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(18)
        self.status_msg = QLabel("Lavorando...")
        self.status_msg.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 12px")
        vl.addWidget(self.status_msg)
        vl.addWidget(self.pbar)
        work_l.addLayout(vl, 1)
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setMinimumHeight(40)
        set_variant(self.btn_stop, "danger")
        self.btn_stop.clicked.connect(self.request_stop)
        work_l.addWidget(self.btn_stop)
        self.status_stack.addWidget(work_w)

        self._vis_watcher = _VisibilityWatcher(self._refit_width, self)
        for _b in (self.btn_sel_all, self.btn_sel, self.btn_merge, self.btn_rename,
                   self.btn_trash_sel, self.btn_trash_dupes):
            _b.installEventFilter(self._vis_watcher)
        self.top_bar_w = QWidget()
        self.top_bar_w.setLayout(top_bar)
        self.top_bar_scroll = QScrollArea()
        self.top_bar_scroll.setWidgetResizable(True)
        self.top_bar_scroll.setFixedHeight(74)
        self.top_bar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.top_bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.top_bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.top_bar_scroll.setWidget(self.top_bar_w)
        layout.addWidget(self.top_bar_scroll)
        # riga tutta sua sotto i pulsanti: aiuto e frase (a riposo), avanzamento e STOP (al lavoro)
        layout.addWidget(self.status_stack)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_w = QWidget()
        self.grid_l = QGridLayout(self.grid_w)
        self.grid_l.setSpacing(15)
        self.grid_l.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_w)

        # Griglia vuota: al posto delle card la scritta "trascina qui" (niente riquadri)
        self.empty_lbl = _EmptyArea(
            "<div style='font-size: 26px; font-weight: 800;'>TRASCINA QUI I FILE</div>"
            "<div style='font-size: 14px; margin-top: 8px;'>"
            "CBZ · CBR · ZIP · RAR · PDF · cartelle di immagini</div>",
            os.path.join(config.RES_DIR, "comicoptimizer_drop.png"))
        self.grid_stack = QStackedWidget()
        self.grid_stack.setObjectName("grid_stack")
        self.grid_stack.addWidget(self.empty_lbl)
        self.grid_stack.addWidget(self.scroll)
        self.set_drop_style(False)
        layout.addWidget(self.grid_stack)
        self._drag_selector = _DragSelector(self)

        footer = QHBoxLayout()
        self.n_btn = QPushButton(f"Novità v{APP_VERSION}")
        set_variant(self.n_btn, "link")
        self.n_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.n_btn.clicked.connect(self.show_news)
        self.c_btn = QPushButton("Credits")
        set_variant(self.c_btn, "link")
        self.c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.c_btn.clicked.connect(self.show_credits)
        self.p_btn = QPushButton("Privacy")
        set_variant(self.p_btn, "link")
        self.p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.p_btn.clicked.connect(self.show_privacy)
        self.log_btn = QPushButton("📋 Log  [L]")
        set_variant(self.log_btn, "linklog")
        self.log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_btn.clicked.connect(self._toggle_log)

        self.chk_keep_log = QCheckBox("Mantieni log")
        self.chk_keep_log.setChecked(False)
        self.chk_keep_log.setToolTip(
            f"Se spuntato, il file di log viene conservato alla chiusura:\n{LOG_PATH}\n"
            "Se non spuntato, viene eliminato automaticamente."
        )

        footer.addWidget(self.n_btn)
        footer.addStretch()
        footer.addWidget(self.c_btn)
        footer.addStretch()
        footer.addWidget(self.p_btn)
        footer.addStretch()
        self.chk_notify = QCheckBox("🔔 Avvisi")
        self.chk_notify.setChecked(True)
        self.chk_notify.setToolTip(
            "A fine lavoro mostra una notifica di sistema e riproduce un suono.\n"
            "Il riepilogo a fine lavoro viene mostrato comunque."
        )

        footer.addWidget(self.log_btn)
        footer.addSpacing(8)
        footer.addWidget(self.chk_notify)
        footer.addSpacing(8)
        footer.addWidget(self.chk_keep_log)
        self.footer_w = QWidget()
        self.footer_w.setLayout(footer)
        footer_scroll = QScrollArea()
        footer_scroll.setWidgetResizable(True)
        footer_scroll.setFixedHeight(46)
        footer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        footer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        footer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        footer_scroll.setWidget(self.footer_w)
        layout.addWidget(footer_scroll)

    def set_working(self, working, msg="In corso...", val=0, total=0):
        self.status_stack.setCurrentIndex(1 if working else 0)
        self.status_msg.setText(msg)
        if total > 0:
            self.pbar.setRange(0, total)
            self.pbar.setValue(val)
        else:
            self.pbar.setRange(0, 0)
        self.btn_all.setEnabled(not working)
        self.btn_clear.setEnabled(not working)

    def _on_prep_pages(self, name, v, t, n_files):
        """Avanzamento pagina per pagina durante l'estrazione di un PDF."""
        if n_files == 1:
            self.set_working(True, f"Estrazione: {name} ({v}/{t} pagine)", v, t)
        else:
            self.status_msg.setText(f"Estrazione: {name} ({v}/{t} pagine)")

    def handle_conflict(self, old_p, final_p, p_new, p_old):
        msg = QMessageBox(self)
        msg.setWindowTitle("Conflitto Rilevato")
        msg.setText(
            f"Il file <b>{os.path.basename(final_p)}</b> esiste già.<br><br>"
            f"Disco: {p_old} pag. | Nuovo: {p_new} pag."
        )
        b_o = msg.addButton("Sovrascrivi", QMessageBox.ButtonRole.AcceptRole)
        b_r = msg.addButton("Rinomina",    QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Salta",             QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        res = "skip"
        if msg.clickedButton() == b_o:
            res = "overwrite"
        elif msg.clickedButton() == b_r:
            res = "rename"
        if self.current_worker:
            self.current_worker.set_permission(res)

    def confirm_and_trash(self, path):
        if self.skip_trash_confirm:
            self.trash_file(path)
            return
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Rilevato Duplicato")
        msg.setText(f"Vuoi spostare questo duplicato nel cestino?\n\nFile: {os.path.basename(path)}")
        cb    = QCheckBox("Non mostrare più questo avviso")
        msg.setCheckBox(cb)
        b_yes = msg.addButton("Sposta nel Cestino", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == b_yes:
            if cb.isChecked():
                self.skip_trash_confirm = True
            self.trash_file(path)

    def run_analysis(self, auto=True):
        if not self.cards:
            self.btn_trash_dupes.setVisible(False)
            return
        self.set_working(True, "Analisi...")
        aw = AnalysisWorker(list(self.cards.keys()))
        aw.progress.connect(lambda v, t: self.set_working(True, f"Analisi: {v}/{t}", v, t))

        def done(res, d):
            self._discard_thread(aw)
            self.set_working(False)
            damaged = sum(1 for s in res.values() if s == 5)
            to_fix  = sum(1 for s in res.values() if s == 0)
            log.info(f"Analisi completata: {len(res)} file analizzati — "
                     f"{d} duplicati, {damaged} danneggiati, {to_fix} da sistemare.")
            for p, s in res.items():
                status_names = {0:"DA SISTEMARE", 4:"DUPLICATO", 5:"DANNEGGIATO"}
                if s in status_names:
                    log.debug(f"  [{status_names[s]}] {os.path.basename(p)}")
                if p in self.cards:
                    self.cards[p].set_status(s)
            self.btn_trash_dupes.setVisible(d > 0)
            if not auto and d == 0 and not any(s == 5 for s in res.values()):
                QMessageBox.information(self, "Analisi", "Tutto in ordine!")
            self.refresh_grid()

        aw.finished.connect(done)
        aw.start()
        self._add_thread(aw)

    def start_processing(self, tasks, to_webp=False):
        self.set_working(True, "Ottimizzazione...")
        self.current_worker = ProcessingWorker(tasks, to_webp=to_webp)
        self.current_worker.status_msg.connect(self.status_msg.setText)
        self.current_worker.progress_max.connect(self.pbar.setMaximum)
        self.current_worker.progress_val.connect(self.pbar.setValue)
        self.current_worker.ask_permission.connect(self.handle_conflict)
        self.current_worker.file_finished.connect(self.on_file_done)
        self.current_worker.job_done.connect(self._on_job_done)
        self._add_thread(self.current_worker)
        self.current_worker.start()

    # --- Fine lavoro: riepilogo, notifica di sistema e suono ---

    def _on_job_done(self, s):
        worker = self.sender()
        if worker:
            self._discard_thread(worker)
        if worker is self.current_worker:
            self.current_worker = None
        if self._closing:
            return
        self.reset_ui()
        self.run_analysis(True)

        n_err = len(s['errors'])
        if s['aborted']:
            icon, title = QMessageBox.Icon.Warning, "Lavoro interrotto"
        elif n_err:
            icon, title = QMessageBox.Icon.Warning, "Lavoro completato con errori"
        else:
            icon, title = QMessageBox.Icon.Information, "Lavoro completato"

        verb = "convertiti in WebP" if s['mode'] == 'webp' else "riparati"
        short = f"{s['done']} di {s['total']} fumetti {verb}"
        if n_err:
            short += f", {n_err} con errori"

        lines = [f"<b>{title}</b><br>",
                 f"Fumetti {verb}: <b>{s['done']}</b> su {s['total']}"]
        if s['skipped']:
            lines.append(f"Saltati: {s['skipped']}")
        if s['size_before']:
            diff = s['size_before'] - s['size_after']
            perc = diff * 100 / s['size_before']
            if diff >= 0:
                lines.append(f"Spazio: {fmt_size(s['size_before'])} → {fmt_size(s['size_after'])} "
                             f"(<b>risparmiati {fmt_size(diff)}</b>, −{perc:.0f}%)")
                short += f" — risparmiati {fmt_size(diff)}"
            else:
                lines.append(f"Spazio: {fmt_size(s['size_before'])} → {fmt_size(s['size_after'])}")
        if s['pages_kept']:
            lines.append(f"Pagine lasciate nel formato originale: {s['pages_kept']} "
                         f"(dettagli nel log)")
        lines.append(f"Tempo: {fmt_duration(s['elapsed'])}")
        if n_err:
            lines.append("<br><b>Errori</b> (gli originali non sono stati toccati):")
            for name, err in s['errors'][:8]:
                lines.append(f"• {name}: {err}".replace("<", "&lt;"))
            if n_err > 8:
                lines.append(f"… e altri {n_err - 8} (vedi log)")

        if self.chk_notify.isChecked():
            self._notify_system(title, short, ok=not (n_err or s['aborted']))

        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText("<br>".join(lines))
        box.exec()

        # tutti i fumetti nella condizione migliore (sistemati e in WebP): lista pulita
        if self.cards and all(c.status_code == 3 for c in self.cards.values()):
            log.info("Tutti i fumetti sono convertiti: lista pulita.")
            self.clear_all()

    def _notify_system(self, title, body, ok=True):
        """Notifica del sistema operativo + suono (non blocca l'interfaccia)."""
        shown = False
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if sys.platform.startswith("linux") and shutil.which("notify-send"):
                icon = config.APP_ICON_PATH if config.APP_ICON_PATH else "dialog-information"
                subprocess.Popen(["notify-send", "-a", "ComicOptimizer", "-i", icon,
                                  f"ComicOptimizer — {title}", body], **quiet)
                shown = True
        except Exception as e:
            log.debug(f"notify-send non riuscito: {e}")
        if not shown and QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray is None:
                ic = self.windowIcon()
                if ic.isNull():
                    ic = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
                self._tray = QSystemTrayIcon(ic, self)
                self._tray.setToolTip("ComicOptimizer")
                self._tray.activated.connect(lambda *_: (self.showNormal(), self.raise_(),
                                                         self.activateWindow()))
                self._tray.messageClicked.connect(lambda: (self.showNormal(), self.raise_(),
                                                           self.activateWindow()))
            self._tray.show()
            mi = (QSystemTrayIcon.MessageIcon.Information if ok
                  else QSystemTrayIcon.MessageIcon.Warning)
            self._tray.showMessage(f"ComicOptimizer — {title}", body, mi, 8000)
            shown = True
        self._play_sound(ok, notification_shown=shown)
        QApplication.alert(self, 0)   # evidenzia l'app nella barra delle applicazioni

    def _play_sound(self, ok=True, notification_shown=False):
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if sys.platform == "win32":
                # la notifica di Windows ha già il suo suono
                if not notification_shown:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK if ok else winsound.MB_ICONHAND)
                return
            if sys.platform == "darwin":
                snd = "/System/Library/Sounds/" + ("Glass.aiff" if ok else "Basso.aiff")
                subprocess.Popen(["afplay", snd], **quiet)
                return
            if shutil.which("canberra-gtk-play"):
                subprocess.Popen(["canberra-gtk-play", "-i",
                                  "complete" if ok else "dialog-warning"], **quiet)
                return
            for f in ("/usr/share/sounds/freedesktop/stereo/complete.oga",
                      "/usr/share/sounds/freedesktop/stereo/bell.oga"):
                if os.path.exists(f):
                    for player in ("paplay", "pw-play"):
                        if shutil.which(player):
                            subprocess.Popen([player, f], **quiet)
                            return
        except Exception as e:
            log.debug(f"Suono di fine lavoro non riprodotto: {e}")
        QApplication.beep()

    def reset_ui(self):
        for p in list(self.cards.keys()):
            self.cards[p].selected = False
            self.cards[p].update_style()
        self._update_sel_buttons()
        has_dupes = any(c.status_code == 4 for c in self.cards.values())
        self.btn_trash_dupes.setVisible(has_dupes)
        self.last_clicked = None
        self.set_working(False)

    def show_news(self):
        msg = (f"<b>⚡ ComicOptimizer {APP_VERSION}: più sicuro e più veloce</b><br><br>"
               "&nbsp;&nbsp;🛡️ <b>Originali al sicuro:</b> il nuovo CBZ viene verificato prima di toccare "
               "l'originale, che finisce nel cestino invece di essere cancellato.<br>"
               "&nbsp;&nbsp;📄 <b>Nessuna pagina persa:</b> le pagine leggere (bianche, crediti) non vengono più scartate.<br>"
               "&nbsp;&nbsp;🏷️ <b>Metadati conservati:</b> ComicInfo.xml resta nell'archivio.<br>"
               "&nbsp;&nbsp;🚀 <b>WebP su più core:</b> conversione molto più veloce, senza ricomprimere pagine già WebP.<br>"
               "&nbsp;&nbsp;📚 <b>PDF migliori:</b> le scansioni vengono estratte in qualità originale.<br>"
               "&nbsp;&nbsp;🔍 <b>Duplicati per contenuto:</b> trovati anche con nomi diversi.<br>"
               "&nbsp;&nbsp;🔔 <b>Fine lavoro:</b> riepilogo con spazio risparmiato, notifica e suono.<br><br>"
               "Mettiti comodo, al disordine ci pensiamo noi.")
        QMessageBox.information(self, f"Novità v{APP_VERSION}", msg)

    def show_credits(self):
        msg = ("<b>Creatore, Designer e Beta Tester (mio malgrado):</b> Michele Shuren Bancheri<br><br>"
               "Ho sviluppato ComicOptimizer perché la mia collezione di fumetti era un disastro e la mia pazienza era finita.<br><br>"
               "<b>Ringraziamenti Speciali:</b><br>&nbsp;&nbsp;• <b>A mia moglie Keyla Damaer</b>.<br>"
               "&nbsp;&nbsp;• <b>A me stesso:</b> Per non aver mollato al decimo errore di PyQt6.<br>"
               "&nbsp;&nbsp;• <b>A Gemini 3 Flash Preview:</b> Per aver risposto alle mie domande esistenziali sul codice alle tre di notte.<br>"
               "&nbsp;&nbsp;• <b>Al mio PC:</b> Per non essere esploso mentre compilavo e testavo centinaia di versioni.<br>"
               "&nbsp;&nbsp;• <b>A Claude:</b> Per aver scritto, riscritto e poi gentilmente cancellato più codice di quanto ne sia rimasto, "
               "senza mai lamentarsi (almeno a voce alta). Se ComicOptimizer funziona, il merito è anche suo; se ha un bug, "
               "è sicuramente colpa di un fumetto scritto in modo strano.")
        QMessageBox.information(self, "Credits", msg)

    def show_privacy(self):
        msg = ("<b>Informativa sulla Privacy (100% Locale)</b><br><br><b>Sicurezza Integrale: I tuoi file non lasciano mai il PC.</b><br><br>"
               "La riservatezza dei tuoi dati e della tua collezione è la nostra priorità assoluta. ComicOptimizer è progettato secondo il principio della privacy-by-design.<br><br>"
               "La tua libreria rimane sotto il tuo controllo.")
        QMessageBox.information(self, "Privacy", msg)

    def handle_selection(self, card, mod):
        cards = [
            self.grid_l.itemAt(i).widget()
            for i in range(self.grid_l.count())
            if self.grid_l.itemAt(i).widget()
        ]
        if mod & Qt.KeyboardModifier.ShiftModifier and self.last_clicked:
            idx1 = cards.index(self.last_clicked)
            idx2 = cards.index(card)
            for i in range(min(idx1, idx2), max(idx1, idx2) + 1):
                cards[i].selected = True
                cards[i].update_style()
        self.last_clicked = card
        self._update_sel_buttons()

    def _update_sel_buttons(self):
        """Mostra i pulsanti che dipendono da quanti fumetti sono selezionati."""
        sel_n = sum(1 for c in self.cards.values() if c.selected)
        self.btn_sel.setVisible(sel_n > 0)
        self.btn_merge.setVisible(sel_n > 1)
        self.btn_rename.setVisible(sel_n > 0)
        self.btn_trash_sel.setVisible(sel_n > 0)
        self.btn_sel_all.setVisible(bool(self.cards))
        self.btn_sel_all.setText("DESELEZIONA TUTTO" if self.cards and sel_n == len(self.cards)
                                 else "SELEZIONA TUTTO")

    def select_all(self, on=True):
        for c in self.cards.values():
            c.selected = on
            c.update_style()
        self.last_clicked = None
        self._update_sel_buttons()

    def on_file_done(self, o, n, s):
        status_names = {0:"DA SISTEMARE", 1:"OK", 2:"RIPARATO", 3:"CONVERTITO", 4:"SALTATO", 5:"DANNEGGIATO"}
        label = status_names.get(s, str(s))
        if o == n:
            log.info(f"File saltato: '{os.path.basename(o)}' → {label}")
        else:
            log.info(f"File completato: '{os.path.basename(o)}' → '{os.path.basename(n)}' [{label}]")
        if o in self.cards:
            if n != o and n in self.cards:
                self.rem(n)   # card già presente per il file finale (unione o "Sovrascrivi")
            c = self.cards.pop(o)
            c.file_path = n
            c.name.setText(os.path.basename(n))
            c.set_status(s)
            flist = get_archive_file_list(n)
            c.set_pages(len(flist))
            self.cards[n] = c
            self.load_t(n)

    def import_files(self, paths):
        self.set_working(False)
        added = 0
        for p, count in paths:
            if p not in self.cards:
                if os.path.isdir(p) and folder_has_loose_and_subs(p):
                    self._ask_loose_order(p)
                c = ComicCard(p)
                c.set_pages(count)
                c.edit_requested.connect(self.open_editor)
                c.repair_requested.connect(self.individual_repair)
                c.remove_requested.connect(self.rem)
                c.trash_requested.connect(self.confirm_and_trash)
                c.rename_requested.connect(lambda path: self.rename_cards([path]))
                self.cards[p] = c
                self.load_t(p)
                c.set_status(self.check_status(p))
                added += 1
        log.info(f"Importati {added} file ({len(paths)} totali scansionati).")
        self.refresh_grid()
        # L'analisi automatica post-import è stata rimossa: check_status() assegna
        # già lo stato corretto a ogni card durante l'import. L'utente può lanciare
        # manualmente l'analisi (che include la ricerca duplicati) con il tasto ANALIZZA.

    def _ask_loose_order(self, folder):
        """Cartella con immagini sciolte e sottocartelle: dove vanno le sciolte?"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Ordine delle pagine")
        msg.setText(f"La cartella <b>{os.path.basename(folder)}</b> contiene sia immagini "
                    "sciolte sia sottocartelle.<br><br>Le immagini sciolte vanno messe:")
        msg.addButton("Prima delle sottocartelle", QMessageBox.ButtonRole.AcceptRole)
        b_after = msg.addButton("Dopo le sottocartelle", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
        after = msg.clickedButton() == b_after
        (self._loose_last.add if after else self._loose_last.discard)(folder)
        log.info(f"Cartella '{os.path.basename(folder)}': immagini sciolte "
                 f"{'dopo' if after else 'prima del'}le sottocartelle")

    def merge_selected(self):
        """Unisce i fumetti selezionati (ordine naturale del nome) in un unico CBZ."""
        sel = sorted((p for p, c in self.cards.items() if c.selected),
                     key=lambda p: get_natural_sort_key(os.path.basename(p)))
        if len(sel) < 2:
            return
        dlg = MergeDialog(sel, self)
        if not dlg.exec():
            return
        name, dest = dlg.values()
        final_p = os.path.join(dest, name + ".cbz")
        log.info(f"Unione di {len(sel)} fumetti in '{final_p}': "
                 + ", ".join(os.path.basename(p) for p in sel))
        self.set_working(True, "Preparazione...")
        bw = BatchPrepWorker(sel, dlg.to_webp, self._loose_last)
        bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
        bw.page_progress.connect(self._on_prep_pages)

        def ready(tasks, to_webp):
            self._discard_thread(bw)
            if len(tasks) != len(sel):
                for t in tasks:
                    if t['tmp']:
                        shutil.rmtree(t['tmp'], ignore_errors=True)
                self.set_working(False)
                QMessageBox.warning(self, "Unisci",
                                    "Non è stato possibile leggere tutti i fumetti: unione annullata, "
                                    "originali intatti (dettagli nel log).")
                return
            self.start_processing([{
                'src': sel[0], 'extra_srcs': sel[1:], 'dest': final_p,
                'images': [img for t in tasks for img in t['images']],
                'tmp': tasks[0]['tmp'], 'extra_tmps': [t['tmp'] for t in tasks[1:]],
                'comicinfo': tasks[0]['comicinfo'],   # solo quello del primo fumetto
                'edited': True, 'title': name,
            }], to_webp)

        bw.ready.connect(ready)
        bw.start()
        self._add_thread(bw)

    def rename_selected(self):
        sel = [p for p, c in self.cards.items() if c.selected]
        if sel:
            self.rename_cards(sel)

    def rename_cards(self, paths):
        """Rinomina sul disco (solo il nome, mai sovrascrivendo) e aggiorna le card."""
        if self.current_worker:
            QMessageBox.information(self, "Rinomina", "Attendi la fine del lavoro in corso.")
            return
        dlg = RenameDialog(paths, self)
        if not dlg.exec():
            return
        errors = []
        for old, new in dlg.renames():
            try:
                # ricontrollo: su Linux os.rename sovrascriverebbe in silenzio
                if os.path.exists(new) and not os.path.samefile(old, new):
                    raise FileExistsError("esiste già un file con questo nome")
                os.rename(old, new)
            except OSError as e:
                log.error(f"Rinomina fallita: '{os.path.basename(old)}': {e}")
                errors.append(f"{os.path.basename(old)}: {e}")
                continue
            log.info(f"Rinominato: '{os.path.basename(old)}' → '{os.path.basename(new)}'")
            if old in self.cards:
                c = self.cards.pop(old)
                c.file_path = new
                c.name.setText(os.path.basename(new))
                self.cards[new] = c
            if old in self._loose_last:
                self._loose_last.discard(old)
                self._loose_last.add(new)
        self.reset_ui()
        self.refresh_grid()
        if errors:
            QMessageBox.warning(self, "Rinomina", "Non rinominati (dettagli nel log):\n"
                                + "\n".join(errors[:8]))

    # FIX #2: trash cross-platform con feedback in caso di errore
    def trash_file(self, p):
        log.info(f"Cestino: '{os.path.basename(p)}'")
        if _trash_file_cross_platform(p):
            log.info("  → spostato nel cestino con successo.")
            self.rem(p)
        else:
            log.error(f"  → FALLITO. Impossibile cestinare '{p}'")
            QMessageBox.warning(
                self, "Errore Cestino",
                f"Impossibile spostare nel cestino:\n{p}\n\n"
                "Installa 'send2trash':\n  pip install send2trash"
            )

    def trash_selected(self):
        sel = [p for p, c in self.cards.items() if c.selected]
        if sel and QMessageBox.question(
            self, "Cestina", f"Spostare {len(sel)} file nel cestino?"
        ) == QMessageBox.StandardButton.Yes:
            for p in sel:
                self.trash_file(p)
            self.reset_ui()

    def trash_all_duplicates(self):
        dupes = [p for p, c in self.cards.items() if c.status_code == 4]
        if dupes and QMessageBox.question(
            self, "Cestina", "Eliminare i duplicati?"
        ) == QMessageBox.StandardButton.Yes:
            for p in dupes:
                self.trash_file(p)
            self.reset_ui()

    def repair_selected(self):
        m = self.ask_mode()
        if m != "cancel":
            targets = [p for p, c in self.cards.items() if c.selected]
            self.set_working(True, "Preparazione...")
            bw = BatchPrepWorker(targets, m == "convert", self._loose_last)
            bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
            bw.page_progress.connect(self._on_prep_pages)
            bw.ready.connect(lambda t, mv: (self._discard_thread(bw), self.start_processing(t, mv)))
            bw.start()
            self._add_thread(bw)

    def repair_all_trigger(self):
        m = self.ask_mode()
        if m == "cancel":
            return
        if m == "convert":
            # esclusi duplicati, danneggiati e già convertiti (niente ricompressione)
            targets = [p for p, c in self.cards.items() if c.status_code not in (3, 4, 5)]
        else:
            targets = [p for p, c in self.cards.items() if c.status_code in (0, 1)]
        if not targets:
            QMessageBox.information(self, "Ottimizzazione", "Nessun file idoneo trovato.")
            return
        self.set_working(True, "Preparazione...")
        bw = BatchPrepWorker(targets, m == "convert", self._loose_last)
        bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
        bw.page_progress.connect(self._on_prep_pages)
        bw.ready.connect(lambda t, mv: (self._discard_thread(bw), self.start_processing(t, mv)))
        bw.start()
        self._add_thread(bw)

    def ask_mode(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Ottimizzazione")
        msg.setText("Scegli la modalità:")
        b_c = msg.addButton("Converti WebP", QMessageBox.ButtonRole.AcceptRole)
        b_r = msg.addButton("Solo Ripara",   QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Annulla",             QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == b_c:
            return "convert"
        if msg.clickedButton() == b_r:
            return "repair"
        return "cancel"

    def open_editor(self, path):
        self.set_working(True, "Apertura...")
        l = LoadingWorker(path, path in self._loose_last)
        l.progress.connect(lambda v, t: self.set_working(True, f"Apertura: Pagina {v}/{t}...", v, t))

        def done(p, t, i):
            self.set_working(False)
            self._discard_thread(l)
            dlg = AdvancedEditor(p, t, i, self)
            if dlg.exec():
                # get_paths() converte già le immagini aggiunte nel formato prevalente
                self.start_processing([{'src': p, 'images': dlg.get_paths(), 'tmp': t,
                                        'comicinfo': find_comicinfo(t), 'edited': True}],
                                      to_webp=False)
            else:
                shutil.rmtree(t, ignore_errors=True)

        l.finished.connect(done)
        l.error.connect(lambda m: (self.set_working(False), QMessageBox.warning(self, "Errore", m)))
        l.start()
        self._add_thread(l)

    def individual_repair(self, path):
        m = self.ask_mode()
        if m != "cancel":
            self.set_working(True, "Preparazione...")
            bw = BatchPrepWorker([path], m == "convert", self._loose_last)
            bw.page_progress.connect(self._on_prep_pages)
            bw.ready.connect(lambda t, mv: (self._discard_thread(bw), self.start_processing(t, mv)))
            bw.start()
            self._add_thread(bw)

    def request_stop(self):
        if self.current_worker:
            dlg = StopDialog(self)
            r   = dlg.exec()
            if r == 1:
                self.current_worker.abort_now()
                self.status_msg.setText("Interruzione in corso, pulizia file temporanei...")
            elif r == 2:
                self.current_worker.stop_later()
                self.status_msg.setText("Termino il fumetto in corso, poi mi fermo...")

    def check_status(self, p):
        real_fmt = detect_real_format(p)
        ext      = os.path.splitext(p)[1].lower()
        # PDF o RAR (anche con estensione .cbz) → da sistemare
        if ext == '.pdf' or real_fmt == 'pdf':
            return 0
        if real_fmt == 'rar' or (real_fmt is None and ext in ('.cbr', '.rar')):
            return 0
        if real_fmt == 'rar' and ext in ('.cbz', '.zip'):
            return 0   # CBZ con contenuto RAR — mismatch
        # ZIP reale o presunto
        try:
            return cbz_status(p)
        except Exception as e:
            log.warning(f"check_status error '{p}': {e}")
            return 0

    def load_t(self, p):
        w = ThumbWorker(p)

        def _on_thumb_done(path, data):
            self._discard_thread(w)
            if path not in self.cards:
                return
            # QPixmap creato nel main thread dai bytes raw (thread-safe)
            pix = QPixmap()
            if pix.loadFromData(data):
                self.cards[path].set_pixmap(pix)
            else:
                log.warning(f"load_t: QPixmap.loadFromData fallito per '{path}'")

        w.done.connect(_on_thumb_done)
        w.start()
        self._add_thread(w)

    def clear_all(self):
        for p in list(self.cards.keys()):
            self.cards[p].deleteLater()
        self.cards.clear()
        self.refresh_grid()
        self.reset_ui()
        self.btn_trash_dupes.setVisible(False)

    def refresh_grid(self):
        # Svuota la griglia
        for i in reversed(range(self.grid_l.count())):
            w = self.grid_l.itemAt(i).widget()
            if w:
                w.setParent(None)

        n    = len(self.cards)
        cols = self._cols_for_count(n)
        self._apply_window_width(cols)

        for i, p in enumerate(sorted(self.cards.keys(), key=get_natural_sort_key)):
            self.grid_l.addWidget(self.cards[p], i // cols, i % cols)
        empty = not self.cards
        self.grid_stack.setCurrentWidget(self.empty_lbl if empty else self.scroll)
        self.top_bar_scroll.setVisible(not empty)
        if empty != self._was_empty:   # la frase cambia solo quando la lista si svuota/riempie
            self._was_empty = empty
            self.hint_lbl.setText(random.choice(_EMPTY_HINTS) if empty else _HINT_CARDS)
            self.hint_lbl.setToolTip("Formati: CBZ, CBR, ZIP, RAR, PDF e cartelle di immagini"
                                     if empty else _HINT_CARDS_TIP)
        if self.last_clicked not in self.cards.values():
            self.last_clicked = None   # card rimossa: lo Shift+click ripartirebbe da lei
        self._update_sel_buttons()

    def rem(self, p):
        if p in self.cards:
            self.cards.pop(p).deleteLater()
            self.refresh_grid()

    def set_drop_style(self, a):
        """Mentre si trascinano file sulla finestra: scritta ciano e bordo tratteggiato."""
        self.empty_lbl.label.setStyleSheet(f"color: {'#00e5ff' if a else '#888'};")
        self.grid_stack.setStyleSheet(
            "QStackedWidget#grid_stack { border: 2px dashed #00e5ff; border-radius: 14px; }" if a else "")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
            self.set_drop_style(True)
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.set_drop_style(False)

    def dropEvent(self, e):
        self.set_drop_style(False)
        urls = [u.toLocalFile() for u in e.mimeData().urls()]
        if urls:
            self.set_working(True, "Scansione...")
            iw = ImportWorker(urls)
            iw.progress.connect(lambda v, t: self.set_working(True, f"Importazione: {v}/{t}", v, t))
            iw.finished.connect(lambda p: (self._discard_thread(iw), self.import_files(p)))
            iw.start()
            self._add_thread(iw)
