"""Scheda Libreria: albero delle cartelle della libreria e miniature dei suoi fumetti.
Le azioni (pagine, info e rinomina, sistema, cestino) sono quelle della finestra principale."""
import hashlib
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QDir, QMimeData, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QLineEdit,
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
from .comicinfo import nome_da_schema
from .metadata_dialog import SETTINGS, ConfermaRinomina, leggi_dati
from .style import set_variant
from .utils import _ARCHIVE_EXTS, _trash_file_cross_platform, get_natural_sort_key
from . import history, workers
from .workers import ThumbWorker, _Stoppable

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


# stato (vedi classify in workers.py) → (testo, colore) nella griglia
STATI = {0: ("da sistemare", "#ff9800"), 1: ("CBZ, non WebP", "#ffc107"), 3: ("WebP", None),
         4: ("doppione", "#e040fb"), 5: ("danneggiato", "#f44336")}
FILTRI = (("Cartella scelta", None), ("Da convertire in WebP", {0, 1}), ("Doppioni", {4}), ("Danneggiati", {5}))


SCHEMA_PREDEFINITO = "<Publisher>/<Series>"


def cartella_da_schema(schema, valori):
    """Sottocartella della libreria dalle info, es. "<Publisher>/<Series>" → "DC Comics/Batman".
    I campi vuoti spariscono con il loro separatore, i pezzi vuoti spariscono del tutto."""
    pezzi = [nome_da_schema(pezzo, valori, 1) for pezzo in schema.split("/")]
    return os.path.join(*[p for p in pezzi if p]) if any(pezzi) else ""


def piano_spostamenti(root, schema, paths):
    """([(vecchio, nuovo)], [senza info]). Un nome già usato prende un suffisso: mai sovrascrivere."""
    piano, senza_info, riservati = [], [], set()
    for p in paths:
        cartella = cartella_da_schema(schema, leggi_dati(p))
        if not cartella:
            senza_info.append(p)
            continue
        base, ext = os.path.splitext(os.path.basename(p))
        dest = os.path.join(root, cartella)
        nuovo, i = os.path.join(dest, base + ext), 1
        if os.path.normcase(nuovo) == os.path.normcase(p):
            continue
        while os.path.exists(nuovo) or os.path.normcase(nuovo) in riservati:
            nuovo = os.path.join(dest, f"{base}_{i}{ext}")
            i += 1
        riservati.add(os.path.normcase(nuovo))
        piano.append((p, nuovo))
    return piano, senza_info


def _cached(p):
    """True se il controllo del file è già in cache e il file non è cambiato."""
    hit = workers._ANALYSIS_CACHE.get(p)
    try:
        st = os.stat(p)
    except OSError:
        return False
    return bool(hit) and hit[0] == (st.st_size, st.st_mtime_ns)


def adopt_moved(paths):
    """Un file spostato o rinominato (anche fuori dall'app) ha la stessa dimensione e data di uno
    sparito: riprende il suo controllo invece di essere riletto da capo."""
    found = set(paths)
    gone = {k: rest for p, (k, *rest) in list(workers._ANALYSIS_CACHE.items())
            if p not in found and not os.path.exists(p)}
    for p in paths:
        if p not in workers._ANALYSIS_CACHE:
            try:
                st = os.stat(p)
            except OSError:
                continue
            key = (st.st_size, st.st_mtime_ns)
            if key in gone:
                workers._ANALYSIS_CACHE[p] = (key, *gone.pop(key))


