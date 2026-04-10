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
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QPushButton, QLabel, QFileDialog, QHBoxLayout,
                             QScrollArea, QGridLayout, QFrame, QDialog,
                             QStackedWidget, QSpinBox, QMessageBox, QProgressBar,
                             QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QWaitCondition, QMutex, QMutexLocker
from PyQt6.QtGui import QPixmap, QColor, QPalette, QIcon

# --- LOGGING ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("comicoptimizer.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("ComicOptimizer")

# Handler che emette ogni riga di log come segnale Qt (per la finestra di log in-app)
from PyQt6.QtCore import QObject, pyqtSignal as _pyqtSignal

class _QtLogHandler(logging.Handler, QObject):
    new_record = _pyqtSignal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
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
        self.setMinimumSize(900, 500)
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
    if sys.platform == "linux":
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

# --- UTILITY ---

def get_natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def is_junk_file(path):
    name = os.path.basename(path)
    return name.startswith("._") or name.lower() == ".ds_store" or "__macosx" in path.lower()

# FIX #6: parsing 7z con formato stabile (-slt) invece di offset fisso line[53:]
def _parse_7z_list(path):
    """Usa '7z l -ba -slt' per un output strutturato e affidabile."""
    imgs = []
    try:
        res = subprocess.run(
            ['7z', 'l', '-ba', '-slt', path],
            capture_output=True, text=True, timeout=10
        )
        if res.returncode != 0:
            return imgs
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.lower().startswith("path = "):
                name = line[7:].strip()
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(name):
                    imgs.append(name)
    except Exception as e:
        log.warning(f"7z list fallito su '{path}': {e}")
    return imgs

