"""Scheda Libreria: albero delle cartelle della libreria e miniature dei suoi fumetti.
Le azioni (pagine, info e rinomina, sistema, cestino) sono quelle della finestra principale."""
import hashlib
import os
from collections import deque

from PyQt6.QtCore import QDir, QMimeData, QSettings, QSize, QStandardPaths, Qt, QUrl
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QFileSystemModel

from .logsetup import log
from .metadata_dialog import SETTINGS
from .style import set_variant
from .utils import _ARCHIVE_EXTS, _trash_file_cross_platform, get_natural_sort_key
from .workers import ThumbWorker

THUMB_W, THUMB_H = 140, 210
THUMBS_AT_ONCE = 4


def thumb_path(p):
    """File della miniatura in cache: cambia se cambia il fumetto (dimensione o data)."""
    st = os.stat(p)
    key = f"{p}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8", "surrogateescape")
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return os.path.join(base, "thumbs", hashlib.sha1(key).hexdigest() + ".jpg")


def save_thumb(p, data):
    """Riduce la prima pagina e la salva in cache. Ritorna il QPixmap o None."""
    img = QImage()
    if not img.loadFromData(data):
        return None
    img = img.scaled(THUMB_W * 2, THUMB_H * 2, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    try:
        dest = thumb_path(p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        img.save(dest, "JPG", 85)
    except OSError as e:
        log.debug(f"Miniatura non salvata in cache per '{p}': {e}")
    return QPixmap.fromImage(img)


def list_comics(folder, recursive=False):
    """Fumetti (archivi, PDF, EPUB) della cartella, in ordine naturale.
    shortcut: le cartelle di sole immagini non compaiono, da aggiungere se servissero nella libreria"""
    if recursive:
        found = [os.path.join(r, f) for r, _, fs in os.walk(folder) for f in fs
                 if f.lower().endswith(_ARCHIVE_EXTS)]
    else:
        try:
            found = [e.path for e in os.scandir(folder) if e.is_file() and e.name.lower().endswith(_ARCHIVE_EXTS)]
        except OSError:
            found = []
    return sorted(found, key=get_natural_sort_key)


class _ComicList(QListWidget):
    """Griglia di miniature; trascinando i fumetti escono i loro percorsi (per l'albero)."""

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction              # sull'albero i fumetti si spostano, non si copiano

    def mimeData(self, items):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole)) for i in items])
        return data