class LibraryScanWorker(_Stoppable):
    """Controlla tutta la libreria: integrità, doppioni, WebP. Rilegge solo i file nuovi o cambiati
    (gli altri vengono dall'indice su disco), che salva ogni SAVE_EVERY file: uno Stop non perde niente."""
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict, list)    # {percorso: stato}, percorsi ricontrollati in questo giro
    THREADS = 6
    SAVE_EVERY = 200

    def __init__(self, root):
        super().__init__()
        self.root = root

    def _check(self, p):
        if not self._helper_started():
            return None
        return workers._integrity_and_signature(p)

    def run(self):
        self._started()
        paths = list_comics(self.root, recursive=True)
        adopt_moved(paths)
        fresh = [p for p in paths if not _cached(p)]
        log.info(f"Libreria: {len(paths)} fumetti, {len(fresh)} da controllare")
        checked = {p: workers._ANALYSIS_CACHE[p][1:] for p in paths if p not in fresh}
        with ThreadPoolExecutor(self.THREADS) as pool:
            futures = {pool.submit(self._check, p): p for p in fresh}
            for n, f in enumerate(as_completed(futures), 1):
                if self.aborted:
                    for other in futures:
                        other.cancel()
                    break
                checked[futures[f]] = f.result()
                self.progress.emit(n, len(fresh))
                if n % self.SAVE_EVERY == 0:
                    workers.save_index()
        workers.save_index()
        if self.aborted:
            self.cancelled.emit()
            return
        self.finished.emit(workers.classify(paths, checked)[0], fresh)


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
        self.results = {}                             # stato di ogni fumetto, dall'ultimo controllo
        self.scanner = None
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
        self.filtro = QComboBox()
        for testo, _stati in FILTRI:
            self.filtro.addItem(testo)
        self.filtro.currentIndexChanged.connect(lambda: self.refresh(force=True))
        self.lbl_scan = QLabel()
        self.lbl_scan.setStyleSheet("color: #00e5ff")
        self.b_scan = QPushButton("Controlla")
        self.b_scan.setToolTip("Integrità, doppioni e WebP di tutta la libreria (rilegge solo i file cambiati)")
        self.b_scan.clicked.connect(lambda: self.scan(always_ask=True))
        bar.addWidget(b_root)
        bar.addWidget(self.lbl_root, 1)
        bar.addWidget(self.lbl_scan)
        bar.addWidget(self.b_scan)
        bar.addWidget(self.filtro)
        bar.addWidget(self.chk_sub)
        l.addLayout(bar)

        cfg = QSettings(*SETTINGS)
        riga = QHBoxLayout()
        self.chk_auto = QCheckBox("Sposta qui i fumetti sistemati nella lista di lavoro, in cartelle:")
        self.chk_auto.setChecked(cfg.value("libreria/auto", False, type=bool))
        self.chk_auto.toggled.connect(lambda on: QSettings(*SETTINGS).setValue("libreria/auto", on))
        self.schema = QLineEdit(cfg.value("libreria/schema", SCHEMA_PREDEFINITO))
        self.schema.setToolTip("Campi del ComicInfo.xml tra < >, cartelle separate da /: es. <Publisher>/<Series>.\n"
                               "Un fumetto senza quei campi resta dov'è.")
        self.schema.editingFinished.connect(
            lambda: QSettings(*SETTINGS).setValue("libreria/schema", self.schema.text().strip() or SCHEMA_PREDEFINITO))
        riga.addWidget(self.chk_auto)
        riga.addWidget(self.schema, 1)
        l.addLayout(riga)

        actions = QHBoxLayout()
        self.buttons = []
        for text, slot, variant in (("PAGINE", self.open_pages, None),
                                    ("INFO E RINOMINA", self.rename, None),
                                    ("SISTEMA", self.repair, "primary"),
                                    ("RIORDINA", self.reorder, None),
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
        """Rilegge la cartella; ricostruisce la griglia solo se i fumetti sono cambiati o con `force`.
        Senza `force` (dopo un lavoro, una rinomina, il cestino) ricontrolla la libreria: solo i file cambiati."""
        stati = FILTRI[self.filtro.currentIndex()][1]
        if stati:
            paths = sorted((p for p, s in self.results.items() if s in stati and os.path.exists(p)),
                           key=get_natural_sort_key)
        else:
            paths = list_comics(self.folder, self.chk_sub.isChecked()) if self.folder else []
        if not force and self.results:
            QTimer.singleShot(0, self.scan)           # dopo un lavoro: stati aggiornati (rilegge solo i cambiati)
        if paths == self.paths and not force:
            return
        self.paths = paths
        self._queue.clear()
        self.list.clear()
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            testo, colore = STATI.get(self.results.get(p), ("", None))
            item.setToolTip(p + (f"\n{testo}" if testo else ""))
            if colore:
                item.setForeground(QBrush(QColor(colore)))
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

    # --- controllo della libreria ---

    def scan(self, always_ask=False):
        if not self.root or self.scanner:
            return
        workers.load_index()
        self.scanner = LibraryScanWorker(self.root)
        self.scanner.progress.connect(lambda v, t: self.lbl_scan.setText(f"Controllo: {v}/{t}"))
        self.scanner.finished.connect(lambda res, fresh: self._scanned(res, fresh, always_ask))
        self.scanner.cancelled.connect(self._scan_ended)
        self.b_scan.setText("Ferma controllo")
        self.b_scan.clicked.disconnect()
        self.b_scan.clicked.connect(self.scanner.abort)
        self.lbl_scan.setText("Controllo…")
        self.scanner.start()

    def _scan_ended(self):
        self.scanner = None
        self.lbl_scan.setText("")
        self.b_scan.setText("Controlla")
        self.b_scan.clicked.disconnect()
        self.b_scan.clicked.connect(lambda: self.scan(always_ask=True))

    def _scanned(self, results, fresh, always_ask):
        self._scan_ended()
        self.results = results
        self.refresh(force=True)
        if always_ask or any(results.get(p) in (0, 1, 4, 5) for p in fresh):   # solo problemi nuovi
            self.report()

    def report(self):
        """Riepilogo del controllo e cosa fare."""
        dupes = [p for p, s in self.results.items() if s == 4]
        broken = [p for p, s in self.results.items() if s == 5]
        convert = [p for p, s in self.results.items() if s in (0, 1)]
        if not (dupes or broken or convert):
            QMessageBox.information(self, "Libreria", f"Tutti i {len(self.results)} fumetti sono in ordine e in WebP.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Libreria")
        box.setText(f"<b>Controllo della libreria: {len(self.results)} fumetti</b><br><br>"
                    f"Doppioni: <b>{len(dupes)}</b><br>Danneggiati: <b>{len(broken)}</b><br>"
                    f"Da convertire in WebP: <b>{len(convert)}</b>")
        b_show = box.addButton("Mostra", QMessageBox.ButtonRole.AcceptRole)
        b_conv = box.addButton(f"Converti in WebP ({len(convert)})", QMessageBox.ButtonRole.ActionRole) if convert else None
        b_dup = box.addButton(f"Cestina doppioni ({len(dupes)})", QMessageBox.ButtonRole.ActionRole) if dupes else None
        box.addButton("Più tardi", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_show:
            self.win.tabs.setCurrentWidget(self)
            self.filtro.setCurrentIndex(next(i for i, (_t, st) in enumerate(FILTRI)
                                             if st and any(self.results[p] in st for p in dupes + broken + convert)))
        elif clicked is b_conv and self.win._free():
            self.win.process_paths(convert, True)
        elif clicked is b_dup and self.win._free() and QMessageBox.question(
                self, "Cestina doppioni", f"Spostare nel cestino {len(dupes)} doppioni?\n"
                "Di ogni gruppo resta il CBZ con il nome più corto.") == QMessageBox.StandardButton.Yes:
            self.win.trash_files(dupes)

    def stop(self):
        """Alla chiusura: niente miniature nuove, controllo fermato, attesa dei thread."""
        if self.scanner:
            self.scanner.abort()
            self.scanner.wait(15000)
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

    def reorder(self):
        """Riordina dalle info i fumetti selezionati, con conferma; si annulla dalla Cronologia."""
        sel = self.selected()
        if not sel or not self.win._free():
            return
        piano, senza_info = piano_spostamenti(self.root, self.schema.text().strip() or SCHEMA_PREDEFINITO, sel)
        if piano and ConfermaRinomina(piano, self, "Riordina dalle info", f"Spostare {len(piano)} fumetti?",
                                      "Sposta").exec():
            self.win._do_renames(piano, history.new_batch())
            self.win._refresh_undo()
        self._avvisa_senza_info(senza_info, "" if piano else "Niente da spostare.")

    def auto_move(self, paths):
        """A fine lavoro: i CBZ sistemati fuori dalla libreria ci finiscono, nelle cartelle dello schema."""
        if not (self.root and self.chk_auto.isChecked()):
            return
        root = os.path.join(os.path.abspath(self.root), "")
        fuori = [p for p in paths if os.path.exists(p) and not os.path.abspath(p).startswith(root)]
        piano, senza_info = piano_spostamenti(self.root, self.schema.text().strip() or SCHEMA_PREDEFINITO, fuori)
        if piano:
            log.info(f"Libreria: {len(piano)} fumetti spostati nella libreria")
            self.win._do_renames(piano, history.new_batch())
            self.win._refresh_undo()
        self._avvisa_senza_info(senza_info)

    def _avvisa_senza_info(self, senza_info, altrimenti=""):
        if senza_info:
            nomi = "\n".join(os.path.basename(p) for p in senza_info[:8])
            QMessageBox.information(self, "Libreria", f"{len(senza_info)} fumetti non hanno le info dello schema "
                                    f"«{self.schema.text()}» e restano dove sono:\n{nomi}")
        elif altrimenti:
            QMessageBox.information(self, "Libreria", altrimenti)

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
