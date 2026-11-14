"""Scheda Libreria: albero delle cartelle della libreria e miniature dei suoi fumetti.
Le azioni (pagine, info e rinomina, sistema, cestino) sono quelle della finestra principale."""
import ctypes
import hashlib
import json
import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PyQt6.QtCore import QDir, QEvent, QMimeData, QModelIndex, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from .config import IS_WIN, opzione
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
FILTRI = (("Cartella scelta", None), ("Da convertire in WebP", {0, 1}), ("Doppioni", {4}), ("Danneggiati", {5}),
          ("Senza info (ComicInfo)", {0, 1, 3}))    # i fumetti sani senza ComicInfo.xml (vedi refresh)


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


def _cached(p, completo=False):
    """True se il controllo del file è già in cache e il file non è cambiato (per un controllo
    completo: se anche quello in cache era completo; senza il ComicInfo registrato va riletto)."""
    hit = workers._ANALYSIS_CACHE.get(p)
    try:
        st = os.stat(p)
    except OSError:
        return False
    return (bool(hit) and hit[0] == (st.st_size, st.st_mtime_ns) and hit[4] is not None
            and (hit[5] or not completo))


def disco_meccanico(path):
    """Linux: True se `path` sta su un disco a piatti (lì leggere più file insieme fa saltare la testina).
    Il disco dal punto di montaggio in /proc/mounts: con btrfs il numero di dispositivo del file non serve."""
    try:
        path = os.path.realpath(path)
        with open("/proc/mounts") as f:
            montaggi = [riga.split()[:2] for riga in f]
        dev = max((m for m in montaggi if m[0].startswith("/dev/")
                   and (path + "/").startswith(m[1].replace("\\040", " ").rstrip("/") + "/")),
                  key=lambda m: len(m[1]))[0]
        base = os.path.realpath(os.path.join("/sys/class/block", os.path.basename(os.path.realpath(dev))))
        for d in (base, os.path.dirname(base)):       # partizione, poi il suo disco
            f = os.path.join(d, "queue", "rotational")
            if os.path.exists(f):
                with open(f) as fh:
                    return fh.read().strip() == "1"
    except (OSError, ValueError):
        pass
    return False


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

    def __init__(self, roots, completo=False):
        super().__init__()
        self.roots = [roots] if isinstance(roots, str) else list(roots)
        self.completo = completo                      # False: rapido, senza leggere le pagine

    def _check(self, p):
        if not self._helper_started():
            return None
        return workers._integrity_and_signature(p, self.completo)

    def run(self):
        self._started()
        paths = [p for r in self.roots for p in list_comics(r, recursive=True)]
        adopt_moved(paths)
        fresh = [p for p in paths if not _cached(p, self.completo)]
        # controllo completo su un disco a piatti: un file alla volta (leggerne 6 insieme è più lento)
        threads = 1 if self.completo and any(disco_meccanico(r) for r in self.roots) else self.THREADS
        log.info(f"Libreria: {len(paths)} fumetti, {len(fresh)} da controllare "
                 f"({'completo' if self.completo else 'rapido'}, {threads} alla volta)")
        nuovi = set(fresh)
        checked = {p: workers._ANALYSIS_CACHE[p][1:4] for p in paths if p not in nuovi}
        pool = ThreadPoolExecutor(threads)
        pending = {pool.submit(self._check, p): p for p in fresh}
        n = 0
        try:
            while pending and not self.aborted:       # lo Stop si vede entro un attimo, non a fine file
                done, _ = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for f in done:
                    checked[pending.pop(f)] = f.result()
                    n += 1
                    self.progress.emit(n, len(fresh))
                    if n % self.SAVE_EVERY == 0:
                        workers.save_index()
        finally:
            # shortcut: i file già in lettura finiscono da soli in background (finiscono nell'indice)
            pool.shutdown(wait=False, cancel_futures=True)
        workers.save_index()
        if self.aborted:
            self.cancelled.emit()
            return
        # 7: niente riga per doppione a ogni controllo (dopo ogni lavoro), solo il totale
        results, n, self.dupe_of = workers.classify(paths, checked, log_dupes=False)
        log.info(f"Libreria: {n} doppioni")
        self.finished.emit(results, fresh)


CAMPI_CARTELLE = ("Publisher", "Series", "Writer", "Penciller", "Year", "StoryArc")


