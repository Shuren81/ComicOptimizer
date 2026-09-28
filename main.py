#!/usr/bin/env python3

import sys
import os
import shutil
import tempfile
import subprocess
import zipfile
import re
import random
import logging
import threading
import time
import multiprocessing
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QPushButton, QLabel, QFileDialog, QHBoxLayout,
                             QScrollArea, QGridLayout, QFrame, QDialog,
                             QStackedWidget, QSpinBox, QMessageBox, QProgressBar,
                             QCheckBox, QSystemTrayIcon, QStyle)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QWaitCondition, QMutex, QMutexLocker
from PyQt6.QtGui import QPixmap, QColor, QPalette, QIcon

# --- VERSIONE (unica fonte: usata da titolo, popup e log) ---
APP_VERSION = "2.6.0"

# --- COSTANTI ELABORAZIONE ---
WEBP_QUALITY  = 85       # qualità WebP (0-100)
WEBP_MAX_SIDE = 16383    # limite del formato WebP per lato
PDF_ZOOM      = 2.0      # zoom per le pagine PDF che vanno renderizzate (~144 dpi)
TMP_PREFIX    = "comicopt_"   # prefisso cartelle temporanee (per la pulizia)
APP_ICON_PATH = ""       # impostato all'avvio, usato dalle notifiche di sistema

# --- PERCORSI ---
IS_FROZEN = getattr(sys, "frozen", False)          # True dentro l'eseguibile (PyInstaller)
IS_WIN    = sys.platform == "win32"
# Cartella delle risorse incluse (icona, 7z.exe): _MEIPASS nell'exe, altrimenti accanto allo script
RES_DIR   = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

def _log_file_path():
    """
    Su Windows e nell'eseguibile il log va in %LOCALAPPDATA%\\ComicOptimizer:
    la cartella corrente potrebbe essere Program Files (non scrivibile).
    Da sorgente su Linux resta accanto a dove si lancia lo script, come prima.
    """
    if IS_WIN or IS_FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "ComicOptimizer")
        try:
            os.makedirs(folder, exist_ok=True)
            return os.path.join(folder, "comicoptimizer.log")
        except OSError:
            pass
    return "comicoptimizer.log"

LOG_PATH = _log_file_path()