def get_archive_file_list(path):
    imgs = []
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        if not HAS_PDF:
            return []
        try:
            doc = fitz.open(path)
            imgs = [f"p{i:04d}" for i in range(len(doc))]
            doc.close()
            return imgs
        except Exception as e:
            log.warning(f"Errore apertura PDF '{path}': {e}")
            return []
    # Prova unrar
    try:
        res = subprocess.run(['unrar', 'lb', path], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            imgs = [
                f.strip() for f in res.stdout.splitlines()
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(f)
            ]
    except Exception as e:
        log.debug(f"unrar lb fallito su '{path}': {e}")
    # Fallback 7z con parsing strutturato
    if not imgs:
        imgs = _parse_7z_list(path)
    imgs.sort(key=get_natural_sort_key)
    return imgs

def check_integrity(path):
    """
    Verifica l'integrità dell'archivio.
    Per i RAR/CBR usa prima 'unrar t' (più affidabile), poi 7z come fallback.
    Per ZIP/CBZ usa direttamente zipfile (nessuna dipendenza esterna).
    """
    lower = path.lower()
    if lower.endswith('.pdf'):
        return HAS_PDF

    # ZIP/CBZ: verifica nativa Python, nessun processo esterno
    if lower.endswith(('.cbz', '.zip')):
        try:
            with zipfile.ZipFile(path, 'r') as z:
                bad = z.testzip()
                if bad:
                    log.warning(f"check_integrity: file corrotto nel zip '{bad}' in '{path}'")
                return bad is None
        except Exception as e:
            log.warning(f"check_integrity zip errore '{path}': {e}")
            return False

    # RAR/CBR: prova unrar t prima (più affidabile per tutti i formati RAR)
    if lower.endswith(('.cbr', '.rar')):
        try:
            res = subprocess.run(
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

    # Fallback generico: 7z t
    try:
        res = subprocess.run(['7z', 't', path], capture_output=True, timeout=60)
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        log.warning(f"check_integrity 7z timeout su '{path}'")
        return False
    except Exception as e:
        log.warning(f"check_integrity 7z errore su '{path}': {e}")
        return False

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
_IMAGE_EXTS   = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff', '.tif', '.avif')

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
        groups  = {}
        total   = len(self.paths)
        for i, p in enumerate(self.paths):
            is_ok = check_integrity(p)
            if not is_ok:
                results[p] = 5
            else:
                target = os.path.splitext(p)[0] + ".cbz"
                groups.setdefault(target, []).append(p)
            self.progress.emit(i + 1, total)

        dupes_count = 0
        for t, ps in groups.items():
            if len(ps) > 1:
                ps.sort(key=lambda x: 1 if x.lower().endswith('.cbz') else 0, reverse=True)
                for loser in ps[1:]:
                    if loser not in results:
                        results[loser] = 4
                        dupes_count += 1

        # BUG FIX: assegna status a TUTTI i file integri (non solo danneggiati/duplicati).
        # Senza questo, le card non aggiornano mai il colore dopo la conversione.
        # check_status è leggero (solo lettura zip header) quindi sicuro da chiamare qui.
        for p in self.paths:
            if p not in results:
                # Determina status in base al tipo e al contenuto
                lower = p.lower()
                if lower.endswith('.pdf'):
                    results[p] = 0   # PDF: sempre "da sistemare" (convertibile)
                elif lower.endswith(('.cbr', '.rar')):
                    results[p] = 0   # RAR: ancora da convertire
                elif lower.endswith(('.cbz', '.zip')):
                    try:
                        with zipfile.ZipFile(p, 'r') as z:
                            imgs = [n for n in z.namelist()
                                    if n.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                            if imgs and all(n.lower().endswith('.webp') for n in imgs):
                                results[p] = 3   # tutto WebP → CONVERTITO
                            else:
                                results[p] = 1   # CBZ con jpg/png → OK
                    except Exception:
                        results[p] = 0
                else:
                    results[p] = 1

        self.finished.emit(results, dupes_count)

class ProcessingWorker(QThread):
    progress_val  = pyqtSignal(int)
    progress_max  = pyqtSignal(int)
    status_msg    = pyqtSignal(str)
    ask_permission = pyqtSignal(str, str, int, int)
    file_finished  = pyqtSignal(str, str, int)
    finished       = pyqtSignal()

    def __init__(self, tasks, to_webp=False):
        super().__init__()
        self.tasks   = tasks
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

    def stop_later(self):
        self._stop_after_current = True

    def run(self):
        processed = set()
        total_p = sum(len(t[1]) for t in self.tasks)
        self.progress_max.emit(total_p)
        curr_p = 0
        log.info(f"ProcessingWorker avviato: {len(self.tasks)} file, "
                 f"{total_p} immagini totali, webp={self.to_webp}")

        for task in self.tasks:
            if not self._is_running or self._stop_after_current:
                log.info("ProcessingWorker: interrotto dall'utente.")
                break
            orig_p  = task[0]
            img_list = task[1]
            tmp_src  = task[2] if len(task) > 2 else None
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
                if self._permission_result == 'skip':
                    curr_p += len(img_list)
                    self.progress_val.emit(curr_p)
                    if tmp_src:
                        shutil.rmtree(tmp_src, ignore_errors=True)
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
            out     = tempfile.mkdtemp()
            tmp_zip = final_p + ".tmp"

            # FIX #8: rimuovi eventuali .tmp orfani prima di procedere
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                    log.debug(f"  Rimosso tmp orfano: '{tmp_zip}'")
                except Exception as e:
                    log.warning(f"Impossibile rimuovere tmp orfano '{tmp_zip}': {e}")

            try:
                for i, p in enumerate(img_list):
                    if not self._is_running:
                        log.info("ProcessingWorker: abort_now() ricevuto.")
                        return
                    curr_p += 1
                    self.status_msg.emit(
                        f"Ottimizzazione: {os.path.basename(orig_p)} ({i + 1}/{len(img_list)})"
                    )
                    self.progress_val.emit(curr_p)
                    ext = ".webp" if self.to_webp else (os.path.splitext(p)[1].lower() or ".jpg")
                    dst = os.path.join(out, f"{i + 1:04d}{ext}")
                    if self.to_webp:
                        with Image.open(p) as img:
                            if img.mode in ("RGBA", "P", "LA"):
                                img = img.convert("RGB")
                            img.save(dst, "WEBP", quality=85)
                    else:
                        shutil.copy2(p, dst)

                with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_STORED) as z:
                    for f in sorted(os.listdir(out)):
                        fp = os.path.join(out, f)
                        sz = os.path.getsize(fp)
                        if sz < 5120:
                            log.error(f"  GUARD: immagine sospetta {sz} B → '{f}' — "
                                      f"l'estrazione potrebbe essere fallita!")
                        z.write(fp, f)

                final_size_kb = os.path.getsize(tmp_zip) // 1024
                if os.path.exists(final_p):
                    os.remove(final_p)
                if os.path.exists(orig_p) and os.path.normpath(orig_p) != os.path.normpath(final_p):
                    os.remove(orig_p)
                shutil.move(tmp_zip, final_p)
                result_label = "CONVERTITO (WebP)" if self.to_webp else "RIPARATO"
                log.info(f"  ✓ {result_label}: '{os.path.basename(final_p)}' — {final_size_kb} KB")
                self.file_finished.emit(orig_p, final_p, 3 if self.to_webp else 2)

            except Exception as e:
                log.error(f"  ✗ Errore elaborazione '{os.path.basename(orig_p)}': {e}")
            finally:
                shutil.rmtree(out, ignore_errors=True)
                if os.path.exists(tmp_zip):
                    try:
                        os.remove(tmp_zip)
                    except Exception:
                        pass
                if tmp_src and os.path.exists(tmp_src):
                    shutil.rmtree(tmp_src, ignore_errors=True)

        log.info("ProcessingWorker completato.")
        self.finished.emit()

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
            lower = self.path.lower()
            if lower.endswith('.pdf'):
                try:
                    doc   = fitz.open(self.path)
                    page  = doc.load_page(0)
                    pix   = page.get_pixmap()
                    img_p = os.path.join(tmp, "t.png")
                    pix.save(img_p)
                    doc.close()
                except Exception as e:
                    log.warning(f"ThumbWorker PDF error '{self.path}': {e}")
                    return
            elif lower.endswith(('.cbz', '.zip')):
                # ZIP: estrazione nativa Python, veloce e affidabile
                try:
                    first = imgs[0]
                    with zipfile.ZipFile(self.path, 'r') as z:
                        z.extract(first, tmp)
                except Exception as e:
                    log.warning(f"ThumbWorker ZIP error '{self.path}': {e}")
                    return
            else:
                # RAR/CBR: prova unrar e (appiattisce sottocartelle), poi 7z e
                first = imgs[0]
                extracted = False
                try:
                    res = subprocess.run(
                        ['unrar', 'e', '-y', self.path, first, tmp + "/"],
                        capture_output=True, timeout=15
                    )
                    extracted = bool(os.listdir(tmp))
                    if not extracted:
                        log.debug(f"ThumbWorker unrar non ha estratto '{first}' da '{self.path}'")
                except Exception as e:
                    log.debug(f"ThumbWorker unrar error: {e}")
                if not extracted:
                    try:
                        res = subprocess.run(
                            ['7z', 'e', '-y', f'-o{tmp}', self.path, first],
                            capture_output=True, timeout=15
                        )
                        extracted = bool(os.listdir(tmp))
                        if not extracted:
                            log.warning(f"ThumbWorker 7z: nessun file estratto per "
                                        f"'{first}' da '{self.path}' (rc={res.returncode})")
                    except Exception as e:
                        log.warning(f"ThumbWorker 7z error '{self.path}': {e}")

            # Leggi bytes del file immagine (sicuro da thread non-GUI)
            for root_dir, _, files in os.walk(tmp):
                for f in sorted(files):
                    full = os.path.join(root_dir, f)
                    if not is_junk_file(f) and f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
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
        tmp     = tempfile.mkdtemp()
        ext     = os.path.splitext(self.path)[1].lower()
        success = False
        img_list = get_archive_file_list(self.path)
        total    = len(img_list)

        if not img_list:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Archivio vuoto.")
            return

        if ext == '.pdf' and HAS_PDF:
            try:
                doc = fitz.open(self.path)
                for i in range(total):
                    page = doc.load_page(i)
                    pix  = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    pix.save(os.path.join(tmp, f"{i + 1:04d}.png"))
                    self.progress.emit(i + 1, total)
                doc.close()
                success = True
            except Exception as e:
                log.error(f"LoadingWorker PDF '{self.path}': {e}")
                success = False
        else:
            try:
                if self.path.lower().endswith(('.cbz', '.zip')):
                    # ZIP: estrazione nativa Python
                    with zipfile.ZipFile(self.path, 'r') as z:
                        for i, img_name in enumerate(img_list):
                            z.extract(img_name, tmp)
                            self.progress.emit(i + 1, total)
                    success = True
                else:
                    # RAR/CBR: unrar x prima, poi 7z x come fallback
                    extracted_ok = False
                    try:
                        res = subprocess.run(
                            ['unrar', 'x', '-y', self.path, tmp + "/"],
                            capture_output=True, timeout=300
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
                        res = subprocess.run(
                            ['7z', 'x', '-y', f'-o{tmp}', self.path],
                            capture_output=True, timeout=300
                        )
                        if res.returncode == 0:
                            extracted_ok = True
                            log.info(f"LoadingWorker 7z x OK: '{os.path.basename(self.path)}'")
                        else:
                            log.error(f"LoadingWorker 7z x rc={res.returncode}: "
                                      f"{res.stderr.decode(errors='replace')[:200]}")

                    # Emetti progress manuale dato che abbiamo estratto tutto in una volta
                    for i in range(total):
                        self.progress.emit(i + 1, total)
                    success = extracted_ok

            except Exception as e:
                log.error(f"LoadingWorker archive '{self.path}': {e}")
                success = False

        if success:
            extracted = [
                os.path.join(r, f)
                for r, _, fs in os.walk(tmp)
                for f in fs
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                and not is_junk_file(os.path.join(r, f))
            ]
            extracted.sort(key=get_natural_sort_key)
            self.finished.emit(self.path, tmp, extracted)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Errore durante l'estrazione.")

class BatchPrepWorker(QThread):
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
            tmp = tempfile.mkdtemp()
            ext = os.path.splitext(p)[1].lower()
            log.info(f"BatchPrep: estrazione '{os.path.basename(p)}' → '{tmp}'")
            try:
                if ext == '.pdf' and HAS_PDF:
                    doc = fitz.open(p)
                    for j in range(len(doc)):
                        page = doc.load_page(j)
                        pix  = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8))
                        pix.save(os.path.join(tmp, f"{j + 1:04d}.png"))
                    doc.close()
                    log.info(f"  PDF: estratte {len(doc.pages) if hasattr(doc,'pages') else '?'} pagine")
                elif ext in ('.cbz', '.zip'):
                    # ZIP: estrazione nativa Python, affidabile al 100%
                    with zipfile.ZipFile(p, 'r') as z:
                        z.extractall(tmp)
                    log.info(f"  ZIP: extractall completato")
                else:
                    # RAR/CBR: prova unrar x prima (più affidabile), poi 7z x come fallback
                    success = False
                    try:
                        res = subprocess.run(
                            ['unrar', 'x', '-y', p, tmp + "/"],
                            capture_output=True, timeout=300
                        )
                        if res.returncode == 0:
                            success = True
                            log.info(f"  unrar x: OK (rc=0)")
                        else:
                            log.warning(f"  unrar x: FALLITO rc={res.returncode}, "
                                        f"stderr={res.stderr.decode(errors='replace')[:200]}")
                    except FileNotFoundError:
                        log.warning("  unrar non trovato, uso 7z x")
                    except subprocess.TimeoutExpired:
                        log.error(f"  unrar x: TIMEOUT su '{p}'")
                    except Exception as e:
                        log.warning(f"  unrar x eccezione: {e}")

                    if not success:
                        try:
                            res = subprocess.run(
                                ['7z', 'x', '-y', f'-o{tmp}', p],
                                capture_output=True, timeout=300
                            )
                            if res.returncode == 0:
                                success = True
                                log.info(f"  7z x: OK (rc=0)")
                            else:
                                log.error(f"  7z x: FALLITO rc={res.returncode}, "
                                          f"stderr={res.stderr.decode(errors='replace')[:200]}")
                        except subprocess.TimeoutExpired:
                            log.error(f"  7z x: TIMEOUT su '{p}'")
                        except Exception as e:
                            log.error(f"  7z x eccezione: {e}")

            except Exception as e:
                log.error(f"BatchPrepWorker eccezione su '{p}': {e}")

            # Conta e valida i file estratti
            extracted = [
                os.path.join(r, f)
                for r, _, fs in os.walk(tmp)
                for f in fs
                if f.lower().endswith(_IMAGE_EXTS)
                and not is_junk_file(os.path.join(r, f))
            ]
            extracted.sort(key=get_natural_sort_key)

            # Validazione dimensioni: un'immagine reale è sempre > 5 KB
            valid = [fp for fp in extracted if os.path.getsize(fp) > 5120]
            if len(valid) != len(extracted):
                log.warning(f"  {len(extracted) - len(valid)} file sospetti (< 5 KB) esclusi su {len(extracted)} totali")
                for fp in extracted:
                    sz = os.path.getsize(fp)
                    if sz <= 5120:
                        log.warning(f"    SOSPETTO {sz} B: {os.path.basename(fp)}")
                extracted = valid

            if extracted:
                log.info(f"  ✓ {len(extracted)} immagini estratte correttamente")
                tasks.append((p, extracted, tmp))
            else:
                log.error(f"  ✗ Nessuna immagine estratta da '{os.path.basename(p)}' — file saltato")
                shutil.rmtree(tmp, ignore_errors=True)

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
        self.setMinimumSize(1100, 850)

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
                            if img.mode in ("RGBA", "P", "LA"):
                                img = img.convert("RGB")
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
        self.setWindowTitle("ComicOptimizer v2.5.00")
        self.setAcceptDrops(True)
        self.cards           = {}
        self.last_clicked    = None
        self._threads_lock   = threading.Lock()
        self._active_threads = set()
        self.current_worker  = None
        self.skip_trash_confirm = False
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
        log.info("ComicOptimizer avviato.")

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
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.abort_now()
        with self._threads_lock:
            threads = list(self._active_threads)
        for t in threads:
            t.quit()
            t.wait(2000)
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

    def _cols_for_count(self, n):
        """
        Restituisce il numero di colonne ottimale per `n` card.
        - Minimo COLS_DEFAULT (4) se ci sono almeno 4 card
        - Massimo COLS_MAX (7), indipendentemente dalla risoluzione
        """
        if n <= 0:
            return COLS_DEFAULT
        cols = min(n, COLS_MAX)
        cols = max(cols, min(n, COLS_DEFAULT))
        return cols

    def _apply_window_width(self, cols):
        """Ridimensiona la finestra alla larghezza giusta per `cols` colonne."""
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(self._win_width_for_cols(cols), screen.width())
        h = self.height() if self.isVisible() else min(800, screen.height())
        self.setFixedWidth(w)
        self.setMinimumHeight(600)
        self.setMaximumHeight(screen.height())
        if not self.isVisible():
            self.resize(w, h)

    def check_deps(self):
        m = []
        if not shutil.which('7z'):
            m.append("p7zip-full")
        if not shutil.which('unrar'):
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
        layout.addLayout(top_bar)

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
        self.n_btn = QPushButton("Novità v2.5")
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
        footer.addWidget(self.n_btn)
        footer.addStretch()
        footer.addWidget(self.c_btn)
        footer.addStretch()
        footer.addWidget(self.p_btn)
        footer.addStretch()
        footer.addWidget(self.log_btn)
        layout.addLayout(footer)

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
        self.current_worker.finished.connect(lambda: (self.reset_ui(), self.run_analysis(True)))
        self._add_thread(self.current_worker)
        self.current_worker.start()

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
        msg = ("<b>⚡ ComicOptimizer 2.0: Il Grande Salto!</b><br><br>"
               "La tua collezione di fumetti non è mai stata così in forma. Ecco cosa c'è di nuovo:<br><br>"
               "&nbsp;&nbsp;🆕 <b>Benvenuti PDF!</b> Converti i tuoi PDF in agili file .cbz con un solo clic.<br>"
               "&nbsp;&nbsp;🚀 <b>Turbo Mode:</b> Motore interno riscritto per essere più veloce, stabile e leggero.<br>"
               "&nbsp;&nbsp;🎯 <b>Ordine Totale:</b> Nuova gestione asincrona dei file per un'esperienza fluida e senza blocchi.<br>"
               "&nbsp;&nbsp;💎 <b>Qualità WebP:</b> Ottimizzazione spaziale estrema senza compromessi visivi.<br><br>"
               "Mettiti comodo, al disordine ci pensiamo noi.")
        QMessageBox.information(self, "Novità v2.0", msg)

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
        self.run_analysis(True)

    # FIX #2: trash cross-platform con feedback in caso di errore
    def trash_file(self, p):
        log.info(f"Cestino: '{os.path.basename(p)}'")
        if _trash_file_cross_platform(p):
            log.info(f"  → spostato nel cestino con successo.")
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
            targets = [p for p, c in self.cards.items() if c.status_code not in (4, 5)]
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
                self.start_processing([(p, dlg.get_paths(), t)], to_webp=False)
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
                self.reset_ui()
            elif r == 2:
                self.current_worker.stop_later()

    def check_status(self, p):
        if p.lower().endswith('.pdf'):
            return 0
        if not p.lower().endswith('.cbz'):
            return 0
        try:
            with zipfile.ZipFile(p, 'r') as z:
                imgs = [n for n in z.namelist() if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                return 3 if imgs and all(n.lower().endswith('.webp') for n in imgs) else 1
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
    app = QApplication(sys.argv)

    # setDesktopFileName va chiamato solo quando si gira come AppImage
    # (o con un .desktop file effettivamente installato), altrimenti
    # causa l'errore "Could not register app ID" sul portal D-Bus di freedesktop.
    _appdir = os.environ.get('APPDIR', '')
    if _appdir:
        # Dentro AppImage: usa il nome del .desktop file incluso nel bundle
        app.setDesktopFileName('comicoptimizer')

    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('comicoptimizer')

    base_path = _appdir or os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, "comicoptimizer.png")
    if os.path.exists(icon_path):
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
        print(f"Errore critico: {e}")