MAX_LIBRERIE = 6
INFO_FILE = ".comicoptimizer.json"     # nella cartella base di ogni libreria: nome e schema


def librerie():
    """Cartelle delle librerie, in ordine (la prima volta: quella della 3.5, se c'era)."""
    cfg = QSettings(*SETTINGS)
    lista = cfg.value("librerie", [], type=list)
    if not lista and cfg.value("libreria/cartella", ""):
        lista = [cfg.value("libreria/cartella")]
    return [c for c in lista if c]


def info_libreria(cartella):
    """{'nome', 'schema'} dal file nascosto della libreria (o i valori di partenza)."""
    vecchio = (QSettings(*SETTINGS).value("libreria/schema", "") or "").strip()   # opzione della 3.5
    info = {"nome": os.path.basename(os.path.normpath(cartella)),
            "schema": vecchio or SCHEMA_PREDEFINITO}
    try:
        with open(os.path.join(cartella, INFO_FILE), encoding="utf-8") as f:
            info.update(json.load(f))
    except (OSError, ValueError):
        pass
    return info


def salva_info(cartella, **valori):
    """Aggiorna il file nascosto della libreria; OSError se la cartella non è scrivibile."""
    info = info_libreria(cartella)
    info.update(valori)
    path = os.path.join(cartella, INFO_FILE)
    if IS_WIN and os.path.exists(path):
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x80)   # nascosto: altrimenti open("w") fallisce
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    if IS_WIN:
        ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)    # su Windows il punto non basta a nasconderlo


def in_libreria(p, root):
    return os.path.abspath(p).startswith(os.path.join(os.path.abspath(root), ""))


def apri_cartella(cartella):
    QDesktopServices.openUrl(QUrl.fromLocalFile(cartella))


class _ComicList(QListWidget):
    """Griglia di miniature; trascinando i fumetti escono i loro percorsi (per l'albero)."""

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction              # sull'albero i fumetti si spostano, non si copiano

    def mimeData(self, items):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole)) for i in items])
        return data

    def _come_ctrl(self, e):
        """Il click semplice aggiunge o toglie quel fumetto (come le card della lista di lavoro):
        è un Ctrl+click. Shift+click (intervallo) resta com'è."""
        if e.button() == Qt.MouseButton.LeftButton and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            e = QMouseEvent(e.type(), e.position(), e.globalPosition(), e.button(), e.buttons(),
                            e.modifiers() | Qt.KeyboardModifier.ControlModifier)
        return e

    def mousePressEvent(self, e):
        super().mousePressEvent(self._come_ctrl(e))

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(self._come_ctrl(e))