# --- LOGGING ---
_log_handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
if sys.stderr:   # nell'exe senza console sys.stderr è None
    _log_handlers.insert(0, logging.StreamHandler())
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger("ComicOptimizer")
# Le librerie esterne scrivono nel log solo avvisi ed errori, non i loro messaggi di debug
for _lib in ("PIL", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

# Handler che emette ogni riga di log come segnale Qt (per la finestra di log in-app)
from PyQt6.QtCore import QObject, pyqtSignal as _pyqtSignal

class _LogEmitter(QObject):
    new_record = _pyqtSignal(str)

class _QtLogHandler(logging.Handler):
    # Il segnale Qt sta in un QObject separato: così l'handler resta un oggetto
    # Python puro e logging.shutdown() alla chiusura non va in errore.
    def __init__(self):
        logging.Handler.__init__(self)
        self._emitter  = _LogEmitter()
        self.new_record = self._emitter.new_record
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.new_record.emit(msg)
        except Exception:
            pass

_qt_log_handler = _QtLogHandler()
log.addHandler(_qt_log_handler)
# NON aggiungere al root logger: causerebbe duplicati perché log è già figlio di root


class LogWindow(QDialog):
    """Finestra di log in-app, aperta con il tasto L o dal footer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log operazioni")
        fit_dialog_to_screen(self, 900, 500, min_w=500, min_h=320)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Barra superiore: filtro + pulsanti
        top = QHBoxLayout()
        from PyQt6.QtWidgets import QComboBox, QLineEdit
        self._level_box = QComboBox()
        self._level_box.addItems(["TUTTI", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self._level_box.setFixedWidth(110)
        self._level_box.currentTextChanged.connect(self._apply_filter)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Cerca nel log...")
        self._search.textChanged.connect(self._apply_filter)

        btn_clear = QPushButton("Pulisci")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._clear)

        btn_save = QPushButton("Salva su file")
        btn_save.setFixedWidth(110)
        btn_save.clicked.connect(self._save)

        top.addWidget(QLabel("Livello:"))
        top.addWidget(self._level_box)
        top.addSpacing(10)
        top.addWidget(QLabel("Filtro:"))
        top.addWidget(self._search, 1)
        top.addSpacing(10)
        top.addWidget(btn_clear)
        top.addWidget(btn_save)
        layout.addLayout(top)

        from PyQt6.QtWidgets import QPlainTextEdit
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            "QPlainTextEdit { background: #0d0d0d; color: #e0e0e0; "
            "font-family: monospace; font-size: 11px; border: 1px solid #333; }"
        )
        layout.addWidget(self._text)

        self._all_lines = []   # tutte le righe, per il filtro
        _qt_log_handler.new_record.connect(self._append_line)

    def _append_line(self, msg):
        self._all_lines.append(msg)
        if self._matches(msg):
            self._write(msg)

    def _matches(self, msg):
        level_filter = self._level_box.currentText()
        search_text  = self._search.text().lower()
        if level_filter != "TUTTI" and f"[{level_filter}]" not in msg:
            return False
        if search_text and search_text not in msg.lower():
            return False
        return True

    def _write(self, msg):
        # Colora le righe per livello
        if "[ERROR]" in msg or "[CRITICAL]" in msg:
            color = "#ff6b6b"
        elif "[WARNING]" in msg:
            color = "#ffd93d"
        elif "[DEBUG]" in msg:
            color = "#888"
        else:
            color = "#e0e0e0"
        self._text.appendHtml(
            f'<span style="color:{color}; white-space:pre;">{msg.replace("&","&amp;").replace("<","&lt;")}</span>'
        )
        # Auto-scroll in fondo
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _apply_filter(self):
        self._text.clear()
        for line in self._all_lines:
            if self._matches(line):
                self._write(line)

    def _clear(self):
        self._all_lines.clear()
        self._text.clear()

    def _save(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Salva log", "comicoptimizer.log", "Log (*.log *.txt)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(self._all_lines))
                log.info(f"Log salvato su '{path}'")
            except Exception as e:
                log.error(f"Impossibile salvare il log: {e}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

# --- IMPORT PDF (opzionale) ---
# "fitz" è deprecato nelle versioni recenti di PyMuPDF: si usa "pymupdf"
# e si ripiega su "fitz" solo per le versioni vecchie.
try:
    import pymupdf as fitz
    HAS_PDF = True
except ImportError:
    try:
        import fitz
        HAS_PDF = True
    except ImportError:
        HAS_PDF = False

# --- TRASH HELPER (cross-platform) FIX #2 ---
def _trash_file_cross_platform(path):
    """
    Sposta il file nel cestino in modo cross-platform.
    Prova send2trash se disponibile, altrimenti fallback per piattaforma.
    """
    try:
        import send2trash
        send2trash.send2trash(path)
        return True
    except ImportError:
        pass
    except Exception as e:
        # Prima un errore qui mandava in crash l'app (eccezione non gestita in uno slot Qt)
        log.warning(f"send2trash non riuscito su '{path}': {e} — provo il metodo di sistema")
    if sys.platform.startswith("linux"):
        try:
            res = subprocess.run(['gio', 'trash', path], capture_output=True, timeout=10)
            if res.returncode == 0:
                return True
            res2 = subprocess.run(['trash-put', path], capture_output=True, timeout=10)
            return res2.returncode == 0
        except Exception as e:
            log.error(f"Impossibile cestinare '{path}': {e}")
            return False
    elif sys.platform == "darwin":
        try:
            script = f'tell application "Finder" to delete POSIX file "{path}"'
            res = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=10)
            return res.returncode == 0
        except Exception as e:
            log.error(f"Impossibile cestinare '{path}': {e}")
            return False
    elif sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class SHFILEOPSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hwnd",                  wintypes.HWND),
                    ("wFunc",                 wintypes.UINT),
                    ("pFrom",                 wintypes.LPCWSTR),
                    ("pTo",                   wintypes.LPCWSTR),
                    ("fFlags",                wintypes.WORD),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings",         wintypes.LPVOID),
                    ("lpszProgressTitle",     wintypes.LPCWSTR),
                ]
            op = SHFILEOPSTRUCT()
            op.wFunc = 3        # FO_DELETE
            op.pFrom = path + "\0"
            op.fFlags = 0x0040  # FOF_ALLOWUNDO
            return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
        except Exception as e:
            log.error(f"Impossibile cestinare '{path}': {e}")
            return False
    return False

# --- PROGRAMMI ESTERNI (7z, unrar) ---

_TOOL_CACHE = {}

def find_tool(name):
    """
    Trova 7z/unrar: prima quello incluso nell'exe (cartella bin), poi il PATH,
    poi (su Windows) le cartelle di installazione standard. None se assente.
    """
    if name in _TOOL_CACHE:
        return _TOOL_CACHE[name]
    exe = name + (".exe" if IS_WIN else "")
    candidates = [os.path.join(RES_DIR, "bin", exe)]
    found = shutil.which(name)
    if found:
        candidates.append(found)
    if IS_WIN:
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                candidates.append(os.path.join(base, "7-Zip" if name == "7z" else "WinRAR",
                                               "7z.exe" if name == "7z" else "UnRAR.exe"))
    path = next((c for c in candidates if c and os.path.isfile(c)), None)
    _TOOL_CACHE[name] = path
    return path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def run_tool(cmd, **kw):
    """
    Come subprocess.run, ma cmd[0] ('7z' o 'unrar') viene risolto con find_tool
    e su Windows non si apre nessuna finestra di console.
    Solleva FileNotFoundError se il programma non c'è (gestito dai chiamanti).
    """
    exe = find_tool(cmd[0])
    if not exe:
        raise FileNotFoundError(cmd[0])
    args = list(cmd[1:])
    if IS_WIN and cmd[0] == "7z" and args and args[0] == "l":
        args.insert(1, "-sccUTF-8")   # nomi con accenti corretti nell'elenco
    if IS_WIN:
        kw.setdefault("creationflags", _NO_WINDOW)
    return subprocess.run([exe] + args, **kw)

# --- UTILITY ---

# Estensioni delle pagine: UNA sola lista usata ovunque (prima erano due liste
# diverse e le GIF/BMP/TIFF venivano impacchettate ma non contate).
_PAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif')

def get_natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def is_junk_file(path):
    name = os.path.basename(path)
    return name.startswith("._") or name.lower() == ".ds_store" or "__macosx" in path.lower()

def is_page_file(name):
    return name.lower().endswith(_PAGE_EXTS) and not is_junk_file(name)

def is_comicinfo(name):
    return os.path.basename(name).lower() == "comicinfo.xml"

def make_temp_dir():
    return tempfile.mkdtemp(prefix=TMP_PREFIX)

def cleanup_stale_temp(max_age_hours=6):
    """Rimuove le cartelle temporanee rimaste da sessioni chiuse male."""
    base = tempfile.gettempdir()
    limit = time.time() - max_age_hours * 3600
    removed = 0
    try:
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if name.startswith(TMP_PREFIX) and os.path.isdir(full):
                try:
                    if os.path.getmtime(full) < limit:
                        shutil.rmtree(full, ignore_errors=True)
                        removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    if removed:
        log.info(f"Pulizia avvio: rimosse {removed} cartelle temporanee orfane.")

def list_page_files(folder):
    """Tutte le pagine (immagini) sotto `folder`, in ordine naturale."""
    pages = [
        os.path.join(r, f)
        for r, _, fs in os.walk(folder)
        for f in fs
        if is_page_file(os.path.join(r, f))
    ]
    pages.sort(key=get_natural_sort_key)
    return pages

def find_comicinfo(folder):
    """Cerca ComicInfo.xml (qualsiasi maiuscolo/minuscolo) nella cartella estratta."""
    for r, _, fs in os.walk(folder):
        for f in fs:
            if is_comicinfo(f) and not is_junk_file(os.path.join(r, f)):
                return os.path.join(r, f)
    return None

def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024

def fmt_duration(sec):
    sec = int(sec)
    if sec < 60:
        return f"{sec} s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"

# FIX #6: parsing 7z con formato stabile (-slt) invece di offset fisso line[53:]
# --- RILEVAMENTO FORMATO REALE (magic bytes) ---

# Firme dei formati archivio (primi byte del file)
_MAGIC = {
    b'Rar!\x1a\x07':   'rar',   # RAR (v1.5+)
    b'Rar!\x1a\x07\x01': 'rar', # RAR5
    b'PK\x03\x04':     'zip',   # ZIP / CBZ
    b'PK\x05\x06':     'zip',   # ZIP vuoto
    b'PK\x07\x08':     'zip',   # ZIP multi-volume
    b'\x25\x50\x44\x46': 'pdf', # PDF (%PDF)
    b'7z\xbc\xaf\x27\x1c': '7z',
}

def detect_real_format(path):
    """
    Legge i primi 8 byte del file e restituisce il formato reale:
    'rar', 'zip', 'pdf', '7z' oppure None se sconosciuto.
    Non si fida dell'estensione.
    """
    try:
        with open(path, 'rb') as f:
            header = f.read(8)
        for sig, fmt in _MAGIC.items():
            if header[:len(sig)] == sig:
                return fmt
    except Exception as e:
        log.debug(f"detect_real_format: impossibile leggere '{path}': {e}")
    return None

def _format_mismatch_log(path, declared_ext, real_fmt):
    """Logga un avviso quando estensione e formato reale non coincidono."""
    log.warning(
        f"Estensione/formato non coincidono: '{os.path.basename(path)}' "
        f"ha estensione '{declared_ext}' ma è un file {real_fmt.upper()}"
    )

def _parse_7z_entries(path):
    """
    Usa '7z l -ba -slt' (output strutturato) e restituisce [(nome, dimensione)]
    delle sole pagine.
    """
    entries = []
    try:
        res = run_tool(
            ['7z', 'l', '-ba', '-slt', path],
            capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace'
        )
        if res.returncode != 0:
            return entries
        name, size = None, 0
        for line in res.stdout.splitlines() + [""]:
            line = line.strip()
            low = line.lower()
            if low.startswith("path = "):
                if name is not None and is_page_file(name):
                    entries.append((name, size))
                name, size = line[7:].strip(), 0
            elif low.startswith("size = "):
                try:
                    size = int(line[7:].strip())
                except ValueError:
                    size = 0
        if name is not None and is_page_file(name):
            entries.append((name, size))
    except Exception as e:
        log.warning(f"7z list fallito su '{path}': {e}")
    return entries

def _parse_7z_list(path):
    return [n for n, _ in _parse_7z_entries(path)]

def get_archive_signature(path):
    """
    "Impronta" del contenuto: numero di pagine + dimensioni di ogni pagina.
    Due archivi con la stessa impronta contengono (in pratica) le stesse immagini,
    anche se hanno nomi diversi. None per PDF o archivi illeggibili.
    """
    real_fmt = detect_real_format(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf' or real_fmt == 'pdf':
        return None
    sizes = []
    if real_fmt == 'zip' or (real_fmt is None and ext in ('.cbz', '.zip')):
        try:
            with zipfile.ZipFile(path, 'r') as z:
                sizes = [i.file_size for i in z.infolist() if is_page_file(i.filename)]
        except Exception:
            sizes = []
    if not sizes:
        sizes = [s for _, s in _parse_7z_entries(path)]
    if not sizes or all(s == 0 for s in sizes):
        return None
    return (len(sizes), tuple(sorted(sizes)))

def get_archive_file_list(path):
    """
    Elenca le immagini dentro l'archivio usando il formato REALE (magic bytes).
    Gestisce il caso di estensione errata (es. .cbz che è un RAR).
    """
    real_fmt     = detect_real_format(path)
    declared_ext = os.path.splitext(path)[1].lower()

    # PDF
    if declared_ext == '.pdf' or real_fmt == 'pdf':
        if not HAS_PDF:
            return []
        try:
            doc  = fitz.open(path)
            imgs = [f"p{i:04d}" for i in range(len(doc))]
            doc.close()
            return imgs
        except Exception as e:
            log.warning(f"Errore apertura PDF '{path}': {e}")
            return []

    # Formato effettivo: usa il reale se disponibile, altrimenti l'estensione
    effective_fmt = real_fmt or ('zip' if declared_ext in ('.cbz', '.zip') else 'rar')

    if effective_fmt == 'zip':
        # ZIP: listing nativo Python
        try:
            with zipfile.ZipFile(path, 'r') as z:
                imgs = [n for n in z.namelist() if is_page_file(n)]
            imgs.sort(key=get_natural_sort_key)
            return imgs
        except zipfile.BadZipFile:
            # Potrebbe essere un RAR con estensione sbagliata
            log.warning(f"get_archive_file_list: '{os.path.basename(path)}' non è un ZIP, "
                        f"provo unrar/7z (real_fmt={real_fmt})")
            # Ricade nel ramo RAR sotto
            effective_fmt = 'rar'

    if effective_fmt in ('rar', '7z'):
        imgs = []
        # Prova unrar lb
        try:
            res = run_tool(['unrar', 'lb', path],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                imgs = [f.strip() for f in res.stdout.splitlines() if is_page_file(f.strip())]
        except Exception as e:
            log.debug(f"unrar lb fallito su '{path}': {e}")
        # Fallback 7z
        if not imgs:
            imgs = _parse_7z_list(path)
        imgs.sort(key=get_natural_sort_key)
        return imgs

    # Formato sconosciuto: prova entrambi
    imgs = []
    try:
        res = run_tool(['unrar', 'lb', path],
                             capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            imgs = [f.strip() for f in res.stdout.splitlines() if is_page_file(f.strip())]
    except Exception:
        pass
    if not imgs:
        imgs = _parse_7z_list(path)
    imgs.sort(key=get_natural_sort_key)
    return imgs

def check_integrity(path):
    """
    Verifica l'integrità dell'archivio usando il formato REALE (magic bytes),
    non l'estensione dichiarata. Questo gestisce correttamente i casi come
    un .cbz che è in realtà un RAR, o un .cbr che è in realtà uno ZIP.
    """
    real_fmt = detect_real_format(path)
    declared_ext = os.path.splitext(path)[1].lower()

    # PDF: verifica presenza di PyMuPDF indipendentemente dall'estensione
    if declared_ext == '.pdf' or real_fmt == 'pdf':
        return HAS_PDF

    # Avvisa se l'estensione non corrisponde al contenuto reale
    if real_fmt:
        declared_is_zip = declared_ext in ('.cbz', '.zip')
        declared_is_rar = declared_ext in ('.cbr', '.rar')
        if (declared_is_zip and real_fmt == 'rar') or \
           (declared_is_rar and real_fmt == 'zip'):
            _format_mismatch_log(path, declared_ext, real_fmt)

    # Sceglie il tool in base al formato REALE, non all'estensione
    effective_fmt = real_fmt or ('zip' if declared_ext in ('.cbz', '.zip') else 'rar')

    if effective_fmt == 'zip':
        try:
            with zipfile.ZipFile(path, 'r') as z:
                bad = z.testzip()
                if bad:
                    log.warning(f"check_integrity: file corrotto '{bad}' in '{path}'")
                return bad is None
        except zipfile.BadZipFile:
            log.warning(f"check_integrity: '{os.path.basename(path)}' non è un ZIP valido "
                        f"(real_fmt={real_fmt})")
            return False
        except Exception as e:
            log.warning(f"check_integrity zip errore '{path}': {e}")
            return False

    if effective_fmt in ('rar', '7z'):
        # Prova unrar t per i RAR
        if effective_fmt == 'rar':
            try:
                res = run_tool(
                    ['unrar', 't', '-y', path],
                    capture_output=True, timeout=60
                )
                if res.returncode == 0:
                    return True
                log.debug(f"unrar t fallito (rc={res.returncode}) su '{path}', provo 7z...")
            except FileNotFoundError:
                log.debug("unrar non trovato, uso 7z per il test di integrità")
            except subprocess.TimeoutExpired:
                log.warning(f"check_integrity unrar timeout su '{path}'")
                return False
            except Exception as e:
                log.debug(f"unrar t eccezione su '{path}': {e}")

        # Fallback / 7z nativo: 7z t
        try:
            res = run_tool(['7z', 't', path], capture_output=True, timeout=60)
            return res.returncode == 0
        except subprocess.TimeoutExpired:
            log.warning(f"check_integrity 7z timeout su '{path}'")
            return False
        except Exception as e:
            log.warning(f"check_integrity 7z errore su '{path}': {e}")
            return False

    # Formato sconosciuto: prova 7z come ultimo tentativo
    log.debug(f"check_integrity: formato sconosciuto per '{path}', provo 7z t")
    try:
        res = run_tool(['7z', 't', path], capture_output=True, timeout=60)
        return res.returncode == 0
    except Exception as e:
        log.warning(f"check_integrity fallback 7z errore '{path}': {e}")
        return False

# --- ESTRAZIONE ARCHIVI ---

def _extract_with_tools(path, dest):
    """Estrae tutto con unrar, e se fallisce con 7z. True se uno dei due riesce."""
    try:
        res = run_tool(['unrar', 'x', '-y', path, dest + os.sep],
                             capture_output=True, timeout=600)
        if res.returncode == 0:
            log.info("  unrar x: OK")
            return True
        log.warning(f"  unrar x: rc={res.returncode}, "
                    f"stderr={res.stderr.decode(errors='replace')[:200]}")
    except FileNotFoundError:
        log.debug("  unrar non trovato, uso 7z x")
    except subprocess.TimeoutExpired:
        log.error(f"  unrar x: TIMEOUT su '{path}'")
    except Exception as e:
        log.warning(f"  unrar x eccezione: {e}")
    try:
        res = run_tool(['7z', 'x', '-y', f'-o{dest}', path],
                             capture_output=True, timeout=600)
        if res.returncode == 0:
            log.info("  7z x: OK")
            return True
        log.error(f"  7z x: rc={res.returncode}, "
                  f"stderr={res.stderr.decode(errors='replace')[:200]}")
    except subprocess.TimeoutExpired:
        log.error(f"  7z x: TIMEOUT su '{path}'")
    except Exception as e:
        log.error(f"  7z x eccezione: {e}")
    return False

def extract_archive(path, dest, progress_cb=None):
    """
    Estrae l'intero archivio (pagine + ComicInfo.xml) in `dest`, usando il
    formato REALE del file. Per i PDF estrae/renderizza le pagine.
    """
    real_fmt = detect_real_format(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf' or real_fmt == 'pdf':
        if not HAS_PDF:
            log.error("  PDF: PyMuPDF non disponibile")
            return False
        return extract_pdf_pages(path, dest, progress_cb) > 0
    if real_fmt and real_fmt != ext.lstrip('.') and not (real_fmt == 'zip' and ext == '.cbz') \
            and not (real_fmt == 'rar' and ext == '.cbr'):
        _format_mismatch_log(path, ext, real_fmt)
    if real_fmt == 'zip' or (real_fmt is None and ext in ('.cbz', '.zip')):
        try:
            with zipfile.ZipFile(path, 'r') as z:
                z.extractall(dest)
            log.info("  ZIP: extractall completato")
            return True
        except zipfile.BadZipFile:
            log.warning(f"  ZIP fallito — il file è {real_fmt or 'sconosciuto'}, provo unrar/7z")
        except Exception as e:
            log.error(f"  ZIP extractall errore: {e}")
    return _extract_with_tools(path, dest)

# --- PDF ---

def _pdf_page_is_single_scan(doc, page):
    """
    True se la pagina è una "scansione": una sola immagine che copre quasi tutta
    la pagina, senza testo visibile né disegni vettoriali sopra (che andrebbero
    persi estraendo solo l'immagine, es. fumetti digitali con lettering vettoriale).
    """
    imgs = page.get_images(full=True)
    if len(imgs) != 1:
        return None
    xref, smask = imgs[0][0], imgs[0][1]
    if smask or page.rotation:
        return None
    try:
        rects = page.get_image_rects(xref)
        if rects:
            r = rects[0]
            page_area = page.rect.width * page.rect.height
            if page_area <= 0 or (r.width * r.height) < 0.85 * page_area:
                return None
    except Exception:
        pass
    # Testo visibile? (type 3 = testo invisibile, tipico dell'OCR: si può ignorare)
    try:
        for span in page.get_texttrace():
            if span.get("type", 0) != 3:
                return None
    except Exception:
        if page.get_text("text").strip():
            return None
    try:
        if page.get_drawings():
            return None
    except Exception:
        pass
    return xref

def _pdf_extract_native(doc, page, base):
    """Estrae l'immagine originale della pagina (qualità piena). True se riesce."""
    xref = _pdf_page_is_single_scan(doc, page)
    if not xref:
        return False
    info = doc.extract_image(xref)
    if not info or not info.get("image"):
        return False
    ext = info.get("ext", "").lower()
    data = info["image"]
    if ext in ("jpeg", "jpg") and info.get("colorspace") != 4:
        with open(base + ".jpg", "wb") as f:
            f.write(data)
        return True
    if ext == "png":
        with open(base + ".png", "wb") as f:
            f.write(data)
        return True
    # JPEG CMYK, JPEG2000, JBIG2, TIFF...: conversione con Pillow
    try:
        import io
        with Image.open(io.BytesIO(data)) as img:
            img = _to_saveable_rgb(img)
            if ext in ("jpeg", "jpg", "jpx"):
                img.save(base + ".jpg", "JPEG", quality=95)
            else:
                img.save(base + ".png", "PNG", optimize=True)
        return True
    except Exception:
        return False

def _pdf_render(page, base):
    """Renderizza la pagina e la salva in JPEG (molto più leggero del vecchio PNG)."""
    pix = page.get_pixmap(matrix=fitz.Matrix(PDF_ZOOM, PDF_ZOOM), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.save(base + ".jpg", "JPEG", quality=92, optimize=True)

def extract_pdf_pages(path, dest, progress_cb=None):
    """
    Estrae le pagine di un PDF in `dest` (0001.jpg, 0002.png, ...).
    Pagine-scansione → immagine originale; altre pagine → render JPEG.
    Restituisce il numero di pagine scritte.
    """
    doc = fitz.open(path)
    n = len(doc)
    native = 0
    try:
        for i in range(n):
            page = doc.load_page(i)
            base = os.path.join(dest, f"{i + 1:04d}")
            try:
                ok = _pdf_extract_native(doc, page, base)
            except Exception as e:
                log.debug(f"  PDF pag. {i + 1}: estrazione nativa fallita ({e}), render")
                ok = False
            if ok:
                native += 1
            else:
                _pdf_render(page, base)
            if progress_cb:
                progress_cb(i + 1, n)
    finally:
        doc.close()
    log.info(f"  PDF: {native}/{n} pagine estratte in qualità originale, "
             f"{n - native} renderizzate")
    return n

# --- ELABORAZIONE PAGINE (eseguita in processi separati, su più core) ---

def _to_saveable_rgb(img):
    """Porta qualsiasi modalità (CMYK, 16 bit, palette, alpha...) in RGB/L a 8 bit."""
    mode = img.mode
    if mode in ("RGB", "L"):
        return img
    if mode == "1":
        return img.convert("L")
    if mode.startswith("I;16") or mode in ("I", "F"):
        # 16/32 bit: riscala a 8 bit invece di "tagliare" (altrimenti pagina bianca)
        img = img.convert("I") if mode != "F" else img
        hi = img.getextrema()[1] or 1
        # 16 bit → dividi per 256; valori già a 8 bit restano uguali
        scale = 1.0 if hi <= 255 else (1 / 256 if hi <= 65535 else 255.0 / hi)
        return img.point(lambda v: v * scale).convert("L")
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")   # CMYK, YCbCr, LAB, P, ...

def _prepare_page(job):
    """
    job = (sorgente, destinazione_senza_estensione, to_webp, qualità)
    Restituisce (file_scritto, nota). La nota spiega perché una pagina è stata
    lasciata nel formato originale (None se tutto normale).
    Una pagina problematica NON fa più fallire l'intero fumetto.
    """
    src, dst_base, to_webp, quality = job
    src_ext = os.path.splitext(src)[1].lower() or ".jpg"
    keep = dst_base + src_ext

    if not to_webp:
        shutil.copy2(src, keep)
        return keep, None
    if src_ext == ".webp":
        shutil.copy2(src, keep)            # già WebP: niente ricompressione
        return keep, None

    dst = dst_base + ".webp"
    try:
        with Image.open(src) as img:
            if max(img.size) > WEBP_MAX_SIDE:
                shutil.copy2(src, keep)
                return keep, "troppo grande per WebP"
            img.load()
            rgb = _to_saveable_rgb(img)
            rgb.save(dst, "WEBP", quality=quality, method=4)
        if os.path.getsize(dst) >= os.path.getsize(src):
            os.remove(dst)
            shutil.copy2(src, keep)
            return keep, "WebP più pesante dell'originale"
        return dst, None
    except Exception as e:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        shutil.copy2(src, keep)
        return keep, f"conversione fallita ({e})"

# --- COMICINFO / STATO CBZ ---

CBZ_MARK = f"ComicOptimizer {APP_VERSION}"

def build_comicinfo(path, page_count, edited=False):
    """
    Restituisce i byte di ComicInfo.xml da inserire nel nuovo CBZ.
    Se il numero di pagine è cambiato (o le pagine sono state riordinate
    nell'editor) aggiorna <PageCount> e rimuove <Pages>, che non sarebbe più valido.
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        root = ET.fromstring(raw)
        pc = root.find("PageCount")
        pages = root.find("Pages")
        pc_wrong = pc is not None and (pc.text or "").strip() != str(page_count)
        pages_wrong = pages is not None and (edited or len(pages) != page_count)
        if not pc_wrong and not pages_wrong:
            return raw
        if pc_wrong:
            pc.text = str(page_count)
        if pages_wrong:
            root.remove(pages)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except Exception as e:
        log.warning(f"  ComicInfo.xml non analizzabile ({e}): copiato così com'è")
        return raw

def cbz_status(path):
    """3 = convertito in WebP, 1 = CBZ valido. Solleva eccezione se non è uno ZIP."""
    with zipfile.ZipFile(path, 'r') as z:
        comment = z.comment or b""
        if comment.startswith(b"ComicOptimizer") and b"webp" in comment:
            return 3
        imgs = [n for n in z.namelist() if is_page_file(n)]
        return 3 if imgs and all(n.lower().endswith('.webp') for n in imgs) else 1

def verify_cbz(path, expected_pages):
    """Controlla il CBZ appena creato PRIMA di toccare l'originale."""
    with zipfile.ZipFile(path, 'r') as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"archivio creato corrotto ('{bad}')")
        n = sum(1 for name in z.namelist() if is_page_file(name))
    if n != expected_pages:
        raise RuntimeError(f"il nuovo archivio ha {n} pagine invece di {expected_pages}")

# --- ADATTAMENTO ALLO SCHERMO ---

def fit_dialog_to_screen(dialog, want_w, want_h, min_w=520, min_h=380, margin=60):
    """
    Apre `dialog` con la dimensione desiderata (want_w x want_h), ma senza mai
    superare lo schermo disponibile (barra delle applicazioni esclusa). Se lo
    schermo è più piccolo, la finestra si apre più piccola: il contenuto che
    non ci sta è già dentro una QScrollArea, quindi resta raggiungibile con lo
    scorrimento invece di finire fuori dalla parte visibile. `min_w`/`min_h`
    sono un limite minimo di comodità, MAI più grande dello schermo stesso.
    """
    screen = QApplication.primaryScreen().availableGeometry()
    avail_w, avail_h = max(screen.width() - margin, 200), max(screen.height() - margin, 150)
    w, h = min(want_w, avail_w), min(want_h, avail_h)
    dialog.resize(w, h)
    dialog.setMinimumSize(min(min_w, avail_w), min(min_h, avail_h))

# --- COMPONENTS ---

class StopDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Interruzione")
        self.setFixedSize(450, 180)
        l = QVBoxLayout(self)
        lbl = QLabel("<b>Cosa desideri fare?</b>")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        btns = QHBoxLayout()
        b1 = QPushButton("Annulla Subito")
        b1.setStyleSheet("background: #b71c1c; color: white;")
        b1.clicked.connect(lambda: self.done(1))
        b2 = QPushButton("Termina in corso")
        b2.setStyleSheet("background: #e65100; color: white;")
        b2.clicked.connect(lambda: self.done(2))
        b3 = QPushButton("Prosegui")
        b3.setStyleSheet("background: #444; color: white;")
        b3.clicked.connect(lambda: self.done(0))
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addWidget(b3)
        l.addLayout(btns)

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")

    def wheelEvent(self, e):
        e.ignore()

# --- WORKERS ---

_ARCHIVE_EXTS = ('.cbz', '.cbr', '.zip', '.rar', '.pdf')
_IMAGE_EXTS   = _PAGE_EXTS

class ImportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)

    def __init__(self, raw_paths):
        super().__init__()
        self.raw_paths = raw_paths

    def run(self):
        valid        = []
        all_to_check = []
        for p in self.raw_paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    for f in fs:
                        if f.lower().endswith(_ARCHIVE_EXTS):
                            all_to_check.append(os.path.join(r, f))
            elif p.lower().endswith(_ARCHIVE_EXTS):
                all_to_check.append(p)
        total = len(all_to_check)
        for i, p in enumerate(all_to_check):
            flist = get_archive_file_list(p)
            if flist:
                valid.append((p, len(flist)))
            self.progress.emit(i + 1, total)
        valid.sort(key=lambda x: get_natural_sort_key(x[0]))
        self.finished.emit(valid)

class AnalysisWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict, int)

    def __init__(self, cards_paths):
        super().__init__()
        self.paths = cards_paths

    def run(self):
        results = {}
        groups  = {}     # stesso nome (es. fumetto.cbr + fumetto.cbz)
        by_sig  = {}     # stesso contenuto (pagine identiche) anche con nomi diversi
        total   = len(self.paths)
        for i, p in enumerate(self.paths):
            is_ok = check_integrity(p)
            if not is_ok:
                results[p] = 5
            else:
                target = os.path.splitext(p)[0] + ".cbz"
                groups.setdefault(target, []).append(p)
                sig = get_archive_signature(p)
                if sig:
                    by_sig.setdefault(sig, []).append(p)
            self.progress.emit(i + 1, total)

        def keep_first(x):
            # Tiene preferibilmente il .cbz che è davvero uno ZIP, poi l'ordine naturale
            # poi il nome più corto (le copie di solito sono "… (1)", "… - Copia")
            good_cbz = x.lower().endswith('.cbz') and detect_real_format(x) == 'zip'
            return (0 if good_cbz else 1, len(os.path.basename(x)), get_natural_sort_key(x))

        dupes_count = 0
        for ps in list(groups.values()) + list(by_sig.values()):
            if len(ps) > 1:
                ps = sorted(ps, key=keep_first)
                for loser in ps[1:]:
                    if loser not in results:
                        results[loser] = 4
                        dupes_count += 1
                        log.debug(f"  Duplicato: '{os.path.basename(loser)}' "
                                  f"= '{os.path.basename(ps[0])}'")

        # Assegna status a TUTTI i file integri usando il formato REALE
        for p in self.paths:
            if p not in results:
                real_fmt     = detect_real_format(p)
                declared_ext = os.path.splitext(p)[1].lower()
                if declared_ext == '.pdf' or real_fmt == 'pdf':
                    results[p] = 0   # PDF: da convertire
                elif real_fmt == 'rar' or (real_fmt is None and declared_ext in ('.cbr', '.rar')):
                    results[p] = 0   # RAR reale: da convertire in CBZ
                elif real_fmt == 'rar' and declared_ext in ('.cbz', '.zip'):
                    # CBZ che è in realtà un RAR → da sistemare
                    results[p] = 0
                elif real_fmt == 'zip' or (real_fmt is None and declared_ext in ('.cbz', '.zip')):
                    try:
                        results[p] = cbz_status(p)   # 3 = CONVERTITO, 1 = OK
                    except Exception:
                        results[p] = 0
                else:
                    results[p] = 1

        self.finished.emit(results, dupes_count)