class LibraryView(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.root = QSettings(*SETTINGS).value("libreria/cartella", "") or ""
        self.folder = self.root
        self.paths = []
        self._queue = deque()
        self._running = set()
        self._placeholder = QPixmap(THUMB_W, THUMB_H)
        self._placeholder.fill(Qt.GlobalColor.darkGray)

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lbl_root = QLabel()
        self.lbl_root.setStyleSheet("color: #aaa")
        b_root = QPushButton("Scegli cartella…")
        b_root.clicked.connect(self.choose_root)
        self.chk_sub = QCheckBox("Includi sottocartelle")
        self.chk_sub.toggled.connect(lambda: self.show_folder(self.folder))
        bar.addWidget(b_root)
        bar.addWidget(self.lbl_root, 1)
        bar.addWidget(self.chk_sub)
        l.addLayout(bar)

        actions = QHBoxLayout()
        self.buttons = []
        for text, slot, variant in (("PAGINE", self.open_pages, None),
                                    ("INFO E RINOMINA", self.rename, None),
                                    ("SISTEMA", self.repair, "primary"),
                                    ("NELLA LISTA", self.to_work_list, None),
                                    ("CESTINA", self.trash, "danger")):
            b = QPushButton(text)
            b.setMinimumHeight(36)
            if variant:
                set_variant(b, variant)
            b.clicked.connect(slot)
            actions.addWidget(b)
            self.buttons.append((b, slot))
        actions.addStretch()
        l.addLayout(actions)

        # shortcut: lo spostamento trascinando sull'albero lo fa Qt (mai sovrascrive), ma non va nella
        # cronologia e non si annulla; da passare per _do_renames se servisse annullarlo
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(False)                 # rinomina delle cartelle e spostamento trascinando
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)   # doppio click apre, F2 rinomina
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.model.fileRenamed.connect(
            lambda *_: self.show_folder(self.model.filePath(self.tree.currentIndex()) or self.root))
        self.tree.selectionModel().currentChanged.connect(
            lambda cur, _prev: self.show_folder(self.model.filePath(cur)))

        self.list = _ComicList()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setGridSize(QSize(THUMB_W + 24, THUMB_H + 48))
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list.setMovement(QListView.Movement.Static)
        self.list.itemDoubleClicked.connect(lambda _i: self.open_pages())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.list)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 700])
        l.addWidget(split, 1)
        self.set_root(self.root)

    # --- cartelle ---

    def choose_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella della libreria", self.root)
        if folder:
            QSettings(*SETTINGS).setValue("libreria/cartella", folder)
            self.set_root(folder)

    def set_root(self, folder):
        self.root = folder
        self.lbl_root.setText(folder or "Nessuna libreria: scegli la cartella dove tieni i fumetti")
        self.tree.setEnabled(bool(folder))
        if folder:
            self.tree.setRootIndex(self.model.setRootPath(folder))
        self.show_folder(folder)

    def show_folder(self, folder):
        self.folder = folder
        self.refresh(force=True)

    def refresh(self, force=False):
        """Rilegge la cartella; ricostruisce la griglia solo se i fumetti sono cambiati."""
        paths = list_comics(self.folder, self.chk_sub.isChecked()) if self.folder else []
        if paths == self.paths and not force:
            return
        self.paths = paths
        self._queue.clear()
        self.list.clear()
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            item.setIcon(QIcon(self._cached_thumb(p) or self._placeholder))
            self.list.addItem(item)
        self._next_thumbs()

    def _cached_thumb(self, p):
        try:
            cached = thumb_path(p)
        except OSError:
            return None
        if os.path.exists(cached):
            pix = QPixmap(cached)
            if not pix.isNull():
                return pix
        self._queue.append(p)
        return None

    # --- miniature (poche alla volta, come nella lista di lavoro) ---

    def _next_thumbs(self):
        while self._queue and len(self._running) < THUMBS_AT_ONCE:
            p = self._queue.popleft()
            w = ThumbWorker(p)
            w.done.connect(self._thumb_done)
            w.finished.connect(lambda w=w: (self._running.discard(w), self._next_thumbs()))
            self._running.add(w)
            w.start()

    def _thumb_done(self, p, data):
        pix = save_thumb(p, data)
        if pix is None:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == p:
                item.setIcon(QIcon(pix))
                break

    def stop(self):
        """Alla chiusura: niente miniature nuove, attesa di quelle in corso."""
        self._queue.clear()
        for w in list(self._running):
            w.wait(2000)

    # --- azioni (quelle della finestra principale) ---

    def selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def open_pages(self):
        sel = self.selected()
        if sel:
            self.win.open_editor(sel[0])

    def rename(self):
        sel = self.selected()
        if sel:
            self.win.rename_cards(sel)

    def repair(self):
        sel = self.selected()
        if sel and self.win._free():
            mode = self.win.ask_mode()
            if mode != "cancel":
                self.win.process_paths(sel, mode == "convert")

    def to_work_list(self):
        sel = self.selected()
        if sel:
            self.win.import_paths(sel)
            self.win.tabs.setCurrentIndex(0)

    def trash(self):
        sel = self.selected()
        if sel and self.win._free() and QMessageBox.question(
                self, "Cestina", f"Spostare {len(sel)} file nel cestino?") == QMessageBox.StandardButton.Yes:
            self.win.trash_files(sel)

    def _list_menu(self, pos):
        if not self.selected():
            return
        menu = QMenu(self)
        for b, slot in self.buttons:
            menu.addAction(b.text().capitalize(), slot)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _tree_menu(self, pos):
        index = self.tree.indexAt(pos)
        folder = self.model.filePath(index) if index.isValid() else self.root
        if not folder:
            return
        menu = QMenu(self)
        menu.addAction("Nuova cartella…", lambda: self._new_folder(folder))
        if index.isValid():
            menu.addAction("Rinomina (F2)", lambda: self.tree.edit(index))
            menu.addAction("Sposta nel cestino", lambda: self._trash_folder(folder))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_folder(self, parent):
        name, ok = QInputDialog.getText(self, "Nuova cartella", "Nome:")
        if ok and name.strip():
            if not self.model.mkdir(self.model.index(parent), name.strip()).isValid():
                QMessageBox.warning(self, "Nuova cartella", "Cartella non creata (esiste già o nome non valido).")

    def _trash_folder(self, folder):
        if QMessageBox.question(self, "Sposta nel cestino",
                                f"Spostare nel cestino la cartella «{os.path.basename(folder)}» "
                                "con tutto il suo contenuto?") != QMessageBox.StandardButton.Yes:
            return
        if not _trash_file_cross_platform(folder):
            QMessageBox.warning(self, "Cestino", "La cartella non è stata spostata: il disco non ha un cestino "
                                "o non è accessibile. Non è stato cancellato niente.")
        elif os.path.normpath(self.folder).startswith(os.path.normpath(folder)):
            self.show_folder(self.root)
