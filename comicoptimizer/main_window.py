"""Finestra principale."""

import logging
import os
import random
import shutil
import subprocess
import sys
import threading
from collections import deque

from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices, QKeySequence, QPainter, QPixmap
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
    QProgressDialog,
    QMenu,
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
from .archives import get_archive_file_list
from .card import ComicCard
from .cbz import file_status
from .config import APP_VERSION, CARD_H, CARD_MARGIN, CARD_SPACING, CARD_W, COLS_DEFAULT, COLS_MAX, IS_MAC, IS_WIN
from . import aggiorna, history
from .dialogs import HistoryDialog, LogWindow, MergeDialog, StopDialog
from .metadata_dialog import ConfermaRinomina, MetadataDialog, in_background
from .editor import AdvancedEditor
from .library import LibraryView
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
    folder_subdirs,
    list_folder_pages,
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

LIBRARY_ROWS = 3   # righe di copertine visibili nella Libreria


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
        self._undo_batch     = None    # ultima rinomina ancora annullabile (dalla cronologia su disco)
        self._thumb_queue    = deque() # miniature in attesa: ne girano poche alla volta
        self._thumbs_running = 0
        self._grid_cols      = 0       # colonne attuali della griglia
        self._job_outputs    = []      # CBZ prodotti dal lavoro in corso
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
            "CBR, CBZ, CB7, PDF, EPUB... per me pari sono.",
            "Ho visto librerie peggiori. Poche, ma le ho viste.",
            "Pronto a fare spazio sul disco (e nel cuore).",
            "Anche Batman aveva bisogno di un Alfred. Eccomi.",
            "Le pagine perse non sono mai state un'opzione.",
            "Rinomino, unisco, comprimo. Tu rilassati.",
        ]
        self.ironic_lbl.setText(random.choice(frasi))
        history.prune()
        self._refresh_undo()                          # l'ultima rinomina si annulla anche dopo un riavvio
        if config.opzione("libreria/controllo_avvio", True):
            QTimer.singleShot(1500, self.library.scan)    # controllo della libreria (solo i file cambiati)
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

    def _busy(self):
        """True se c'è un lavoro sui file in corso (preparazione, elaborazione, apertura editor)."""
        if self.current_worker:
            return True
        with self._threads_lock:
            return any(isinstance(t, (BatchPrepWorker, LoadingWorker)) for t in self._active_threads)

    def _free(self):
        """Un lavoro alla volta: con uno già in corso avvisa e restituisce False."""
        if self._busy():
            QMessageBox.information(self, "Lavoro in corso", "Attendi la fine del lavoro in corso.")
            return False
        return True

    # FIX #14: closeEvent per terminare i thread prima di chiudere
    def closeEvent(self, event):
        self._closing = True
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.abort_now()
            # lascia al worker il tempo di cancellare le cartelle temporanee
            self.current_worker.wait(15000)
        self.library.stop()
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
                for f in [_log_path] + [f"{_log_path}.{i}" for i in (1, 2, 3)]:
                    if os.path.exists(f):
                        os.remove(f)
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
        # Finestra massimizzata: tutte le colonne che stanno nella sua larghezza.
        if self.isMaximized():
            return self._cols_fit(self.width(), 50)
        return min(max(COLS_DEFAULT, min(n, COLS_MAX)), self._cols_fit_screen())

    def _view_cols(self):
        """Colonne per la larghezza della finestra: la Libreria una in più della lista più grande."""
        if self.views.currentWidget() is self.library and not self.isMaximized():
            return self._cols_fit(QApplication.primaryScreen().availableGeometry().width(), COLS_MAX + 1)
        return self._cols_for_count(len(self.cards))

    def _cols_fit(self, avail, most):
        """Quante colonne di card (al massimo `most`, almeno 1) entrano in `avail` pixel."""
        cols = most
        # + 12: la barra di scorrimento verticale della griglia (vedi STYLESHEET)
        while cols > 1 and self._win_width_for_cols(cols) + 12 > avail:
            cols -= 1
        return cols

    def _cols_fit_screen(self):
        """Quante colonne di card entrano nella larghezza dello schermo (almeno 1)."""
        return self._cols_fit(QApplication.primaryScreen().availableGeometry().width(), COLS_MAX)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            if self.isMaximized():
                # massimizzata: niente larghezza fissa, la griglia usa tutto lo spazio
                self.setMinimumWidth(0)
                self.setMaximumWidth(16777215)
            QTimer.singleShot(0, self.refresh_grid)   # ripristinata: torna la larghezza calcolata

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isMaximized():
            if self.cards and self._cols_for_count(len(self.cards)) != self._grid_cols:
                self.refresh_grid()
            else:
                self._apply_window_width(self._grid_cols)   # solo il banner

    def _refit_width(self):
        """Riadatta la larghezza quando compaiono/spariscono i pulsanti della barra."""
        self._apply_window_width(self._view_cols())

    def _apply_window_width(self, cols):
        """Ridimensiona la finestra alla larghezza giusta per `cols` colonne.
        Massimizzata: la finestra non si tocca, si adatta solo il banner."""
        m = self.centralWidget().layout().contentsMargins()
        if self.isMaximized():
            if not self._banner.isNull():
                self.title_lbl.setPixmap(self._banner.scaledToWidth(
                    min(self.width() - m.left() - m.right(), self._banner.width()),
                    Qt.TransformationMode.SmoothTransformation))
            return
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
            # largo quanto la griglia, non quanto la finestra: se si allarga per i pulsanti
            # il banner non cambia altezza e le card non si spostano sotto il mouse
            self.title_lbl.setPixmap(self._banner.scaledToWidth(
                min(self._win_width_for_cols(cols), w) - m.left() - m.right(),
                Qt.TransformationMode.SmoothTransformation))
        self.setMinimumHeight(min(600, screen.height()))
        self.setMaximumHeight(screen.height())
        if not self.isVisible():
            self.resize(w, min(h, screen.height()))
        self._fit_height()
        if self.views.currentWidget() is self.library:
            QTimer.singleShot(0, self._trim_library)      # dopo il ridimensionamento

    def _trim_library(self):
        """La Libreria finisce poco dopo l'ultima copertina: via lo spazio che non basta per un'altra."""
        lst = self.library.list
        if self.isMaximized() or self.views.currentWidget() is not self.library or not lst.isVisible():
            return
        extra = lst.viewport().width() % lst.gridSize().width()
        if extra > 8:
            self.setFixedWidth(self.width() - extra + 8)
            if not self._banner.isNull():
                m = self.centralWidget().layout().contentsMargins()
                self.title_lbl.setPixmap(self._banner.scaledToWidth(
                    min(self.title_lbl.pixmap().width(), self.width() - m.left() - m.right()),
                    Qt.TransformationMode.SmoothTransformation))
        # in altezza: LIBRARY_ROWS righe intere (meno se lo schermo è basso), mai copertine tagliate
        self.centralWidget().layout().activate()
        gh = lst.gridSize().height()
        other = self.height() - lst.viewport().height()
        free = QApplication.primaryScreen().availableGeometry().height() - (self.frameGeometry().height() - self.height())
        need = other + LIBRARY_ROWS * gh + 8 - free
        pix = self.title_lbl.pixmap()
        if need > 0 and not self._banner.isNull():   # come con le card: prima si abbassa il banner
            self.title_lbl.setPixmap(self._banner.scaledToHeight(
                max(40, pix.height() - need), Qt.TransformationMode.SmoothTransformation))
            self.centralWidget().layout().activate()
            other = self.height() - lst.viewport().height()
        rows = LIBRARY_ROWS
        while rows > 1 and other + rows * gh + 8 > free:
            rows -= 1
        self.setFixedHeight(other + rows * gh + 8)

    def _fit_height(self):
        """Con dei fumetti, una fila intera di card deve stare senza barra di scorrimento:
        la finestra si allunga (fin dove arriva lo schermo), poi se serve il banner si abbassa."""
        if not self.cards or self.isMaximized():
            return
        self.centralWidget().layout().activate()
        m = self.grid_l.contentsMargins()
        missing = CARD_H + m.top() + m.bottom() - self.grid_stack.height()
        if missing <= 0:
            return
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        grow = max(0, min(missing, screen_h - self.height()))
        if grow:
            self.resize(self.width(), self.height() + grow)
            missing -= grow
        pix = self.title_lbl.pixmap()
        if missing > 0 and not pix.isNull():
            self.title_lbl.setPixmap(self._banner.scaledToHeight(
                max(40, pix.height() - missing), Qt.TransformationMode.SmoothTransformation))

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

        self.btn_all = QPushButton("SISTEMA")
        self.btn_all.setMinimumHeight(42)
        set_variant(self.btn_all, "primary")
        self.btn_all.setToolTip("Ripara o converte in WebP tutti i fumetti, o solo i selezionati")
        self.btn_all.clicked.connect(self.repair_trigger)

        self.btn_sel_all = QPushButton("SELEZIONA TUTTO")
        self.btn_sel_all.setMinimumHeight(42)
        self.btn_sel_all.setToolTip("Ctrl+A seleziona tutto, Esc toglie la selezione")
        self.btn_sel_all.setVisible(False)
        # con almeno un fumetto selezionato toglie la selezione, altrimenti seleziona tutto
        self.btn_sel_all.clicked.connect(
            lambda: self.select_all(not any(c.selected for c in self.cards.values())))

        self.btn_trash_sel = QPushButton("CESTINA")
        self.btn_trash_sel.setMinimumHeight(42)
        set_variant(self.btn_trash_sel, "danger")
        self.btn_trash_sel.setToolTip("Sposta nel cestino i fumetti selezionati")
        self.btn_trash_sel.setVisible(False)
        self.btn_trash_sel.clicked.connect(self.trash_selected)

        self.btn_merge = QPushButton("UNISCI")
        self.btn_merge.setMinimumHeight(42)
        set_variant(self.btn_merge, "accent")
        self.btn_merge.setToolTip("Unisce i fumetti selezionati in un unico CBZ")
        self.btn_merge.setVisible(False)
        self.btn_merge.clicked.connect(self.merge_selected)

        self.btn_rename = QPushButton("INFO E RINOMINA")
        self.btn_rename.setMinimumHeight(42)
        self.btn_rename.setToolTip("Metadati (ComicInfo.xml), ricerca online e rinomina dei fumetti selezionati (F2)")
        self.btn_rename.setVisible(False)
        self.btn_rename.clicked.connect(self.rename_selected)

        self.btn_undo_rename = QPushButton("ANNULLA RINOMINA")
        self.btn_undo_rename.setMinimumHeight(42)
        set_variant(self.btn_undo_rename, "muted")
        self.btn_undo_rename.setToolTip("Rimette i nomi di prima ai fumetti dell'ultima rinomina\n"
                                        "(anche dopo aver chiuso il programma; le altre nella Cronologia)")
        self.btn_undo_rename.setVisible(False)
        self.btn_undo_rename.clicked.connect(self.undo_rename)

        self.btn_move = QPushButton("SPOSTA IN LIBRERIA")
        self.btn_move.setMinimumHeight(42)
        self.btn_move.setToolTip("Sposta i selezionati nella libreria, nelle cartelle dello schema "
                                 "(es. Editore/Serie) lette dalle info; si annulla dalla Cronologia")
        self.btn_move.setVisible(False)
        self.btn_move.clicked.connect(lambda: self.library.reorder(self._selected()))

        self.btn_trash_dupes = QPushButton("PULISCI DUPLICATI")
        self.btn_trash_dupes.setMinimumHeight(42)
        set_variant(self.btn_trash_dupes, "muted")
        self.btn_trash_dupes.setVisible(False)
        self.btn_trash_dupes.clicked.connect(self.trash_all_duplicates)

        top_bar.setSpacing(8)
        self.btn_lib = QPushButton("← LIBRERIA")
        self.btn_lib.setMinimumHeight(42)
        self.btn_lib.setToolTip("Torna alla Libreria (la lista di lavoro resta)")
        self.btn_lib.clicked.connect(lambda: self.show_view(self.library))
        top_bar.addWidget(self.btn_lib)
        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.btn_all)
        top_bar.addWidget(self.btn_sel_all)
        top_bar.addWidget(self.btn_merge)
        top_bar.addWidget(self.btn_rename)
        top_bar.addWidget(self.btn_move)
        top_bar.addWidget(self.btn_undo_rename)
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
        for _b in (self.btn_sel_all, self.btn_merge, self.btn_rename, self.btn_move, self.btn_undo_rename,
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
        # riga tutta sua: aiuto e frase (a riposo), avanzamento e STOP (al lavoro), per tutte e due le schede
        layout.addWidget(self.status_stack)
        work_tab = QWidget()
        work_l = QVBoxLayout(work_tab)
        work_l.setContentsMargins(0, 0, 0, 0)
        work_l.addWidget(self.top_bar_scroll)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)   # niente bordo: tutta l'altezza è per le card
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
            "CBZ · CBR · CB7 · ZIP · RAR · 7Z<br>PDF · EPUB · cartelle di immagini</div>",
            os.path.join(config.RES_DIR, "comicoptimizer_drop.png"))
        self.grid_stack = QStackedWidget()
        self.grid_stack.setObjectName("grid_stack")
        self.grid_stack.addWidget(self.empty_lbl)
        self.grid_stack.addWidget(self.scroll)
        self.set_drop_style(False)
        work_l.addWidget(self.grid_stack)
        self.library = LibraryView(self)
        # schermata unica: la Libreria; il Lavoro la sostituisce finché la lista non è vuota
        self.work_tab = work_tab
        self.views = QStackedWidget()
        self.views.addWidget(self.library)
        self.views.addWidget(work_tab)
        layout.addWidget(self.views)
        self._drag_selector = _DragSelector(self)
        self.grid_w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_w.customContextMenuRequested.connect(
            lambda pos: self._card_menu(self._drag_selector._card_at(pos), self.grid_w.mapToGlobal(pos)))

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
        self.upd_btn = QPushButton("Aggiorna app")
        set_variant(self.upd_btn, "link")
        self.upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upd_btn.clicked.connect(self.show_update)
        self.hist_btn = QPushButton("🕘 Rinomine")
        set_variant(self.hist_btn, "linklog")
        self.hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_btn.setToolTip("Cronologia delle rinomine: ognuna si può annullare, anche dopo un riavvio")
        self.hist_btn.clicked.connect(self.show_history)
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
        footer.addWidget(self.upd_btn)
        footer.addStretch()
        self.chk_notify = QCheckBox("🔔 Avvisi")
        self.chk_notify.setChecked(True)
        self.chk_notify.setToolTip(
            "A fine lavoro mostra una notifica di sistema e riproduce un suono.\n"
            "Il riepilogo a fine lavoro viene mostrato comunque."
        )

        footer.addWidget(self.hist_btn)
        footer.addSpacing(8)
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
        if not self._free():
            return
        if self.skip_trash_confirm:
            self.trash_files([path])
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
            self.trash_files([path])

    def run_analysis(self, auto=True):
        if not self.cards:
            self.btn_trash_dupes.setVisible(False)
            return
        self.set_working(True, "Analisi...")
        aw = AnalysisWorker(list(self.cards.keys()))
        aw.progress.connect(lambda v, t: self.set_working(True, f"Analisi: {v}/{t}", v, t))
        self._watch_stop(aw)

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
        outputs, self._job_outputs = self._job_outputs, []
        self.library.auto_move(outputs)
        self.reset_ui()
        self._refresh_undo()                          # file convertiti: quei nomi non ci sono più
        self.run_analysis(True)

        n_err = len(s['errors'])
        if s['aborted']:
            icon, title = QMessageBox.Icon.Warning, "Lavoro interrotto"
        elif n_err:
            icon, title = QMessageBox.Icon.Warning, "Lavoro completato con errori"
        else:
            icon, title = QMessageBox.Icon.Information, "Lavoro completato"

        verb = {"webp": "convertiti in WebP", "info": "salvati con le info"}.get(s['mode'], "riparati")
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
        if s.get('page_size'):
            (w0, h0), (w1, h1) = s['page_size']
            if (w0, h0) == (w1, h1):
                lines.append(f"Pagine: {w0}×{h0} px (la più grande), dimensione non modificata")
            else:
                lines.append(f"Pagine: {w0}×{h0} → <b>{w1}×{h1} px</b> (la più grande)")
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
        self.library.refresh()                        # file convertiti, rinominati o cestinati

    def show_news(self):
        msg = (f"<b>⚡ ComicOptimizer {APP_VERSION}: la tua libreria in ordine</b><br><br>"
               "&nbsp;&nbsp;📦 <b>CB7 ed EPUB:</b> si importano anche i CB7 e gli EPUB a fumetti, con le info del libro.<br>"
               "&nbsp;&nbsp;🕘 <b>Cronologia rinomine:</b> ogni rinomina si annulla, anche dopo aver chiuso il programma.<br>"
               "&nbsp;&nbsp;🔍 <b>Info e rinomina:</b> una finestra sola per metadati, ricerca su ComicVine, "
               "MyAnimeList, AniList e ComicsBox, e nomi costruiti dai metadati.<br>"
               "&nbsp;&nbsp;📚 <b>Unisci e cartelle:</b> più fumetti in uno; una cartella di immagini diventa un fumetto.<br>"
               "&nbsp;&nbsp;🛡️ <b>Originali al sicuro:</b> il nuovo CBZ viene verificato prima di toccare "
               "l'originale, che finisce nel cestino; se il cestino non c'è, l'originale resta dov'è.<br><br>"
               "Mettiti comodo, al disordine ci pensiamo noi.")
        QMessageBox.information(self, f"Novità v{APP_VERSION}", msg)

    def show_update(self):
        box = QMessageBox(self)
        box.setWindowTitle("Aggiorna app")
        box.setText(f"Versione in uso: <b>{APP_VERSION}</b>")
        controlla = box.addButton("Controlla aggiornamenti", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Chiudi", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not controlla:
            return
        self.upd_btn.setEnabled(False)
        self.upd_btn.setText("Controllo…")
        in_background(self, aggiorna.ultima_release, self._update_checked)

    def _update_checked(self, release, errore):
        self.upd_btn.setEnabled(True)
        self.upd_btn.setText("Aggiorna app")
        if errore:
            QMessageBox.warning(self, "Aggiorna app", f"Controllo non riuscito:\n{errore}")
            return
        tag = release.get("tag_name", "")
        if not aggiorna.piu_nuova(tag, APP_VERSION):
            QMessageBox.information(self, "Aggiorna app", f"Hai già l'ultima versione ({APP_VERSION}).")
            return
        appimage, asset = aggiorna.appimage_in_uso(), aggiorna.asset_appimage(release)
        if not (appimage and asset):           # Windows, macOS o programma avviato dai sorgenti
            if QMessageBox.question(self, "Aggiorna app", f"È disponibile la versione {tag}.\n"
                                    "Apro la pagina per scaricarla?") == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(release["html_url"]))
            return
        if QMessageBox.question(self, "Aggiorna app", f"È disponibile la versione {tag}.\n"
                                f"Scarico e sostituisco ora l'AppImage?\n{appimage}") != QMessageBox.StandardButton.Yes:
            return
        attesa = QProgressDialog(f"Scarico {asset['name']}…", None, 0, 0, self)
        attesa.setWindowTitle("Aggiorna app")
        attesa.setWindowModality(Qt.WindowModality.WindowModal)
        attesa.show()

        def fine(nuova, errore):
            attesa.close()
            if errore:
                log.error(f"Aggiornamento non riuscito: {errore}")
                QMessageBox.warning(self, "Aggiorna app", f"Aggiornamento non riuscito:\n{errore}\n\n"
                                    "La versione attuale non è stata toccata.")
                return
            log.info(f"AppImage aggiornata a {tag}")
            if QMessageBox.question(self, "Aggiorna app", f"Aggiornato a {tag}. Riavvio ora?") == QMessageBox.StandardButton.Yes:
                subprocess.Popen([nuova], start_new_session=True)
                self.close()

        in_background(self, lambda: aggiorna.sostituisci_appimage(asset, appimage), fine)

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
               "<b>Unica eccezione, solo se la usi tu:</b> la <i>Ricerca online</i>, nella finestra Info e rinomina, "
               "invia alla fonte scelta (ComicVine, MyAnimeList, AniList o ComicsBox) <b>il testo che vedi e "
               "confermi</b>, con la tua chiave API se la fonte ne chiede una, e ne scarica schede e copertine. "
               "Mai i file o il percorso. Senza aprire quella ricerca l'app non usa Internet.<br><br>"
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
        self.btn_merge.setVisible(sel_n > 1)
        self.btn_rename.setVisible(sel_n > 0)
        self.btn_trash_sel.setVisible(sel_n > 0)
        self.btn_move.setVisible(sel_n > 0 and bool(self.library.root))
        self.btn_sel_all.setVisible(bool(self.cards))
        self.btn_sel_all.setText("DESELEZIONA TUTTO" if sel_n else "SELEZIONA TUTTO")

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
        if s in (2, 3):
            self._job_outputs.append(n)               # a fine lavoro, eventualmente nella libreria
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
        self.views.setCurrentWidget(self.work_tab)       # lista vuota alla fine: refresh_grid torna alla Libreria
        added = 0
        for p, count in paths:
            if p not in self.cards:
                if os.path.isdir(p) and not self._confirm_folder(p):
                    continue
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
                c.set_status(file_status(p))
                added += 1
        log.info(f"Importati {added} file ({len(paths)} totali scansionati).")
        self.refresh_grid()

    def _show_skipped(self, skipped):
        """Un solo messaggio con i file non importati e il motivo."""
        if not skipped:
            return
        lines = "\n".join(f"• {os.path.basename(p)}: {why}" for p, why in skipped[:12])
        more = f"\n… e altri {len(skipped) - 12} (vedi log)" if len(skipped) > 12 else ""
        QMessageBox.warning(self, "Importazione", f"{len(skipped)} file non importati:\n\n{lines}{more}")

    def _confirm_folder(self, folder):
        """Cartella con più sottocartelle: diventa davvero UN fumetto? (una libreria trascinata
        per sbaglio diventerebbe un unico CBZ enorme)"""
        pages = list_folder_pages(folder)
        subs = folder_subdirs(folder, pages)
        if len(subs) < 2:
            return True
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Cartella di immagini")
        msg.setText(f"La cartella <b>{os.path.basename(folder)}</b> contiene {len(subs)} sottocartelle "
                    f"e {len(pages)} immagini.<br><br>Diventeranno <b>un solo fumetto</b>, con le "
                    "sottocartelle una dopo l'altra in ordine naturale.<br>"
                    "Se invece è una raccolta di fumetti diversi, trascina le singole cartelle.")
        b_yes = msg.addButton("Sì, un solo fumetto", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("No, salta questa cartella", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        ok = msg.clickedButton() == b_yes
        if not ok:
            log.info(f"Cartella '{os.path.basename(folder)}' saltata ({len(subs)} sottocartelle)")
        return ok

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

    def _selected(self):
        return [p for p, c in self.cards.items() if c.selected]

    def card_menu(self):
        """Le azioni possibili sulle card selezionate (tasto destro), come nella Libreria."""
        sel = self._selected()
        menu = QMenu(self)
        if not sel:
            return menu
        if len(sel) == 1:
            menu.addAction("Pagine", lambda: self.open_editor(sel[0]))
        menu.addAction("Info e rinomina", lambda: self.rename_cards(sel))
        menu.addAction("Sistema", self.repair_selected)
        if len(sel) > 1:
            menu.addAction("Unisci", lambda: self.merge_paths(sel))
        if self.library.root:
            menu.addAction("Sposta in libreria", lambda: self.library.reorder(sel))
        menu.addSeparator()
        menu.addAction("Togli dalla lista", lambda: [self.rem(p) for p in sel])
        menu.addAction("Cestina", self.trash_selected)
        return menu

    def _card_menu(self, card, pos):
        if card and not card.selected:               # tasto destro su una card non selezionata: solo lei
            self.select_all(False)
            card.selected = True
            card.update_style()
            self.last_clicked = card
            self._update_sel_buttons()
        menu = self.card_menu()
        if not menu.isEmpty():
            menu.exec(pos)

    def merge_selected(self):
        self.merge_paths([p for p, c in self.cards.items() if c.selected])

    def merge_paths(self, paths):
        """Unisce i fumetti (ordine naturale del nome) in un unico CBZ."""
        if not self._free():
            return
        sel = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        if len(sel) < 2:
            return
        dlg = MergeDialog(sel, self)
        if not dlg.exec():
            return
        name, dest = dlg.values()
        final_p = os.path.join(dest, name + ".cbz")
        log.info(f"Unione di {len(sel)} fumetti in '{final_p}': "
                 + ", ".join(os.path.basename(p) for p in sel))

        def ready(tasks, to_webp):
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

        self._run_prep(sel, dlg.to_webp, ready)

    def rename_selected(self):
        sel = [p for p, c in self.cards.items() if c.selected]
        if sel:
            self.rename_cards(sel)

    def rename_cards(self, paths):
        """Finestra Info e rinomina. I CBZ si salvano da lì; gli altri formati si convertono dopo la
        chiusura, con la catena di "Solo Ripara", per scrivere le info."""
        if not self._free():
            return
        batch = history.new_batch()          # tutti i passaggi della finestra sono un'operazione
        dlg = MetadataDialog(paths, self, on_rename=lambda pairs: self._do_renames(pairs, batch))
        dlg.exec()   # resta aperta per più passaggi: ogni "Rinomina" chiama _do_renames
        self._refresh_undo()
        jobs = dlg.conversioni
        if jobs:
            log.info(f"Info: {len(jobs)} fumetti da convertire")
            self.process_paths(list(jobs), False, lambda p: {
                'info': jobs[p][0], 'dest': jobs[p][1], 'info_job': True})   # riepilogo: "salvati con le info"

    def undo_rename(self):
        """Rimette i nomi di prima ai fumetti dell'ultima rinomina (mai sovrascrivendo)."""
        if self._undo_batch:
            self.undo_batch(self._undo_batch)

    def undo_batch(self, batch):
        """Annulla un'operazione della cronologia, dall'ultimo file rinominato al primo.
        I file che non ci sono più (spostati, convertiti) si saltano. Restituisce quanti annullati."""
        if not self._free():
            return 0
        pairs, missing, back = [], [], set()
        for old, new in reversed(batch["pending"]):
            # con più passaggi (A→B, poi B→C) B riappare solo dopo aver annullato B→C
            if os.path.exists(new) or new in back:
                pairs.append((new, old))
                back.add(old)
            else:
                missing.append(os.path.basename(new))
        if pairs:
            # con più passaggi (C→B, B→A) si mostra solo il risultato: C→A
            piano, inizio = {}, {}
            for da, a in pairs:
                primo = inizio.pop(da, da)
                piano[primo] = a
                inizio[a] = primo
            if not ConfermaRinomina(list(piano.items()), self, "Annulla rinomina",
                                    f"Ripristinare i nomi di {len(piano)} file?", "Ripristina").exec():
                return 0
        log.info(f"Annulla rinomina: {len(pairs)} file" + (f", {len(missing)} non più presenti" if missing else ""))
        done = self._do_renames(pairs)
        for _new, old in done:
            history.record_undo(batch["id"], old)
        if missing:
            QMessageBox.warning(self, "Annulla rinomina",
                                f"{len(missing)} file non ci sono più con il nome nuovo (spostati, convertiti "
                                "o rinominati fuori dall'app) e sono stati saltati:\n" + "\n".join(missing[:8]))
        self._refresh_undo()
        return len(done)

    def _refresh_undo(self):
        """"Annulla rinomina" per l'ultima operazione, se ha ancora file da riportare indietro."""
        last = next(iter(history.batches()), None)
        ok = last and [p for p in last["pending"] if os.path.exists(p[1])]
        self._undo_batch = last if ok else None
        self.btn_undo_rename.setVisible(bool(ok))

    def show_history(self):
        HistoryDialog(self, self.undo_batch).exec()

    def _do_renames(self, pairs, batch=None):
        """Rinomina sul disco (solo il nome, mai sovrascrivendo) e aggiorna le card.
        Con `batch` ogni rinomina riuscita va subito nella cronologia su disco.
        Restituisce le coppie (vecchio, nuovo) riuscite."""
        errors, done = [], []
        for old, new in pairs:
            try:
                # ricontrollo: su Linux os.rename sovrascriverebbe in silenzio
                if os.path.exists(new) and not os.path.samefile(old, new):
                    raise FileExistsError("esiste già un file con questo nome")
                os.makedirs(os.path.dirname(new), exist_ok=True)   # spostamento nella libreria
                shutil.move(old, new)                 # come os.rename, ma anche verso un altro disco
            except OSError as e:
                log.error(f"Rinomina fallita: '{os.path.basename(old)}': {e}")
                errors.append(f"{os.path.basename(old)}: {e}")
                continue
            log.info(f"Rinominato: '{os.path.basename(old)}' → '{os.path.basename(new)}'")
            if batch:
                history.record(batch, old, new)
            done.append((old, new))
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
        return done

    def trash_file(self, p):
        """Sposta nel cestino; se non si può il file resta dov'è. True se spostato."""
        log.info(f"Cestino: '{os.path.basename(p)}'")
        if _trash_file_cross_platform(p):
            log.info("  → spostato nel cestino con successo.")
            self.rem(p)
            return True
        log.error(f"  → non spostato nel cestino, resta al suo posto: '{p}'")
        return False

    def trash_files(self, paths):
        """Più file: un solo messaggio per quelli che non si sono potuti spostare."""
        failed = [p for p in paths if not self.trash_file(p)]
        if failed:
            names = "\n".join(os.path.basename(p) for p in failed[:8])
            more = f"\n… e altri {len(failed) - 8}" if len(failed) > 8 else ""
            QMessageBox.warning(
                self, "Cestino",
                f"{len(failed)} file non spostati nel cestino: il disco non ne ha uno "
                f"(es. disco di rete) o il file non è accessibile.\n"
                f"Sono rimasti al loro posto, niente è stato cancellato.\n\n{names}{more}")
        self.reset_ui()

    def trash_selected(self):
        if not self._free():
            return
        sel = [p for p, c in self.cards.items() if c.selected]
        if sel and QMessageBox.question(
            self, "Cestina", f"Spostare {len(sel)} file nel cestino?"
        ) == QMessageBox.StandardButton.Yes:
            self.trash_files(sel)

    def trash_all_duplicates(self):
        if not self._free():
            return
        dupes = [p for p, c in self.cards.items() if c.status_code == 4]
        if dupes and QMessageBox.question(
            self, "Cestina", "Spostare i duplicati nel cestino?"
        ) == QMessageBox.StandardButton.Yes:
            self.trash_files(dupes)

    def repair_trigger(self):
        """SISTEMA: con una selezione chiede se sistemare i selezionati o tutti."""
        if not self._free():
            return
        sel_n = sum(1 for c in self.cards.values() if c.selected)
        if not sel_n:
            self.repair_all_trigger()
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Sistema")
        msg.setText("Cosa vuoi sistemare?")
        b_sel = msg.addButton(f"Selezionati ({sel_n})", QMessageBox.ButtonRole.AcceptRole)
        b_all = msg.addButton(f"Tutti ({len(self.cards)})", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == b_sel:
            self.repair_selected()
        elif msg.clickedButton() == b_all:
            self.repair_all_trigger()

    def repair_selected(self):
        if not self._free():
            return
        m = self.ask_mode()
        if m != "cancel":
            targets = [p for p, c in self.cards.items() if c.selected]
            self.process_paths(targets, m == "convert")

    def repair_all_trigger(self):
        if not self._free():
            return
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
        self.process_paths(targets, m == "convert")

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
        if not self._free():
            return
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
        l.error.connect(lambda m: (self._discard_thread(l), self.set_working(False),
                                   QMessageBox.warning(self, "Errore", m)))
        self._watch_stop(l)
        l.start()
        self._add_thread(l)

    def individual_repair(self, path):
        if not self._free():
            return
        m = self.ask_mode()
        if m != "cancel":
            self.process_paths([path], m == "convert")

    def process_paths(self, paths, to_webp, extra=None):
        """Sistema/Converti/Salva info: ogni fumetto si estrae subito prima di convertirlo (dentro
        ProcessingWorker), non tutti all'inizio. extra(percorso) → campi in più del task."""
        tasks = [{'src': p, 'lazy': True, 'loose_last': p in self._loose_last,
                  'pages': getattr(self.cards.get(p), 'page_count', 0), **(extra(p) if extra else {})}
                 for p in paths]
        log.info(f"Lavoro su {len(tasks)} fumetti (estrazione durante la conversione)")
        self.start_processing(tasks, to_webp)

    def _run_prep(self, paths, to_webp, ready):
        """Estrazione di tutti i fumetti (BatchPrepWorker), poi ready(tasks, to_webp): serve all'unione,
        che li vuole tutti pronti insieme. Stop la annulla tutta."""
        self.set_working(True, "Preparazione...")
        bw = BatchPrepWorker(paths, to_webp, self._loose_last)
        bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
        bw.page_progress.connect(self._on_prep_pages)
        bw.ready.connect(lambda tasks, mv: (self._discard_thread(bw), ready(tasks, mv)))
        self._watch_stop(bw)
        bw.start()
        self._add_thread(bw)

    def _watch_stop(self, worker):
        """Lavoro fermato con Stop: si torna allo stato di prima (i temporanei li ha già tolti lui)."""
        def stopped():
            self._discard_thread(worker)
            self.set_working(False)
            log.info(f"Stop: {type(worker).__name__} annullato, nessun file modificato")
            QMessageBox.information(self, "Stop", "Lavoro annullato: nessun fumetto è stato modificato "
                                    "e i file temporanei sono stati cancellati.")
        worker.cancelled.connect(stopped)

    def request_stop(self):
        if self.current_worker:                       # conversione: alcuni fumetti possono essere già finiti
            dlg = StopDialog(self)
            r   = dlg.exec()
            if r == 1:
                self.current_worker.abort_now()
                self.status_msg.setText("Interruzione in corso, pulizia file temporanei...")
            elif r == 2:
                self.current_worker.stop_later()
                self.status_msg.setText("Termino il fumetto in corso, poi mi fermo...")
            return
        # importazione, analisi, estrazione, apertura dell'editor: niente è stato ancora scritto
        with self._threads_lock:
            jobs = [t for t in self._active_threads
                    if isinstance(t, (ImportWorker, AnalysisWorker, BatchPrepWorker, LoadingWorker))]
        for t in jobs:
            t.abort()
        if jobs:
            self.status_msg.setText("Interruzione in corso, pulizia file temporanei...")

    THUMBS_AT_ONCE = max(2, os.cpu_count() or 2)   # miniature caricate in parallelo

    def load_t(self, p):
        """Miniatura della card: in coda, al massimo THUMBS_AT_ONCE alla volta
        (importando 1000 CBR non partono 1000 processi 7z insieme)."""
        self._thumb_queue.append(p)
        self._next_thumbs()

    def _next_thumbs(self):
        while self._thumb_queue and self._thumbs_running < self.THUMBS_AT_ONCE:
            p = self._thumb_queue.popleft()
            if p not in self.cards or self._closing:
                continue
            w = ThumbWorker(p)
            w.done.connect(self._on_thumb_done)
            # "finished" arriva sempre, anche se la miniatura non riesce
            w.finished.connect(lambda w=w: self._thumb_finished(w))
            self._thumbs_running += 1
            self._add_thread(w)
            w.start()

    def _thumb_finished(self, w):
        self._discard_thread(w)
        self._thumbs_running -= 1
        self._next_thumbs()

    def _on_thumb_done(self, path, data):
        if path not in self.cards:
            return
        # QPixmap creato nel main thread dai bytes raw (thread-safe)
        pix = QPixmap()
        if pix.loadFromData(data):
            self.cards[path].set_pixmap(pix)
        else:
            log.warning(f"load_t: QPixmap.loadFromData fallito per '{path}'")

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
        if not n:
            self.views.setCurrentWidget(self.library)   # lista vuota: si torna alla Libreria
        cols = self._view_cols()
        self._grid_cols = cols
        self._apply_window_width(cols)
        # massimizzata: la griglia al centro (lo spazio avanzato si divide ai due lati)
        self.grid_l.setAlignment(Qt.AlignmentFlag.AlignTop | (
            Qt.AlignmentFlag.AlignHCenter if self.isMaximized() else Qt.AlignmentFlag.AlignLeft))

        for i, p in enumerate(sorted(self.cards.keys(), key=get_natural_sort_key)):
            self.grid_l.addWidget(self.cards[p], i // cols, i % cols)
        empty = not self.cards
        self.grid_stack.setCurrentWidget(self.empty_lbl if empty else self.scroll)
        self.top_bar_scroll.setVisible(not empty)
        if empty != self._was_empty:   # la frase cambia solo quando la lista si svuota/riempie
            self._was_empty = empty
            self.hint_lbl.setText(random.choice(_EMPTY_HINTS) if empty else _HINT_CARDS)
            self.hint_lbl.setToolTip("Formati: CBZ, CBR, CB7, ZIP, RAR, 7Z, PDF, EPUB a fumetti e cartelle di immagini"
                                     if empty else _HINT_CARDS_TIP)
        if self.last_clicked not in self.cards.values():
            self.last_clicked = None   # card rimossa: lo Shift+click ripartirebbe da lei
        self._update_sel_buttons()
        self._fit_height()   # la riga dei pulsanti può essere appena ricomparsa

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
        # i fumetti trascinati dalla Libreria vanno sulle cartelle dell'albero, non nella lista di lavoro
        if e.mimeData().hasUrls() and e.source() is not self.library.list:
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
            self.import_paths(urls)

    def show_view(self, w):
        self.views.setCurrentWidget(w)
        self.refresh_grid()

    def import_paths(self, urls):
        """Fumetti e cartelle nella lista di lavoro (trascinati o dalla Libreria)."""
        self.views.setCurrentWidget(self.work_tab)   # le card arrivano con import_files
        self.set_working(True, "Scansione...")
        iw = ImportWorker(urls)
        iw.progress.connect(lambda v, t: self.set_working(True, f"Importazione: {v}/{t}", v, t))
        iw.finished.connect(lambda p, s: (self._discard_thread(iw), self.import_files(p),
                                          self._show_skipped(s)))
        self._watch_stop(iw)
        iw.start()
        self._add_thread(iw)