class ProcessingWorker(QThread):
    """
    Crea i nuovi CBZ. Sequenza sicura per ogni fumetto:
      1. pagine preparate in una cartella temporanea (WebP su più core)
      2. CBZ scritto come .tmp e VERIFICATO (integrità + numero di pagine)
      3. solo dopo: vecchio file nel cestino e .tmp rinominato nel file finale
    Le cartelle temporanee di TUTTI i task vengono eliminate anche in caso
    di interruzione o errore.
    """
    progress_val   = pyqtSignal(int)
    progress_max   = pyqtSignal(int)
    status_msg     = pyqtSignal(str)
    ask_permission = pyqtSignal(str, str, int, int)
    file_finished  = pyqtSignal(str, str, int)
    job_done       = pyqtSignal(dict)   # riepilogo (non si chiama "finished" per non
                                        # nascondere il segnale nativo di QThread)

    def __init__(self, tasks, to_webp=False):
        super().__init__()
        self.tasks   = tasks            # lista di dict: src, images, tmp, comicinfo, edited
        self.to_webp = to_webp
        self._is_running = True
        self._stop_after_current = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._permission_result = None

    def set_permission(self, res):
        with QMutexLocker(self._mutex):
            self._permission_result = res
            self._condition.wakeAll()

    def abort_now(self):
        self._is_running = False
        # sblocca un'eventuale attesa della scelta sul conflitto
        self.set_permission('skip')

    def stop_later(self):
        self._stop_after_current = True

    def run(self):
        summary = {
            'mode': 'webp' if self.to_webp else 'repair',
            'total': len(self.tasks), 'done': 0, 'skipped': 0,
            'errors': [], 'pages_kept': 0,
            'size_before': 0, 'size_after': 0,
            'aborted': False, 'start': time.time(),
        }
        pool = None
        try:
            if self.to_webp:
                workers = max(1, (os.cpu_count() or 2) - 1)   # un core libero per l'interfaccia
                pool = ProcessPoolExecutor(max_workers=workers,
                                           mp_context=multiprocessing.get_context("spawn"))
                log.info(f"Conversione WebP su {workers} processi paralleli")
            self._run_tasks(pool, summary)
        except Exception as e:
            log.error(f"ProcessingWorker: errore imprevisto: {e}", exc_info=True)
            summary['errors'].append(("(generale)", str(e)))
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
            for task in self.tasks:
                tmp = task.get('tmp')
                if tmp and os.path.exists(tmp):
                    shutil.rmtree(tmp, ignore_errors=True)
            summary['elapsed'] = time.time() - summary['start']
            log.info(f"ProcessingWorker completato: {summary['done']} ok, "
                     f"{summary['skipped']} saltati, {len(summary['errors'])} errori"
                     f"{' (INTERROTTO)' if summary['aborted'] else ''}.")
            self.job_done.emit(summary)

    def _run_tasks(self, pool, summary):
        processed = set()
        total_p = sum(len(t['images']) for t in self.tasks)
        self.progress_max.emit(total_p)
        curr_p = 0
        log.info(f"ProcessingWorker avviato: {len(self.tasks)} file, "
                 f"{total_p} immagini totali, webp={self.to_webp}")

        for task in self.tasks:
            if not self._is_running or self._stop_after_current:
                log.info("ProcessingWorker: interrotto dall'utente.")
                summary['aborted'] = True
                break
            orig_p   = task['src']
            img_list = task['images']
            final_p  = os.path.splitext(orig_p)[0] + ".cbz"
            log.info(f"Elaborazione: '{os.path.basename(orig_p)}' "
                     f"({len(img_list)} immagini) → '{os.path.basename(final_p)}'")

            if (os.path.exists(final_p) and os.path.normpath(orig_p) != os.path.normpath(final_p)) \
                    or (final_p in processed):
                self._permission_result = None
                pages_on_disk = len(get_archive_file_list(final_p)) if os.path.exists(final_p) else 0
                log.warning(f"  Conflitto: '{os.path.basename(final_p)}' esiste già "
                            f"({pages_on_disk} pag. su disco vs {len(img_list)} nuove)")
                self.ask_permission.emit(orig_p, final_p, len(img_list), pages_on_disk)
                with QMutexLocker(self._mutex):
                    while self._permission_result is None:
                        self._condition.wait(self._mutex)
                log.info(f"  Scelta conflitto: {self._permission_result}")
                if not self._is_running:
                    summary['aborted'] = True
                    break
                if self._permission_result == 'skip':
                    curr_p += len(img_list)
                    self.progress_val.emit(curr_p)
                    summary['skipped'] += 1
                    self.file_finished.emit(orig_p, orig_p, 4)
                    continue
                if self._permission_result == 'rename':
                    base, ext = os.path.splitext(final_p)
                    c = 1
                    while os.path.exists(f"{base}_{c}{ext}") or f"{base}_{c}{ext}" in processed:
                        c += 1
                    final_p = f"{base}_{c}{ext}"
                    log.info(f"  Rinominato in: '{os.path.basename(final_p)}'")

            processed.add(final_p)
            out      = make_temp_dir()
            tmp_zip  = final_p + ".tmp"
            start_p  = curr_p
            size_before = os.path.getsize(orig_p) if os.path.exists(orig_p) else 0

            # rimuovi eventuali .tmp orfani prima di procedere
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                    log.debug(f"  Rimosso tmp orfano: '{tmp_zip}'")
                except Exception as e:
                    log.warning(f"Impossibile rimuovere tmp orfano '{tmp_zip}': {e}")

            try:
                pages = self._build_pages(pool, img_list, out, orig_p, start_p, summary)
                if pages is None:
                    log.info("ProcessingWorker: abort_now() ricevuto.")
                    summary['aborted'] = True
                    break

                with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_STORED) as z:
                    for i, fp in enumerate(pages):
                        z.write(fp, os.path.basename(fp))
                    ci = task.get('comicinfo')
                    if ci and os.path.exists(ci):
                        z.writestr("ComicInfo.xml",
                                   build_comicinfo(ci, len(pages), task.get('edited', False)))
                        log.info("  ComicInfo.xml conservato")
                    mode = "webp" if self.to_webp else "repair"
                    z.comment = f"{CBZ_MARK} {mode}".encode()

                verify_cbz(tmp_zip, len(pages))
                self._commit(orig_p, final_p, tmp_zip)

                size_after = os.path.getsize(final_p)
                summary['done'] += 1
                summary['size_before'] += size_before
                summary['size_after']  += size_after
                result_label = "CONVERTITO (WebP)" if self.to_webp else "RIPARATO"
                log.info(f"  ✓ {result_label}: '{os.path.basename(final_p)}' — "
                         f"{fmt_size(size_before)} → {fmt_size(size_after)}")
                self.file_finished.emit(orig_p, final_p, 3 if self.to_webp else 2)

            except Exception as e:
                log.error(f"  ✗ Errore elaborazione '{os.path.basename(orig_p)}': {e} "
                          f"— originale NON modificato")
                summary['errors'].append((os.path.basename(orig_p), str(e)))
            finally:
                curr_p = start_p + len(img_list)
                self.progress_val.emit(curr_p)
                shutil.rmtree(out, ignore_errors=True)
                if os.path.exists(tmp_zip):
                    try:
                        os.remove(tmp_zip)
                    except Exception:
                        pass
                tmp_src = task.get('tmp')
                if tmp_src and os.path.exists(tmp_src):
                    shutil.rmtree(tmp_src, ignore_errors=True)

    def _build_pages(self, pool, img_list, out, orig_p, start_p, summary):
        """Prepara le pagine numerate 0001, 0002... Restituisce None se interrotto."""
        n    = len(img_list)
        name = os.path.basename(orig_p)
        jobs = [(src, os.path.join(out, f"{i + 1:04d}"), self.to_webp, WEBP_QUALITY)
                for i, src in enumerate(img_list)]
        results = [None] * n

        if pool is None:
            for i, job in enumerate(jobs):
                if not self._is_running:
                    return None
                results[i] = _prepare_page(job)
                self.status_msg.emit(f"Ottimizzazione: {name} ({i + 1}/{n})")
                self.progress_val.emit(start_p + i + 1)
        else:
            futures = {pool.submit(_prepare_page, job): i for i, job in enumerate(jobs)}
            done = 0
            for fut in as_completed(futures):
                if not self._is_running:
                    for f in futures:
                        f.cancel()
                    return None
                results[futures[fut]] = fut.result()
                done += 1
                self.status_msg.emit(f"Conversione WebP: {name} ({done}/{n})")
                self.progress_val.emit(start_p + done)

        notes = {}
        for dst, note in results:
            if note:
                key = note.split(" (")[0]
                notes[key] = notes.get(key, 0) + 1
        for note, count in notes.items():
            log.info(f"  {count} pagine lasciate nel formato originale: {note}")
            summary['pages_kept'] += count
        return [r[0] for r in results]

    def _commit(self, orig_p, final_p, tmp_zip):
        """Il nuovo CBZ è già verificato: ora si possono toccare i file originali."""
        same = os.path.normpath(orig_p) == os.path.normpath(final_p)
        if os.path.exists(final_p):
            # file che verrà sostituito (originale .cbz o "Sovrascrivi"): nel cestino
            if not _trash_file_cross_platform(final_p):
                log.warning(f"  Cestino non disponibile: '{os.path.basename(final_p)}' "
                            f"verrà sovrascritto")
        os.replace(tmp_zip, final_p)
        if not same and os.path.exists(orig_p):
            if _trash_file_cross_platform(orig_p):
                log.info(f"  Originale spostato nel cestino: '{os.path.basename(orig_p)}'")
            else:
                log.warning(f"  Cestino non disponibile: originale eliminato "
                            f"'{os.path.basename(orig_p)}'")
                os.remove(orig_p)