class LibraryView(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        attiva, tutte = QSettings(*SETTINGS).value("libreria/attiva", ""), librerie()
        self.root = attiva if attiva in tutte else (tutte[0] if tutte else "")
        self.folder = self.root
        self.paths = []
        self.results = {}                             # stato di ogni fumetto, dall'ultimo controllo
        self.scanned_roots = []                       # librerie dell'ultimo controllo
        self.dupe_of = {}                             # doppione → il file che si tiene
        self.scanner = None
        self._queue = deque()
        self._running = set()

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lbl_root = QLabel()
        self.lbl_root.setStyleSheet("color: #aaa")
        self.scelta = QComboBox()
        self.scelta.setToolTip("Libreria da mostrare (si aggiungono in Opzioni)")
        self.scelta.currentIndexChanged.connect(self._cambia_libreria)
        b_home = QPushButton("⌂ Tutta la libreria")
        b_home.setToolTip("Torna alla cartella principale della libreria")
        b_home.clicked.connect(self.go_root)
        self.cerca = QLineEdit()
        self.cerca.setPlaceholderText("Cerca per nome…")
        self.cerca.setClearButtonEnabled(True)
        self.cerca.setToolTip("Cerca nei fumetti mostrati; dalla cartella principale, in tutta la libreria.\n"
                              "Più parole: devono esserci tutte.")
        self._attesa = QTimer(self, singleShot=True, interval=300)   # non a ogni tasto
        self._attesa.timeout.connect(lambda: self.refresh(force=True))
        self.cerca.textChanged.connect(self._attesa.start)
        self.chk_sub = QCheckBox("Includi sottocartelle")
        self.chk_sub.toggled.connect(lambda: self.show_folder(self.folder))
        self.filtro = QComboBox()
        for testo, _stati in FILTRI:
            self.filtro.addItem(testo)
        self.filtro.currentIndexChanged.connect(lambda: self.refresh(force=True))
        self.lbl_scan = QLabel()
        self.lbl_scan.setStyleSheet("color: #00e5ff")
        self.b_stop = QPushButton("■ Ferma")
        self.b_stop.setToolTip("Ferma il controllo della libreria (la volta dopo riprende da dove era arrivato)")
        self.b_stop.clicked.connect(self._stop_scan)
        self.b_stop.hide()                            # solo durante il controllo (che si avvia dalle Opzioni)
        self.b_apri = QPushButton("📂 Apri cartella")
        self.b_apri.clicked.connect(lambda: apri_cartella(self.folder))
        bar.addWidget(self.scelta)
        bar.addWidget(b_home)
        bar.addWidget(self.b_apri)
        bar.addWidget(self.lbl_root)
        bar.addWidget(self.cerca, 1)
        bar.addWidget(self.lbl_scan)
        bar.addWidget(self.b_stop)
        b_opts = QPushButton("Opzioni")
        b_opts.setToolTip("Librerie, controllo della libreria, conversione WebP, Info e rinomina")
        b_opts.clicked.connect(self.options)
        bar.addWidget(b_opts)
        bar.addWidget(self.filtro)
        bar.addWidget(self.chk_sub)
        l.addLayout(bar)


        actions = QHBoxLayout()
        self.pulsanti = {}
        for text, slot, variant, tip in (
                ("SELEZIONA TUTTO", self.toggle_all, None, "Seleziona tutti i fumetti mostrati, o toglie la selezione"
                                                          " (anche Ctrl+A)"),
                ("PAGINE", self.open_pages, None, "Apre le pagine del fumetto (anche con doppio click)"),
                ("INFO E RINOMINA", self.rename, None, "Metadati (ComicInfo.xml), ricerca online e rinomina"),
                ("AZIONI", None, "primary", "Ripara, converti in WebP, cestina i doppioni:\n"
                                              "sui selezionati, o su tutti i fumetti mostrati"),
                ("ORDINA IN CARTELLE", self.reorder, None,
                 "Sposta i selezionati nelle cartelle dello schema (es. Editore/Serie) lette dalle info;\n"
                 "si annulla dalla Cronologia"),
                ("CESTINA", self.trash, "danger", "Sposta nel cestino i selezionati")):
            b = QPushButton(text)
            b.setMinimumHeight(36)
            b.setToolTip(tip)
            if variant:
                set_variant(b, variant)
            if slot:
                b.clicked.connect(slot)
            actions.addWidget(b)
            self.pulsanti[text] = b
        azioni = QMenu(self)
        azioni.aboutToShow.connect(lambda: (azioni.clear(), self._riempi_azioni(azioni)))
        self.pulsanti["AZIONI"].setMenu(azioni)
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
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.model.fileRenamed.connect(
            lambda *_: self.show_folder(self.model.filePath(self.tree.currentIndex()) or self.root))
        self.tree.selectionModel().currentChanged.connect(
            lambda cur, _prev: self.show_folder(self.model.filePath(cur) or self.root))

        self.list = _ComicList()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.set_thumb_size()
        # sempre: la finestra è stretta sulle colonne, la barra che compare dopo ne farebbe andare a capo una
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list.setMovement(QListView.Movement.Static)
        self.list.itemDoubleClicked.connect(lambda _i: self.open_pages())
        self.list.itemSelectionChanged.connect(self._selezione_cambiata)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.list)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 700])
        l.addWidget(split, 1)
        self._riempi_scelta()
        self.set_root(self.root)

    # --- librerie e cartelle ---

    def _riempi_scelta(self):
        self.scelta.blockSignals(True)
        self.scelta.clear()
        for cartella in librerie():
            self.scelta.addItem(info_libreria(cartella)["nome"], cartella)
            self.scelta.setItemData(self.scelta.count() - 1, cartella, Qt.ItemDataRole.ToolTipRole)
        self.scelta.setCurrentIndex(max(0, self.scelta.findData(self.root)))
        self.scelta.setVisible(self.scelta.count() > 0)
        self.scelta.blockSignals(False)

    def _cambia_libreria(self, i):
        cartella = self.scelta.itemData(i) or ""
        QSettings(*SETTINGS).setValue("libreria/attiva", cartella)
        self.set_root(cartella)

    def schema(self):
        return info_libreria(self.root)["schema"] if self.root else SCHEMA_PREDEFINITO

    def options(self):
        from .opzioni import Opzioni                  # qui: opzioni.py usa le funzioni di questo file
        dlg = Opzioni(self)
        if dlg.exec():
            self.set_thumb_size()
            tutte = librerie()
            nuove = [c for c in tutte if c not in self.scanned_roots]
            root = self.root if self.root in tutte else (tutte[0] if tutte else "")
            self.root = root
            self._riempi_scelta()
            self._cambia_libreria(self.scelta.currentIndex()) if tutte else self.set_root("")
            if dlg.controllo is not None:             # "Controlla ora" / "Controllo completo…"
                self.scan(always_ask=True, completo=dlg.controllo)
            elif nuove:
                self.scan()
            self.win.refresh_grid()                   # larghezza della finestra sulle nuove miniature

    def eventFilter(self, obj, ev):
        # file trascinati da fuori sull'albero: nella lista di lavoro, non spostati nella libreria
        if ev.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop) \
                and ev.source() is not self.list and ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            if ev.type() == QEvent.Type.Drop:
                self.win.import_paths([u.toLocalFile() for u in ev.mimeData().urls()])
            return True
        return False

    def set_root(self, folder):
        self.root = folder
        self.tree.setEnabled(bool(folder))
        if folder:
            self.tree.setRootIndex(self.model.setRootPath(folder))
        self.show_folder(folder)

    def set_thumb_size(self):
        """Dimensione delle miniature scelta nelle Opzioni (la cache è al doppio: nitide anche grandi)."""
        w = opzione("libreria/miniature", THUMB_W)
        h = w * THUMB_H // THUMB_W
        self.list.setIconSize(QSize(w, h))
        self.list.setGridSize(QSize(w + 24, h + 48))
        self._placeholder = QPixmap(w, h)
        self._placeholder.fill(Qt.GlobalColor.darkGray)

    def go_root(self):
        self.tree.setCurrentIndex(QModelIndex())      # niente cartella scelta: show_folder(root)
        if self.folder != self.root:
            self.show_folder(self.root)

    def show_folder(self, folder):
        self.folder = folder
        self.lbl_root.setText("Nessuna libreria: scegli la cartella in Opzioni, o trascina qui i file da sistemare")
        self.lbl_root.setVisible(not folder)
        self.b_apri.setVisible(bool(folder))
        self.b_apri.setToolTip(f"Apre nel gestore file:\n{folder}")
        self.refresh(force=True)

    def refresh(self, force=False):
        """Rilegge la cartella; ricostruisce la griglia solo se i fumetti sono cambiati o con `force`.
        Senza `force` (dopo un lavoro, una rinomina, il cestino) ricontrolla la libreria: solo i file cambiati."""
        stati = FILTRI[self.filtro.currentIndex()][1]
        parole = self.cerca.text().lower().split()
        trovato = lambda p: all(w in os.path.basename(p).lower() for w in parole)
        gruppi = {}                                   # doppioni: ogni fumetto accanto a quello che si tiene
        if stati:
            senza_info = FILTRI[self.filtro.currentIndex()][0].startswith("Senza info")
            paths = sorted((p for p, s in self.results.items()
                            if s in stati and in_libreria(p, self.root) and os.path.exists(p)
                            and not (senza_info and workers._ANALYSIS_CACHE.get(p, (0,) * 6)[4])),
                           key=get_natural_sort_key)
            if stati == {4}:
                for p in paths:
                    gruppi.setdefault(self.dupe_of.get(p, p), []).append(p)
                gruppi = {k: ([k] if k not in v and os.path.exists(k) else []) + v
                          for k, v in sorted(gruppi.items(), key=lambda kv: get_natural_sort_key(kv[0]))
                          if not parole or any(trovato(p) for p in [k] + v)}   # tutto il gruppo se uno combacia
                paths = [p for v in gruppi.values() for p in v]
        elif parole and self.folder == self.root and self.root:   # dalla radice: tutta la libreria
            noti = [p for p in self.results if in_libreria(p, self.root)]
            paths = sorted(noti or list_comics(self.root, True), key=get_natural_sort_key)
        else:
            paths = list_comics(self.folder, self.chk_sub.isChecked()) if self.folder else []
        if parole and not gruppi:
            paths = [p for p in paths if trovato(p)]
        if not force and self.results:
            QTimer.singleShot(0, self.scan)           # dopo un lavoro: stati aggiornati (rilegge solo i cambiati)
        if paths == self.paths and not force:
            return
        self.paths = paths
        self._queue.clear()
        self.list.clear()
        sfondo = {p: n % 2 for n, v in enumerate(gruppi.values()) for p in v}   # gruppi a colori alterni
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            if sfondo.get(p):
                item.setBackground(QBrush(QColor("#263238")))
            item.setData(Qt.ItemDataRole.UserRole, p)
            testo, colore = STATI.get(self.results.get(p), ("", None))
            if p in self.dupe_of:
                testo += f" di «{os.path.basename(self.dupe_of[p])}»"
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

    def scan(self, always_ask=False, completo=False):
        roots = librerie()
        if not roots or self.scanner:
            return
        workers.load_index()
        if completo and QMessageBox.question(
                self, "Controllo completo",
                "Il controllo completo legge ogni pagina di ogni fumetto, per trovare anche quelle "
                "rovinate.<br><br><b>Con migliaia di fumetti può durare molte ore.</b> Intanto puoi usare "
                "il programma, e fermarlo quando vuoi con «Ferma controllo»: la volta dopo riprende da dove "
                "era arrivato.<br><br>Avvio il controllo completo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.scanned_roots = roots
        self.scanner = LibraryScanWorker(roots, completo)
        self.scanner.progress.connect(lambda v, t: self.lbl_scan.setText(f"Controllo: {v}/{t}"))
        self.scanner.finished.connect(lambda res, fresh: self._scanned(res, fresh, always_ask))
        self.scanner.cancelled.connect(self._scan_ended)
        self.b_stop.show()
        self.lbl_scan.setText("Controllo completo…" if completo else "Controllo…")
        self.scanner.start()

    def _stop_scan(self):
        self.lbl_scan.setText("Fermo il controllo…")
        self.scanner.abort()

    def _scan_ended(self):
        self.scanner = None
        self.lbl_scan.setText("")
        self.b_stop.hide()

    def _scanned(self, results, fresh, always_ask):
        self.dupe_of = self.scanner.dupe_of
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
        righe = []
        for root in self.scanned_roots or [self.root]:
            n = [sum(1 for p in gruppo if in_libreria(p, root)) for gruppo in (dupes, broken, convert)]
            if any(n):
                righe.append(f"<b>{info_libreria(root)['nome']}</b>: {n[0]} doppioni, {n[1]} danneggiati, "
                             f"{n[2]} da convertire in WebP")
        box = QMessageBox(self)
        box.setWindowTitle("Libreria")
        box.setText(f"<b>Controllo delle librerie: {len(self.results)} fumetti</b><br><br>" + "<br>".join(righe))
        b_show = box.addButton("Mostra", QMessageBox.ButtonRole.AcceptRole)
        b_conv = box.addButton(f"Converti in WebP ({len(convert)})", QMessageBox.ButtonRole.ActionRole) if convert else None
        b_dup = box.addButton(f"Cestina doppioni ({len(dupes)})", QMessageBox.ButtonRole.ActionRole) if dupes else None
        box.addButton("Più tardi", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_show:
            self.win.show_view(self)
            problemi = dupes + broken + convert
            if not any(in_libreria(p, self.root) for p in problemi):   # apre la libreria con i problemi
                self.scelta.setCurrentIndex(max(0, self.scelta.findData(
                    next(r for r in librerie() if any(in_libreria(p, r) for p in problemi)))))
            self.filtro.setCurrentIndex(next(i for i, (_t, st) in enumerate(FILTRI)
                                             if st and any(self.results[p] in st for p in problemi
                                                           if in_libreria(p, self.root))))
        elif clicked is b_conv and self.win._free():
            self.win.process_paths(convert, True)
        elif clicked is b_dup:
            self.cestina_doppioni(dupes)

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

    def _selezione_cambiata(self):
        n = len(self.list.selectedItems())
        self.pulsanti["AZIONI"].setText(f"AZIONI ({n})" if n else "AZIONI")   # la freccia la mette Qt (menu)
        self.pulsanti["SELEZIONA TUTTO"].setText("DESELEZIONA TUTTO" if n else "SELEZIONA TUTTO")

    def toggle_all(self):
        self.list.clearSelection() if self.list.selectedItems() else self.list.selectAll()

    def _riempi_azioni(self, menu):
        """Voci di AZIONI ▾: sui selezionati, o su tutti i fumetti mostrati."""
        paths = self.selected() or list(self.paths)
        for testo, webp in (("Ripara", False), ("Converti in WebP", True)):
            menu.addAction(f"{testo} ({len(paths)})",
                           lambda w=webp: self.win._free() and self.win.process_paths(paths, w)).setEnabled(bool(paths))
        doppi = [p for p in paths if self.results.get(p) == 4]
        if doppi:
            menu.addSeparator()
            menu.addAction(f"Cestina doppioni ({len(doppi)})", lambda: self.cestina_doppioni(doppi))

    def cestina_doppioni(self, doppi):
        if self.win._free() and QMessageBox.question(
                self, "Cestina doppioni", f"Spostare nel cestino {len(doppi)} doppioni?\n"
                "Di ogni gruppo resta la copia con le info (ComicInfo), poi quella col nome più corto."
                ) == QMessageBox.StandardButton.Yes:
            self.win.trash_files(doppi)

    def reorder(self, sel=None):
        """Sposta i fumetti (i selezionati della Libreria, o quelli della lista di lavoro) nelle cartelle
        dello schema dentro la libreria, con conferma; si annulla dalla Cronologia."""
        sel = sel or self.selected()
        if not sel or not self.root or not self.win._free():
            return
        piano, senza_info = piano_spostamenti(self.root, self.schema(), sel)
        if piano and ConfermaRinomina(piano, self, "Riordina dalle info", f"Spostare {len(piano)} fumetti?",
                                      "Sposta").exec():
            self.win._do_renames(piano, history.new_batch())
            self.win._refresh_undo()
        self._avvisa_senza_info(senza_info, "" if piano else "Niente da spostare.")

    def auto_move(self, paths):
        """A fine lavoro: i CBZ sistemati fuori dalle librerie finiscono in quella aperta, nelle cartelle
        del suo schema."""
        if not (self.root and opzione("libreria/auto", False)):
            return
        fuori = [p for p in paths if os.path.exists(p)
                 and not any(in_libreria(p, r) for r in librerie() + [self.root])]
        piano, senza_info = piano_spostamenti(self.root, self.schema(), fuori)
        if piano:
            log.info(f"Libreria: {len(piano)} fumetti spostati nella libreria")
            self.win._do_renames(piano, history.new_batch())
            self.win._refresh_undo()
        self._avvisa_senza_info(senza_info)

    def _avvisa_senza_info(self, senza_info, altrimenti=""):
        if senza_info:
            nomi = "\n".join(os.path.basename(p) for p in senza_info[:8])
            QMessageBox.information(self, "Libreria", f"{len(senza_info)} fumetti non hanno le info dello schema "
                                    f"«{self.schema()}» e restano dove sono:\n{nomi}")
        elif altrimenti:
            QMessageBox.information(self, "Libreria", altrimenti)

    def trash(self):
        sel = self.selected()
        if sel and self.win._free() and QMessageBox.question(
                self, "Cestina", f"Spostare {len(sel)} file nel cestino?") == QMessageBox.StandardButton.Yes:
            self.win.trash_files(sel)

    def list_menu(self):
        """Le azioni possibili sulla selezione (tasto destro sulla griglia)."""
        sel = self.selected()
        menu = QMenu(self)
        if sel:
            if len(sel) == 1:
                menu.addAction("Pagine", self.open_pages)
            menu.addAction("Info e rinomina", self.rename)
            self._riempi_azioni(menu)
            menu.addSeparator()
            if len(sel) > 1:
                menu.addAction("Unisci", lambda: self.win.merge_paths(sel))
            menu.addAction("Ordina in cartelle", self.reorder)
            menu.addSeparator()
            menu.addAction("Cestina", self.trash)
            menu.addAction("Apri la cartella del fumetto", lambda: apri_cartella(os.path.dirname(sel[0])))
        if self.win.cards:
            menu.addAction("Torna alla lista di lavoro", lambda: self.win.show_view(self.win.work_tab))
        return menu

    def _list_menu(self, pos):
        menu = self.list_menu()
        if not menu.isEmpty():
            menu.exec(self.list.viewport().mapToGlobal(pos))

    def _tree_menu(self, pos):
        index = self.tree.indexAt(pos)
        folder = self.model.filePath(index) if index.isValid() else self.root
        if not folder:
            return
        menu = QMenu(self)
        menu.addAction("Apri nel gestore file", lambda: apri_cartella(folder))
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