class ThumbWorker(QThread):
    # Emette i byte raw dell'immagine invece di QPixmap
    # (QPixmap NON può essere creato fuori dal main thread in Qt6)
    done = pyqtSignal(str, bytes)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        imgs = get_archive_file_list(self.path)
        if not imgs:
            log.debug(f"ThumbWorker: nessuna immagine trovata in '{self.path}'")
            return
        with tempfile.TemporaryDirectory() as tmp:
            real_fmt = detect_real_format(self.path)
            lower    = self.path.lower()

            if lower.endswith('.pdf') or real_fmt == 'pdf':
                try:
                    doc   = fitz.open(self.path)
                    page  = doc.load_page(0)
                    pix   = page.get_pixmap(alpha=False)
                    img_p = os.path.join(tmp, "t.png")
                    pix.save(img_p)
                    doc.close()
                except Exception as e:
                    log.warning(f"ThumbWorker PDF error '{self.path}': {e}")
                    return
            elif real_fmt == 'zip' or (real_fmt is None and lower.endswith(('.cbz', '.zip'))):
                # ZIP reale: estrazione nativa Python
                try:
                    first = imgs[0]
                    with zipfile.ZipFile(self.path, 'r') as z:
                        z.extract(first, tmp)
                except zipfile.BadZipFile:
                    log.warning(f"ThumbWorker: '{os.path.basename(self.path)}' non è un ZIP "
                                f"(real={real_fmt}), provo unrar/7z")
                    real_fmt = 'rar'   # forza il ramo RAR
                except Exception as e:
                    log.warning(f"ThumbWorker ZIP error '{self.path}': {e}")
                    return

            if real_fmt in ('rar', '7z') or \
               (real_fmt is None and not lower.endswith(('.cbz', '.zip', '.pdf'))):
                # RAR/CBR o formato sconosciuto: unrar e poi 7z e
                first     = imgs[0]
                extracted = False
                try:
                    res = run_tool(
                        ['unrar', 'e', '-y', self.path, first, tmp + os.sep],
                        capture_output=True, timeout=15
                    )
                    extracted = bool(os.listdir(tmp))
                    if not extracted:
                        log.debug(f"ThumbWorker unrar non ha estratto '{first}'")
                except Exception as e:
                    log.debug(f"ThumbWorker unrar error: {e}")
                if not extracted:
                    try:
                        res = run_tool(
                            ['7z', 'e', '-y', f'-o{tmp}', self.path, first],
                            capture_output=True, timeout=15
                        )
                        extracted = bool(os.listdir(tmp))
                        if not extracted:
                            log.warning(f"ThumbWorker 7z: nessun file estratto "
                                        f"(rc={res.returncode})")
                    except Exception as e:
                        log.warning(f"ThumbWorker 7z error '{self.path}': {e}")

            # Leggi bytes del file immagine (sicuro da thread non-GUI)
            for root_dir, _, files in os.walk(tmp):
                for f in sorted(files):
                    full = os.path.join(root_dir, f)
                    if is_page_file(full):
                        try:
                            with open(full, 'rb') as fh:
                                data = fh.read()
                            if data:
                                self.done.emit(self.path, data)
                                return
                        except Exception as e:
                            log.warning(f"ThumbWorker lettura bytes '{full}': {e}")

class LoadingWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, str, list)
    error    = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        tmp      = make_temp_dir()
        ext      = os.path.splitext(self.path)[1].lower()
        real_fmt = detect_real_format(self.path)
        success  = False
        img_list = get_archive_file_list(self.path)
        total    = len(img_list)

        if not img_list:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Archivio vuoto.")
            return

        if ext == '.pdf' or real_fmt == 'pdf':
            if HAS_PDF:
                try:
                    extract_pdf_pages(self.path, tmp,
                                      lambda v, t: self.progress.emit(v, t))
                    success = True
                except Exception as e:
                    log.error(f"LoadingWorker PDF '{self.path}': {e}")
                    success = False
        else:
            # Usa formato reale per decidere il tool
            use_zip = (real_fmt == 'zip') or (real_fmt is None and ext in ('.cbz', '.zip'))
            try:
                if use_zip:
                    try:
                        with zipfile.ZipFile(self.path, 'r') as z:
                            for i, img_name in enumerate(img_list):
                                z.extract(img_name, tmp)
                                self.progress.emit(i + 1, total)
                            # conserva i metadati
                            for n in z.namelist():
                                if is_comicinfo(n):
                                    z.extract(n, tmp)
                                    break
                        success = True
                        log.info(f"LoadingWorker ZIP OK: '{os.path.basename(self.path)}'")
                    except zipfile.BadZipFile:
                        log.warning(f"LoadingWorker: '{os.path.basename(self.path)}' "
                                    f"non è un ZIP valido (real={real_fmt}), provo unrar/7z")
                        use_zip = False  # ricade nel ramo RAR/7z sotto

                if not use_zip:
                    if real_fmt and real_fmt != ext.lstrip('.'):
                        _format_mismatch_log(self.path, ext, real_fmt)
                    extracted_ok = False
                    try:
                        res = run_tool(
                            ['unrar', 'x', '-y', self.path, tmp + os.sep],
                            capture_output=True, timeout=600
                        )
                        if res.returncode == 0:
                            extracted_ok = True
                            log.info(f"LoadingWorker unrar x OK: '{os.path.basename(self.path)}'")
                        else:
                            log.warning(f"LoadingWorker unrar x rc={res.returncode}: "
                                        f"{res.stderr.decode(errors='replace')[:200]}")
                    except FileNotFoundError:
                        log.warning("LoadingWorker: unrar non trovato, uso 7z x")
                    except Exception as e:
                        log.warning(f"LoadingWorker unrar x eccezione: {e}")

                    if not extracted_ok:
                        res = run_tool(
                            ['7z', 'x', '-y', f'-o{tmp}', self.path],
                            capture_output=True, timeout=600
                        )
                        if res.returncode == 0:
                            extracted_ok = True
                            log.info(f"LoadingWorker 7z x OK: '{os.path.basename(self.path)}'")
                        else:
                            log.error(f"LoadingWorker 7z x rc={res.returncode}: "
                                      f"{res.stderr.decode(errors='replace')[:200]}")

                    for i in range(total):
                        self.progress.emit(i + 1, total)
                    success = extracted_ok

            except Exception as e:
                log.error(f"LoadingWorker archive '{self.path}': {e}")
                success = False

        if success:
            extracted = list_page_files(tmp)
            self.finished.emit(self.path, tmp, extracted)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Errore durante l'estrazione.")

class BatchPrepWorker(QThread):
    """Estrae gli archivi e prepara i task per ProcessingWorker."""
    progress = pyqtSignal(int, int)
    ready    = pyqtSignal(list, bool)

    def __init__(self, paths, to_webp):
        super().__init__()
        self.paths   = paths
        self.to_webp = to_webp

    def run(self):
        tasks = []
        total = len(self.paths)
        for i, p in enumerate(self.paths):
            tmp = make_temp_dir()
            log.info(f"BatchPrep: estrazione '{os.path.basename(p)}' → '{tmp}'")
            ok = False
            try:
                ok = extract_archive(p, tmp)
            except Exception as e:
                log.error(f"BatchPrepWorker eccezione su '{p}': {e}")

            extracted = list_page_files(tmp)
            expected  = len(get_archive_file_list(p))

            # Controllo: TUTTE le pagine devono essere state estratte.
            # (Sostituisce il vecchio filtro "< 5 KB" che scartava in silenzio
            #  pagine bianche o pagine WebP leggere.)
            if not ok or not extracted:
                log.error(f"  ✗ Nessuna immagine estratta da '{os.path.basename(p)}' — file saltato")
                shutil.rmtree(tmp, ignore_errors=True)
            elif len(extracted) < expected:
                log.error(f"  ✗ Estratte solo {len(extracted)} pagine su {expected} da "
                          f"'{os.path.basename(p)}' — file saltato, originale intatto")
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                unreadable = []
                for fp in extracted:
                    try:
                        with Image.open(fp) as im:
                            im.size
                    except Exception:
                        unreadable.append(os.path.basename(fp))
                if unreadable:
                    log.warning(f"  {len(unreadable)} pagine non leggibili (conservate "
                                f"comunque così come sono): {', '.join(unreadable[:5])}")
                comicinfo = find_comicinfo(tmp)
                log.info(f"  ✓ {len(extracted)} immagini estratte correttamente"
                         f"{' + ComicInfo.xml' if comicinfo else ''}")
                tasks.append({'src': p, 'images': extracted, 'tmp': tmp,
                              'comicinfo': comicinfo, 'edited': False})

            self.progress.emit(i + 1, total)

        log.info(f"BatchPrep completato: {len(tasks)}/{total} file pronti per l'elaborazione")
        self.ready.emit(tasks, self.to_webp)

# --- LAYOUT COSTANTI ---
# Usate sia da ComicCard che da MainWindow per calcolare la larghezza adattiva
CARD_W       = 195   # larghezza fissa di ogni card
CARD_H       = 385   # altezza fissa di ogni card
CARD_SPACING = 15    # spacing tra card nella griglia
CARD_MARGIN  = 15    # margine esterno della griglia
COLS_DEFAULT = 4     # colonne all'avvio
COLS_MAX     = 7     # massimo assoluto di colonne

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
    selection_changed = pyqtSignal(object, object)

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
        self.btn_r.setStyleSheet("background: #e65100; color: white;")
        self.btn_d = QPushButton("X")
        self.btn_d.setFixedWidth(30)
        self.btn_d.setStyleSheet("background: #b71c1c; color: white;")
        self.btn_d.clicked.connect(lambda: self.remove_requested.emit(self.file_path))
        btns.addWidget(self.btn_e)
        btns.addWidget(self.btn_r)
        btns.addWidget(self.btn_d)
        l.addLayout(btns)

    def set_pages(self, c):
        self.page_badge.setText(f"{c} PAGINE")

    def update_style(self):
        b, bg = ("2px solid #00e5ff", "#3a3a3a") if self.selected else ("1px solid #444", "#2a2a2a")
        self.setStyleSheet(f"ComicCard {{ background: {bg}; border-radius: 10px; border: {b}; }}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.selected = not self.selected
            self.update_style()
            self.selection_changed.emit(self, e.modifiers())

    def set_status(self, code):
        self.status_code = code
        txt, bg, fg = _STATUS_MAP.get(code, ("...", "#555", "white"))
        self.status.setText(txt)
        self.status.setStyleSheet(
            f"background: {bg}; color: {fg}; font-weight: bold; padding: 4px; "
            "border-top-left-radius: 10px; border-top-right-radius: 10px;"
        )
        if code == 4:
            self.btn_r.setText("Dupe")
            self.btn_r.setStyleSheet("background: #546e7a; color: white;")
            try:
                self.btn_r.clicked.disconnect()
            except Exception:
                pass
            self.btn_r.clicked.connect(lambda: self.trash_requested.emit(self.file_path))
        else:
            self.btn_r.setText("Fix")
            self.btn_r.setStyleSheet("background: #e65100; color: white;")
            try:
                self.btn_r.clicked.disconnect()
            except Exception:
                pass
            self.btn_r.clicked.connect(lambda: self.repair_requested.emit(self.file_path))

    def set_pixmap(self, pix):
        self.thumb.setPixmap(pix.scaled(175, 230, Qt.AspectRatioMode.KeepAspectRatioByExpanding))

    def mouseDoubleClickEvent(self, e):
        self.edit_requested.emit(self.file_path)

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
        b_can.setFixedSize(140, 45)
        b_can.setStyleSheet("background: #b71c1c; color: white;")
        b_can.clicked.connect(self.reject)
        b_add = QPushButton("AGGIUNGI")
        b_add.setFixedSize(160, 45)
        b_add.setStyleSheet("background: #0277bd; color: white;")
        b_add.clicked.connect(self.add_ext)
        b_sav = QPushButton("SALVA")
        b_sav.setFixedSize(220, 45)
        b_sav.setStyleSheet("background: #2e7d32; color: white; font-weight: bold;")
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
        w.setStyleSheet("background: #333; border-radius: 5px;")
        l = QVBoxLayout(w)
        l.setContentsMargins(4, 4, 4, 4)
        l.setSpacing(3)

        btn_del = QPushButton("X")
        btn_del.setFixedSize(20, 20)
        btn_del.setStyleSheet("background:red; color:white; font-size:9px;")
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
        self._log_window = LogWindow(self)
        self.init_ui()
        self.check_deps()

        # Dimensione iniziale: 4 card di larghezza
        self._apply_window_width(COLS_DEFAULT)

        frasi = [
            "Il mio processore scalpita...",
            "Pronto a triturare PDF e immagini.",
            "Caffè caricato, iniziamo?",
            "I tuoi fumetti sono in buone mani.",
            "Ottimizzazione? È il mio secondo nome."
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
        """Tasto L apre/chiude la finestra di log."""
        if e.key() == Qt.Key.Key_L and not e.modifiers():
            self._toggle_log()
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
        - Minimo fisso: COLS_DEFAULT (4)
        - Massimo fisso: COLS_MAX (7)
        """
        # Se n è piccolo (0,1,2,3), restituisce 4.
        # Se n è tra 4 e 7, restituisce n.
        # Se n è superiore a 7, restituisce 7.
        return max(COLS_DEFAULT, min(n, COLS_MAX))

    def _apply_window_width(self, cols):
        """Ridimensiona la finestra alla larghezza giusta per `cols` colonne."""
        screen = QApplication.primaryScreen().availableGeometry()
        # La larghezza deve bastare anche per le barre dei pulsanti sopra e sotto
        # alla griglia (altrimenti su schermi stretti alcuni pulsanti finiscono
        # fuori dalla finestra, senza modo di raggiungerli).
        min_bars_w = max(self.top_bar_w.minimumSizeHint().width(),
                         self.footer_w.minimumSizeHint().width())
        w = min(max(self._win_width_for_cols(cols), min_bars_w), screen.width())
        h = self.height() if self.isVisible() else min(800, screen.height())
        self.setFixedWidth(w)
        self.setMinimumHeight(min(600, screen.height()))
        self.setMaximumHeight(screen.height())
        if not self.isVisible():
            self.resize(w, min(h, screen.height()))

    def check_deps(self):
        m = []
        if IS_WIN:
            # su Windows basta 7-Zip (incluso nell'exe): legge anche i RAR/RAR5
            if not find_tool('7z'):
                m.append("7-Zip")
            if not HAS_PDF:
                m.append("PyMuPDF")
            if m:
                QMessageBox.warning(
                    self, "Dipendenze mancanti",
                    "Mancano: " + ", ".join(m) +
                    "\n\nInstalla 7-Zip da https://www.7-zip.org"
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

        title = QLabel("ComicOptimizer, by Shuren")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 34px; font-weight: 900; color: #00e5ff; "
            "padding: 10px; background: #1a1a1a; border-bottom: 2px solid #00d4ff;"
        )
        layout.addWidget(title)

        self.drop_zone = QLabel("\nTRASCINA QUI I FILE (CBZ, CBR, ZIP, RAR, PDF)\n")
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setFixedHeight(120)
        self.set_drop_style(False)
        layout.addWidget(self.drop_zone)

        top_bar = QHBoxLayout()
        self.btn_clear = QPushButton("PULISCI LISTA")
        self.btn_clear.setFixedSize(130, 45)
        self.btn_clear.clicked.connect(self.clear_all)

        self.btn_all = QPushButton("SISTEMA TUTTO")
        self.btn_all.setFixedSize(150, 45)
        self.btn_all.setStyleSheet("background: #e65100; color: white; font-weight: bold;")
        self.btn_all.clicked.connect(self.repair_all_trigger)

        self.btn_analyze = QPushButton("ANALIZZA")
        self.btn_analyze.setFixedSize(130, 45)
        self.btn_analyze.setStyleSheet("background: #00bcd4; color: white;")
        self.btn_analyze.clicked.connect(lambda: self.run_analysis(auto=False))

        self.btn_sel = QPushButton("SISTEMA SELEZIONATI")
        self.btn_sel.setFixedSize(180, 45)
        self.btn_sel.setStyleSheet("background: #0277bd; color: white; font-weight: bold;")
        self.btn_sel.setVisible(False)
        self.btn_sel.clicked.connect(self.repair_selected)

        self.btn_trash_sel = QPushButton("CESTINA SELEZIONATI")
        self.btn_trash_sel.setFixedSize(180, 45)
        self.btn_trash_sel.setStyleSheet("background: #b71c1c; color: white;")
        self.btn_trash_sel.setVisible(False)
        self.btn_trash_sel.clicked.connect(self.trash_selected)

        self.btn_trash_dupes = QPushButton("PULISCI DUPLICATI")
        self.btn_trash_dupes.setFixedSize(150, 45)
        self.btn_trash_dupes.setStyleSheet("background: #546e7a; color: white;")
        self.btn_trash_dupes.setVisible(False)
        self.btn_trash_dupes.clicked.connect(self.trash_all_duplicates)

        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.btn_all)
        top_bar.addWidget(self.btn_analyze)
        top_bar.addWidget(self.btn_sel)
        top_bar.addWidget(self.btn_trash_sel)
        top_bar.addWidget(self.btn_trash_dupes)
        top_bar.addStretch()

        self.status_stack = QStackedWidget()
        self.status_stack.setFixedHeight(50)
        idle_w = QWidget()
        idle_l = QVBoxLayout(idle_w)
        idle_l.setContentsMargins(0, 0, 0, 0)
        idle_l.setSpacing(2)
        self.hint_lbl = QLabel("Clicca sulle card per selezionarle (Ctrl e Shift supportati)")
        self.hint_lbl.setStyleSheet("color: #00e5ff; font-size: 11px; font-weight: bold")
        self.ironic_lbl = QLabel("Pronto ad operare.")
        self.ironic_lbl.setStyleSheet("color: #aaa; font-style: italic")
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
        self.pbar.setStyleSheet(
            "QProgressBar { border: 1px solid #00e5ff; border-radius: 5px; "
            "text-align: center; color: white; font-weight: bold; } "
            "QProgressBar::chunk { background: #00e5ff; }"
        )
        self.status_msg = QLabel("Lavorando...")
        self.status_msg.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 12px")
        vl.addWidget(self.status_msg)
        vl.addWidget(self.pbar)
        work_l.addLayout(vl, 1)
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedSize(80, 40)
        self.btn_stop.setStyleSheet("background: #b71c1c; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self.request_stop)
        work_l.addWidget(self.btn_stop)
        self.status_stack.addWidget(work_w)

        top_bar.addWidget(self.status_stack, 1)
        self.top_bar_w = QWidget()
        self.top_bar_w.setLayout(top_bar)
        top_bar_scroll = QScrollArea()
        top_bar_scroll.setWidgetResizable(True)
        top_bar_scroll.setFixedHeight(64)
        top_bar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        top_bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        top_bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        top_bar_scroll.setWidget(self.top_bar_w)
        layout.addWidget(top_bar_scroll)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_w = QWidget()
        self.grid_l = QGridLayout(self.grid_w)
        self.grid_l.setSpacing(15)
        self.grid_l.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_w)
        layout.addWidget(self.scroll)

        footer = QHBoxLayout()
        ls = "color: #FFB300; font-weight: bold; font-size: 13px; background: none; border: none;"
        self.n_btn = QPushButton(f"Novità v{APP_VERSION}")
        self.n_btn.setStyleSheet(ls)
        self.n_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.n_btn.clicked.connect(self.show_news)
        self.c_btn = QPushButton("Credits")
        self.c_btn.setStyleSheet(ls)
        self.c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.c_btn.clicked.connect(self.show_credits)
        self.p_btn = QPushButton("Privacy")
        self.p_btn.setStyleSheet(ls)
        self.p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.p_btn.clicked.connect(self.show_privacy)
        self.log_btn = QPushButton("📋 Log  [L]")
        self.log_btn.setStyleSheet("color: #90caf9; font-weight: bold; font-size: 13px; background: none; border: none;")
        self.log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_btn.clicked.connect(self._toggle_log)

        self.chk_keep_log = QCheckBox("Mantieni log")
        self.chk_keep_log.setChecked(False)
        self.chk_keep_log.setToolTip(
            f"Se spuntato, il file di log viene conservato alla chiusura:\n{LOG_PATH}\n"
            "Se non spuntato, viene eliminato automaticamente."
        )
        self.chk_keep_log.setStyleSheet(
            "QCheckBox { color: #888; font-size: 11px; }"
            "QCheckBox::indicator { width: 13px; height: 13px; }"
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
        self.chk_notify.setStyleSheet(
            "QCheckBox { color: #888; font-size: 11px; }"
            "QCheckBox::indicator { width: 13px; height: 13px; }"
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
        self.btn_analyze.setEnabled(not working)

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

    def _notify_system(self, title, body, ok=True):
        """Notifica del sistema operativo + suono (non blocca l'interfaccia)."""
        shown = False
        quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if sys.platform.startswith("linux") and shutil.which("notify-send"):
                icon = APP_ICON_PATH if APP_ICON_PATH else "dialog-information"
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
        self.btn_sel.setVisible(False)
        self.btn_trash_sel.setVisible(False)
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
               "&nbsp;&nbsp;• <b>Al mio PC:</b> Per non essere esploso mentre compilavo e testavo centinaia di versioni.")
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
        sel_n = len([c for c in cards if c.selected])
        self.btn_sel.setVisible(sel_n > 0)
        self.btn_trash_sel.setVisible(sel_n > 0)

    def on_file_done(self, o, n, s):
        status_names = {0:"DA SISTEMARE", 1:"OK", 2:"RIPARATO", 3:"CONVERTITO", 4:"SALTATO", 5:"DANNEGGIATO"}
        label = status_names.get(s, str(s))
        if o == n:
            log.info(f"File saltato: '{os.path.basename(o)}' → {label}")
        else:
            log.info(f"File completato: '{os.path.basename(o)}' → '{os.path.basename(n)}' [{label}]")
        if o in self.cards:
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
                c = ComicCard(p)
                c.set_pages(count)
                c.selection_changed.connect(self.handle_selection)
                c.edit_requested.connect(self.open_editor)
                c.repair_requested.connect(self.individual_repair)
                c.remove_requested.connect(self.rem)
                c.trash_requested.connect(self.confirm_and_trash)
                self.cards[p] = c
                self.load_t(p)
                c.set_status(self.check_status(p))
                added += 1
        log.info(f"Importati {added} file ({len(paths)} totali scansionati).")
        self.refresh_grid()
        # L'analisi automatica post-import è stata rimossa: check_status() assegna
        # già lo stato corretto a ogni card durante l'import. L'utente può lanciare
        # manualmente l'analisi (che include la ricerca duplicati) con il tasto ANALIZZA.

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
            bw = BatchPrepWorker(targets, m == "convert")
            bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
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
        bw = BatchPrepWorker(targets, m == "convert")
        bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
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
        l = LoadingWorker(path)
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
            bw = BatchPrepWorker([path], m == "convert")
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
        cols = self._cols_for_count(n) if n > 0 else COLS_DEFAULT
        self._apply_window_width(cols)

        for i, p in enumerate(sorted(self.cards.keys(), key=get_natural_sort_key)):
            self.grid_l.addWidget(self.cards[p], i // cols, i % cols)

    def rem(self, p):
        if p in self.cards:
            self.cards.pop(p).deleteLater()
            self.refresh_grid()

    def set_drop_style(self, a):
        self.drop_zone.setStyleSheet(
            f"border: {4 if a else 3}px dashed {'#00e5ff' if a else '#444'}; "
            f"border-radius: 15px; background: {'#2c3e50' if a else '#111'}; "
            f"color: {'#00e5ff' if a else '#555'}; font-size: 18px; font-weight: bold;"
        )

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


# FIX #5: QApplication creata solo in __main__, non a livello di modulo
if __name__ == "__main__":
    multiprocessing.freeze_support()   # necessario per l'eseguibile (PyInstaller)
    app = QApplication(sys.argv)
    app.setApplicationName("ComicOptimizer")
    app.setApplicationVersion(APP_VERSION)
    cleanup_stale_temp()

    # setDesktopFileName va chiamato solo quando si gira come AppImage
    # (o con un .desktop file effettivamente installato), altrimenti
    # causa l'errore "Could not register app ID" sul portal D-Bus di freedesktop.
    _appdir = os.environ.get('APPDIR', '')
    if _appdir:
        # Dentro AppImage: usa il nome del .desktop file incluso nel bundle
        app.setDesktopFileName('comicoptimizer')

    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f'Shuren.ComicOptimizer.{APP_VERSION}')
        except Exception:
            pass

    base_path = _appdir or RES_DIR
    icon_path = os.path.join(base_path, "comicoptimizer.png")
    if os.path.exists(icon_path):
        APP_ICON_PATH = icon_path
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon.fromTheme("applications-graphics"))

    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window,          QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.WindowText,      Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base,            QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase,     Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText,     Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text,            Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button,          QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ColorRole.ButtonText,      Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText,      Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link,            QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.Highlight,       QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    try:
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        log.critical(f"Errore critico: {e}", exc_info=True)
        if sys.stdout:
            print(f"Errore critico: {e}")
        QMessageBox.critical(None, "ComicOptimizer — errore critico",
                             f"{e}\n\nDettagli nel log:\n{LOG_PATH}")
