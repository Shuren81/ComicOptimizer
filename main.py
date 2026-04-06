#!/usr/bin/env python3

import sys
import os
import shutil
import tempfile
import subprocess
import zipfile
import re
import random
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QHBoxLayout, 
                             QScrollArea, QGridLayout, QFrame, QDialog, 
                             QStackedWidget, QSpinBox, QMessageBox, QProgressBar,
                             QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QWaitCondition, QMutex, QMutexLocker
from PyQt6.QtGui import QPixmap, QColor, QPalette, QCursor, QIcon

# --- INIZIALIZZAZIONE APPLICAZIONE (CRITICA PER APPIMAGE) ---
app_id = 'comicoptimizer' 
app = QApplication(sys.argv)
app.setDesktopFileName(app_id)

if sys.platform == 'win32':
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

base_path = os.environ.get('APPDIR', os.path.dirname(os.path.abspath(__file__)))
icon_path = os.path.join(base_path, "comicoptimizer.png")

if os.path.exists(icon_path):
    app.setWindowIcon(QIcon(icon_path))
else:
    app.setWindowIcon(QIcon.fromTheme("applications-graphics"))

try:
    import fitz 
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# --- UTILITY ---

def get_natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def is_junk_file(path):
    name = os.path.basename(path)
    return name.startswith("._") or name.lower() == ".ds_store" or "__macosx" in path.lower()

def get_archive_file_list(path):
    imgs = []
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf' and HAS_PDF:
        try:
            doc = fitz.open(path); imgs = [f"p{i:04d}" for i in range(len(doc))]; doc.close()
            return imgs
        except: return []
    try:
        res = subprocess.run(['unrar', 'lb', path], capture_output=True, text=True, timeout=5)
        if res.returncode == 0: imgs = [f.strip() for f in res.stdout.splitlines() if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(f)]
    except: pass
    if not imgs:
        try:
            res = subprocess.run(['7z', 'l', '-ba', path], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    name = line[53:].strip()
                    if name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(name): imgs.append(name)
        except: pass
    imgs.sort(key=get_natural_sort_key)
    return imgs

def check_integrity(path):
    if path.lower().endswith('.pdf'): return HAS_PDF
    res = subprocess.run(['7z', 't', path], capture_output=True)
    return res.returncode == 0

# --- COMPONENTS ---

class StopDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Interruzione"); self.setFixedSize(450, 180)
        l = QVBoxLayout(self); lbl = QLabel("<b>Cosa desideri fare?</b>"); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); l.addWidget(lbl)
        btns = QHBoxLayout(); b1 = QPushButton("Annulla Subito"); b1.setStyleSheet("background: #b71c1c; color: white;"); b1.clicked.connect(lambda: self.done(1))
        b2 = QPushButton("Termina in corso"); b2.setStyleSheet("background: #e65100; color: white;"); b2.clicked.connect(lambda: self.done(2))
        b3 = QPushButton("Prosegui"); b3.setStyleSheet("background: #444; color: white;"); b3.clicked.connect(lambda: self.done(0))
        btns.addWidget(b1); btns.addWidget(b2); btns.addWidget(b3); l.addLayout(btns)

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None): super().__init__(parent); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus); self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")
    def wheelEvent(self, e): e.ignore()

# --- WORKERS ---

class ImportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    def __init__(self, raw_paths): super().__init__(); self.raw_paths = raw_paths
    def run(self):
        valid = []; all_to_check = []
        for p in self.raw_paths:
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    for f in fs:
                        if f.lower().endswith(('.cbz','.cbr','.zip','.rar','.pdf')): all_to_check.append(os.path.join(r, f))
            elif p.lower().endswith(('.cbz','.cbr','.zip','.rar','.pdf')): all_to_check.append(p)
        total = len(all_to_check)
        for i, p in enumerate(all_to_check):
            flist = get_archive_file_list(p); (valid.append((p, len(flist))) if flist else None)
            self.progress.emit(i+1, total)
        valid.sort(key=lambda x: get_natural_sort_key(x[0])); self.finished.emit(valid)

class AnalysisWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict, int)
    def __init__(self, cards_paths): super().__init__(); self.paths = cards_paths
    def run(self):
        results = {}; groups = {}; total = len(self.paths)
        for i, p in enumerate(self.paths):
            is_ok = check_integrity(p)
            if not is_ok: results[p] = 5
            else:
                target = os.path.splitext(p)[0] + ".cbz"; groups.setdefault(target, []).append(p)
            self.progress.emit(i+1, total)
        
        dupes_count = 0
        for t, ps in groups.items():
            if len(ps) > 1:
                ps.sort(key=lambda x: 1 if x.lower().endswith('.cbz') else 0, reverse=True)
                for loser in ps[1:]:
                    if loser not in results:
                        results[loser] = 4
                        dupes_count += 1
        self.finished.emit(results, dupes_count)

class ProcessingWorker(QThread):
    progress_val = pyqtSignal(int); progress_max = pyqtSignal(int); status_msg = pyqtSignal(str)
    ask_permission = pyqtSignal(str, str, int, int); file_finished = pyqtSignal(str, str, int); finished = pyqtSignal()
    def __init__(self, tasks, to_webp=False):
        super().__init__(); self.tasks = tasks; self.to_webp = to_webp
        self._is_running = True; self._stop_after_current = False
        self._mutex = QMutex(); self._condition = QWaitCondition(); self._permission_result = None
    def set_permission(self, res):
        with QMutexLocker(self._mutex): self._permission_result = res; self._condition.wakeAll()
    def abort_now(self): self._is_running = False
    def stop_later(self): self._stop_after_current = True
    def run(self):
        processed = set(); total_p = sum(len(t[1]) for t in self.tasks); self.progress_max.emit(total_p); curr_p = 0
        for task in self.tasks:
            if not self._is_running or self._stop_after_current: break
            orig_p, img_list, tmp_src = task[0], task[1], task[2] if len(task)>2 else None
            final_p = os.path.splitext(orig_p)[0] + ".cbz"
            if (os.path.exists(final_p) and os.path.normpath(orig_p) != os.path.normpath(final_p)) or (final_p in processed):
                self._permission_result = None
                self.ask_permission.emit(orig_p, final_p, len(img_list), len(get_archive_file_list(final_p)) if os.path.exists(final_p) else 0)
                with QMutexLocker(self._mutex):
                    while self._permission_result is None: self._condition.wait(self._mutex)
                if self._permission_result == 'skip':
                    curr_p += len(img_list); self.progress_val.emit(curr_p); (shutil.rmtree(tmp_src) if tmp_src else None); self.file_finished.emit(orig_p, orig_p, 4); continue
                if self._permission_result == 'rename':
                    base, ext = os.path.splitext(final_p); c = 1
                    while os.path.exists(f"{base}_{c}{ext}") or f"{base}_{c}{ext}" in processed: c += 1
                    final_p = f"{base}_{c}{ext}"
            processed.add(final_p); out = tempfile.mkdtemp(); tmp_zip = final_p + ".tmp"
            try:
                for i, p in enumerate(img_list):
                    if not self._is_running: return
                    curr_p += 1; self.status_msg.emit(f"Ottimizzazione: {os.path.basename(orig_p)} ({i+1}/{len(img_list)})"); self.progress_val.emit(curr_p)
                    ext = ".webp" if self.to_webp else os.path.splitext(p)[1].lower() or ".jpg"
                    dst = os.path.join(out, f"{i+1:04d}{ext}")
                    if self.to_webp:
                        with Image.open(p) as img:
                            if img.mode in ("RGBA", "P", "LA"): img = img.convert("RGB")
                            img.save(dst, "WEBP", quality=85)
                    else: shutil.copy2(p, dst)
                with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_STORED) as z:
                    for f in sorted(os.listdir(out)): z.write(os.path.join(out, f), f)
                if os.path.exists(final_p): os.remove(final_p)
                if os.path.exists(orig_p) and os.path.normpath(orig_p) != os.path.normpath(final_p): os.remove(orig_p)
                shutil.move(tmp_zip, final_p); self.file_finished.emit(orig_p, final_p, 3 if self.to_webp else 2)
            except: pass
            finally: 
                if os.path.exists(out): shutil.rmtree(out)
                if os.path.exists(tmp_zip): os.remove(tmp_zip)
                if tmp_src and os.path.exists(tmp_src): shutil.rmtree(tmp_src)
        self.finished.emit()

class ThumbWorker(QThread):
    done = pyqtSignal(str, QPixmap)
    def __init__(self, path): super().__init__(); self.path = path
    def run(self):
        imgs = get_archive_file_list(self.path)
        if not imgs: return
        with tempfile.TemporaryDirectory() as tmp:
            if self.path.lower().endswith('.pdf'):
                try:
                    doc = fitz.open(self.path); page = doc.load_page(0); pix = page.get_pixmap(); img_p = os.path.join(tmp, "t.png"); pix.save(img_p); doc.close()
                except: return
            else:
                subprocess.run(['unrar', 'e', '-y', self.path, imgs[0], tmp + "/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not os.listdir(tmp): subprocess.run(['7z', 'e', '-y', f'-o{tmp}', self.path, imgs[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for f in os.listdir(tmp):
                if not is_junk_file(f):
                    pix = QPixmap(); 
                    if pix.load(os.path.join(tmp, f)): self.done.emit(self.path, pix); return

class LoadingWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, str, list); error = pyqtSignal(str)
    def __init__(self, path): super().__init__(); self.path = path
    def run(self):
        tmp = tempfile.mkdtemp(); ext = os.path.splitext(self.path)[1].lower(); success = False
        img_list = get_archive_file_list(self.path)
        total = len(img_list)
        if not img_list: shutil.rmtree(tmp); self.error.emit("Archivio vuoto."); return

        if ext == '.pdf' and HAS_PDF:
            try:
                doc = fitz.open(self.path)
                for i in range(total):
                    page = doc.load_page(i); pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    pix.save(os.path.join(tmp, f"{i+1:04d}.png")); self.progress.emit(i+1, total)
                doc.close(); success = True
            except: success = False
        else:
            try:
                for i, img_name in enumerate(img_list):
                    if self.path.lower().endswith('.cbz') or self.path.lower().endswith('.zip'):
                        with zipfile.ZipFile(self.path, 'r') as z:
                            z.extract(img_name, tmp)
                    else:
                        subprocess.run(['7z', 'e', '-y', f'-o{tmp}', self.path, img_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.progress.emit(i+1, total)
                success = True
            except: success = False

        if success:
            extracted = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(os.path.join(r, f))]
            extracted.sort(key=get_natural_sort_key)
            self.finished.emit(self.path, tmp, extracted)
        else: shutil.rmtree(tmp); self.error.emit("Errore durante l'estrazione.")

class BatchPrepWorker(QThread):
    progress = pyqtSignal(int, int); ready = pyqtSignal(list, bool)
    def __init__(self, paths, to_webp): super().__init__(); self.paths = paths; self.to_webp = to_webp
    def run(self):
        tasks = []; total = len(self.paths)
        for i, p in enumerate(self.paths):
            tmp = tempfile.mkdtemp(); ext = os.path.splitext(p)[1].lower()
            img_list = get_archive_file_list(p)
            if ext == '.pdf' and HAS_PDF:
                doc = fitz.open(p)
                for j in range(len(doc)):
                    page = doc.load_page(j); pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8)); pix.save(os.path.join(tmp, f"{j+1:04d}.png"))
                doc.close()
            else: subprocess.run(['7z', 'x', '-y', f'-o{tmp}', p], stdout=subprocess.DEVNULL)
            extracted = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not is_junk_file(os.path.join(r, f))]
            extracted.sort(key=get_natural_sort_key)
            if extracted: tasks.append((p, extracted, tmp))
            else: shutil.rmtree(tmp)
            self.progress.emit(i+1, total)
        self.ready.emit(tasks, self.to_webp)

# --- UI ---

class ComicCard(QFrame):
    edit_requested = pyqtSignal(str); repair_requested = pyqtSignal(str); remove_requested = pyqtSignal(str); trash_requested = pyqtSignal(str); selection_changed = pyqtSignal(object, object)
    def __init__(self, path):
        super().__init__(); self.file_path = path; self.setFixedSize(195, 385); self.status_code = -1; self.selected = False; self.update_style()
        l = QVBoxLayout(self); l.setContentsMargins(0,0,0,5)
        self.status = QLabel("..."); self.status.setAlignment(Qt.AlignmentFlag.AlignCenter); l.addWidget(self.status)
        self.thumb = QLabel("..."); self.thumb.setFixedSize(175, 230); self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_badge = QLabel("-", self.thumb); self.page_badge.setFixedWidth(175); self.page_badge.setFixedHeight(24); self.page_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_badge.setStyleSheet("background: rgba(0, 229, 255, 180); color: black; font-weight: 900; font-size: 11px; border-top: 1px solid white; border-bottom: 1px solid white;"); self.page_badge.move(0, 105)
        l.addWidget(self.thumb); self.name = QLabel(os.path.basename(path)); self.name.setWordWrap(True); self.name.setStyleSheet("font-size: 9px; color: #eee;"); self.name.setMaximumHeight(35); l.addWidget(self.name)
        btns = QHBoxLayout(); btns.setSpacing(2); self.btn_e = QPushButton("Edita"); self.btn_e.clicked.connect(lambda: self.edit_requested.emit(self.file_path))
        self.btn_r = QPushButton("Fix"); self.btn_r.setStyleSheet("background: #e65100; color: white;"); self.btn_d = QPushButton("X"); self.btn_d.setFixedWidth(30); self.btn_d.setStyleSheet("background: #b71c1c; color: white;"); self.btn_d.clicked.connect(lambda: self.remove_requested.emit(self.file_path))
        btns.addWidget(self.btn_e); btns.addWidget(self.btn_r); btns.addWidget(self.btn_d); l.addLayout(btns)
    def set_pages(self, c): self.page_badge.setText(f"{c} PAGINE")
    def update_style(self):
        b, bg = ("2px solid #00e5ff", "#3a3a3a") if self.selected else ("1px solid #444", "#2a2a2a")
        self.setStyleSheet(f"ComicCard {{ background: {bg}; border-radius: 10px; border: {b}; }}")
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.selected = not self.selected; self.update_style(); self.selection_changed.emit(self, e.modifiers())
    def set_status(self, code):
        self.status_code = code
        st = {0: ("DA SISTEMARE", "#b71c1c", "white"), 1: ("OK", "#1b5e20", "#a5d6a7"), 2: ("RIPARATO", "#fbc02d", "black"), 3: ("CONVERTITO", "#00c853", "white"), 4: ("SALTATO", "#455a64", "white"), 5: ("DANNEGGIATO", "#000000", "#ff1744")}
        txt, bg, fg = st.get(code, ("...", "#555", "white"))
        self.status.setText(txt); self.status.setStyleSheet(f"background: {bg}; color: {fg}; font-weight: bold; padding: 4px; border-top-left-radius: 10px; border-top-right-radius: 10px;")
        if code == 4:
            self.btn_r.setText("Dupe"); self.btn_r.setStyleSheet("background: #546e7a; color: white;")
            try: self.btn_r.clicked.disconnect()
            except: pass
            self.btn_r.clicked.connect(lambda: self.trash_requested.emit(self.file_path))
        else:
            self.btn_r.setText("Fix"); self.btn_r.setStyleSheet("background: #e65100; color: white;")
            try: self.btn_r.clicked.disconnect()
            except: pass
            self.btn_r.clicked.connect(lambda: self.repair_requested.emit(self.file_path))
    def set_pixmap(self, pix): self.thumb.setPixmap(pix.scaled(175, 230, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
    def mouseDoubleClickEvent(self, e): self.edit_requested.emit(self.file_path)

class AdvancedEditor(QDialog):
    def __init__(self, file_path, temp_dir, image_list, parent=None):
        super().__init__(parent); self.file_path = file_path; self.temp_dir = temp_dir; self.page_widgets = []; self.setWindowTitle(f"Editor: {os.path.basename(file_path)}"); self.setMinimumSize(1100, 850)
        v = QVBoxLayout(self); self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.grid_c = QWidget(); self.grid_l = QGridLayout(self.grid_c); self.scroll.setWidget(self.grid_c); v.addWidget(self.scroll)
        btns = QHBoxLayout(); b_can = QPushButton("ANNULLA"); b_can.setFixedSize(140, 45); b_can.setStyleSheet("background: #b71c1c; color: white;"); b_can.clicked.connect(self.reject)
        b_add = QPushButton("AGGIUNGI"); b_add.setFixedSize(160, 45); b_add.setStyleSheet("background: #0277bd; color: white;"); b_add.clicked.connect(self.add_ext)
        b_sav = QPushButton("SALVA"); b_sav.setFixedSize(220, 45); b_sav.setStyleSheet("background: #2e7d32; color: white; font-weight: bold;"); b_sav.clicked.connect(self.accept)
        btns.addWidget(b_can); btns.addStretch(); btns.addWidget(b_add); btns.addStretch(); btns.addWidget(b_sav); v.addLayout(btns)
        for i, p in enumerate(image_list): self.add_page(p, i+1)
        self.refresh()
    def add_page(self, p, pos):
        w = QFrame(); w.setFixedSize(160, 280); w.setStyleSheet("background: #333; border-radius: 5px;"); l = QVBoxLayout(w)
        btn_del = QPushButton("X"); btn_del.setFixedSize(20,20); btn_del.setStyleSheet("background:red; color:white; font-size:9px;"); btn_del.clicked.connect(lambda: (self.page_widgets.remove(w), w.deleteLater(), self.refresh())); l.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignRight)
        img = QLabel(); img.setFixedSize(140, 175); pix = QPixmap(p); img.setPixmap(pix.scaled(140, 175, Qt.AspectRatioMode.KeepAspectRatio)); l.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)
        sp = NoWheelSpinBox(); sp.setRange(1, 9999); sp.setValue(pos); sp.editingFinished.connect(lambda: self.reorder(w)); l.addWidget(sp); w.path = p; w.spin = sp; self.page_widgets.append(w)
    def add_ext(self):
        fs, _ = QFileDialog.getOpenFileNames(self, "Aggiungi", "", "Immagini (*.jpg *.png *.webp)")
        for f in fs: dst = os.path.join(self.temp_dir, f"ext_{os.path.basename(f)}"); shutil.copy2(f, dst); self.add_page(dst, len(self.page_widgets)+1)
        self.refresh()
    def reorder(self, moved_w):
        target_idx = max(0, min(moved_w.spin.value() - 1, len(self.page_widgets) - 1))
        self.page_widgets.remove(moved_w); self.page_widgets.insert(target_idx, moved_w); self.refresh()
    def refresh(self):
        for i in reversed(range(self.grid_l.count())): (self.grid_l.itemAt(i).widget().setParent(None) if self.grid_l.itemAt(i).widget() else None)
        for i, w in enumerate(self.page_widgets):
            w.spin.blockSignals(True); w.spin.setValue(i+1); w.spin.blockSignals(False); self.grid_l.addWidget(w, i//6, i%6)
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.focusWidget(): self.focusWidget().clearFocus()
            return
        super().keyPressEvent(e)
    def get_paths(self): return [w.path for w in self.page_widgets]

# --- MAIN WINDOW ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComicOptimizer v2.1.5")
        self.setFixedSize(1350, 1050)
        self.setAcceptDrops(True)
        self.cards = {}
        self.last_clicked = None
        self.active_threads = set()
        self.current_worker = None
        self.skip_trash_confirm = False
        self.init_ui()
        self.check_deps()
        
        frasi = [
            "Il mio processore scalpita...",
            "Pronto a triturare PDF e immagini.",
            "Caffè caricato, iniziamo?",
            "I tuoi fumetti sono in buone mani.",
            "Ottimizzazione? È il mio secondo nome."
        ]
        self.ironic_lbl.setText(random.choice(frasi))

    def check_deps(self):
        m = []
        if not shutil.which('7z'): m.append("p7zip-full")
        if not shutil.which('unrar'): m.append("unrar")
        if not HAS_PDF: m.append("python3-pymupdf")
        if m: QMessageBox.warning(self, "Dipendenze", "Mancano: " + ", ".join(m) + "\n\nsudo apt install p7zip-full unrar\npip install pymupdf")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        title = QLabel("ComicOptimizer, by Shuren")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 34px; font-weight: 900; color: #00e5ff; padding: 10px; background: #1a1a1a; border-bottom: 2px solid #00d4ff;")
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
        idle_w = QWidget(); idle_l = QVBoxLayout(idle_w); idle_l.setContentsMargins(0,0,0,0); idle_l.setSpacing(2)
        self.hint_lbl = QLabel("Clicca sulle card per selezionarle (Ctrl e Shift supportati)")
        self.hint_lbl.setStyleSheet("color: #00e5ff; font-size: 11px; font-weight: bold")
        self.ironic_lbl = QLabel("Pronto ad operare."); self.ironic_lbl.setStyleSheet("color: #aaa; font-style: italic")
        idle_l.addWidget(self.hint_lbl); idle_l.addWidget(self.ironic_lbl); self.status_stack.addWidget(idle_w)
        
        work_w = QWidget(); work_l = QHBoxLayout(work_w); work_l.setContentsMargins(0,0,0,0); work_l.setSpacing(10)
        vl = QVBoxLayout(); vl.setSpacing(2)
        self.pbar = QProgressBar(); self.pbar.setFixedHeight(18); self.pbar.setStyleSheet("QProgressBar { border: 1px solid #00e5ff; border-radius: 5px; text-align: center; color: white; font-weight: bold; } QProgressBar::chunk { background: #00e5ff; }")
        self.status_msg = QLabel("Lavorando..."); self.status_msg.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 12px")
        vl.addWidget(self.status_msg); vl.addWidget(self.pbar); work_l.addLayout(vl, 1)
        self.btn_stop = QPushButton("STOP"); self.btn_stop.setFixedSize(80, 40); self.btn_stop.setStyleSheet("background: #b71c1c; color: white; font-weight: bold;"); self.btn_stop.clicked.connect(self.request_stop)
        work_l.addWidget(self.btn_stop); self.status_stack.addWidget(work_w)
        
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
        self.n_btn = QPushButton("Novità v2.0"); self.n_btn.setStyleSheet(ls); self.n_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.n_btn.clicked.connect(self.show_news)
        self.c_btn = QPushButton("Credits"); self.c_btn.setStyleSheet(ls); self.c_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.c_btn.clicked.connect(self.show_credits)
        self.p_btn = QPushButton("Privacy"); self.p_btn.setStyleSheet(ls); self.p_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.p_btn.clicked.connect(self.show_privacy)
        footer.addWidget(self.n_btn); footer.addStretch(); footer.addWidget(self.c_btn); footer.addStretch(); footer.addWidget(self.p_btn)
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
        msg.setText(f"Il file <b>{os.path.basename(final_p)}</b> esiste già.<br><br>Disco: {p_old} pag. | Nuovo: {p_new} pag.")
        b_o = msg.addButton("Sovrascrivi", QMessageBox.ButtonRole.AcceptRole)
        b_r = msg.addButton("Rinomina", QMessageBox.ButtonRole.ActionRole)
        b_s = msg.addButton("Salta", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        res = "skip"
        if msg.clickedButton() == b_o: res = "overwrite"
        elif msg.clickedButton() == b_r: res = "rename"
        if self.current_worker: self.current_worker.set_permission(res)

    def confirm_and_trash(self, path):
        if self.skip_trash_confirm:
            self.trash_file(path)
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Rilevato Duplicato")
        msg.setText(f"Vuoi spostare questo duplicato nel cestino?\n\nFile: {os.path.basename(path)}")
        cb = QCheckBox("Non mostrare più questo avviso")
        msg.setCheckBox(cb)
        b_yes = msg.addButton("Sposta nel Cestino", QMessageBox.ButtonRole.AcceptRole)
        b_no = msg.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        
        if msg.clickedButton() == b_yes:
            if cb.isChecked(): self.skip_trash_confirm = True
            self.trash_file(path)

    def run_analysis(self, auto=True):
        if not self.cards: 
            self.btn_trash_dupes.setVisible(False)
            return
        self.set_working(True, "Analisi...")
        aw = AnalysisWorker(list(self.cards.keys()))
        aw.progress.connect(lambda v, t: self.set_working(True, f"Analisi: {v}/{t}", v, t))
        def done(res, d):
            self.active_threads.discard(aw)
            self.set_working(False)
            for p, s in res.items():
                if p in self.cards: self.cards[p].set_status(s)
            self.btn_trash_dupes.setVisible(d > 0)
            if not auto and d == 0 and not any(s == 5 for s in res.values()):
                QMessageBox.information(self, "Analisi", "Tutto in ordine!")
            self.refresh_grid()
        aw.finished.connect(done); aw.start(); self.active_threads.add(aw)

    def start_processing(self, tasks, to_webp=False):
        self.set_working(True, "Ottimizzazione...")
        self.current_worker = ProcessingWorker(tasks, to_webp)
        self.current_worker.status_msg.connect(self.status_msg.setText)
        self.current_worker.progress_max.connect(self.pbar.setMaximum)
        self.current_worker.progress_val.connect(self.pbar.setValue)
        self.current_worker.ask_permission.connect(self.handle_conflict)
        self.current_worker.file_finished.connect(self.on_file_done)
        self.current_worker.finished.connect(lambda: (self.reset_ui(), self.run_analysis(True)))
        self.active_threads.add(self.current_worker); self.current_worker.start()

    def reset_ui(self):
        for p in list(self.cards.keys()):
            self.cards[p].selected = False; self.cards[p].update_style()
        self.btn_sel.setVisible(False); self.btn_trash_sel.setVisible(False)
        has_dupes = any(c.status_code == 4 for c in self.cards.values())
        self.btn_trash_dupes.setVisible(has_dupes)
        self.last_clicked = None; self.set_working(False)

    def show_news(self):
        msg = ("<b>⚡ ComicOptimizer 2.0: Il Grande Salto!</b><br><br>"
               "La tua collezione di fumetti non è mai stata così in forma.<br><br>"
               "&nbsp;&nbsp;🆕 <b>Benvenuti PDF!</b> Converti i tuoi PDF in .cbz con un clic.<br>"
               "&nbsp;&nbsp;🚀 <b>Turbo Mode:</b> Motore più veloce e leggero.<br>"
               "&nbsp;&nbsp;🎯 <b>Ordine Totale:</b> Gestione fluida senza blocchi.")
        QMessageBox.information(self, "Novità v2.0", msg)

    def show_credits(self):
        msg = "<b>Creatore:</b> Michele Shuren Bancheri<br><br>Sviluppato per amore dei fumetti."
        QMessageBox.information(self, "Credits", msg)

    def show_privacy(self):
        msg = "<b>Privacy 100% Locale</b><br><br>I tuoi file non lasciano mai il tuo computer."
        QMessageBox.information(self, "Privacy", msg)

    def handle_selection(self, card, mod):
        cards = [self.grid_l.itemAt(i).widget() for i in range(self.grid_l.count()) if self.grid_l.itemAt(i).widget()]
        if mod & Qt.KeyboardModifier.ShiftModifier and self.last_clicked:
            idx1, idx2 = cards.index(self.last_clicked), cards.index(card)
            for i in range(min(idx1, idx2), max(idx1, idx2) + 1):
                cards[i].selected = True; cards[i].update_style()
        self.last_clicked = card
        sel_n = len([c for c in cards if c.selected])
        self.btn_sel.setVisible(sel_n > 0); self.btn_trash_sel.setVisible(sel_n > 0)

    def on_file_done(self, o, n, s):
        if o in self.cards:
            c = self.cards.pop(o); c.file_path = n; c.name.setText(os.path.basename(n)); c.set_status(s)
            flist = get_archive_file_list(n); c.set_pages(len(flist))
            self.cards[n] = c; self.load_t(n)

    def import_files(self, paths):
        self.set_working(False)
        for p, count in paths:
            if p not in self.cards:
                c = ComicCard(p); c.set_pages(count)
                c.selection_changed.connect(self.handle_selection)
                c.edit_requested.connect(self.open_editor)
                c.repair_requested.connect(self.individual_repair)
                c.remove_requested.connect(self.rem)
                c.trash_requested.connect(self.confirm_and_trash)
                self.cards[p] = c; self.load_t(p); c.set_status(self.check_status(p))
        self.refresh_grid(); self.run_analysis(True)

    def trash_file(self, p): 
        if subprocess.run(['gio', 'trash', p]).returncode == 0: self.rem(p)

    def trash_selected(self):
        sel = [p for p, c in self.cards.items() if c.selected]
        if sel and QMessageBox.question(self, "Cestina", f"Spostare {len(sel)} file nel cestino?") == QMessageBox.StandardButton.Yes:
            for p in sel: self.trash_file(p)
            self.reset_ui()

    def trash_all_duplicates(self):
        dupes = [p for p, c in self.cards.items() if c.status_code == 4]
        if dupes and QMessageBox.question(self, "Cestina", "Eliminare i duplicati?") == QMessageBox.StandardButton.Yes:
            for p in dupes: self.trash_file(p)
            self.reset_ui()

    def repair_selected(self):
        m = self.ask_mode()
        if m != "cancel":
            targets = [p for p, c in self.cards.items() if c.selected]
            self.set_working(True, "Preparazione..."); bw = BatchPrepWorker(targets, m == "convert")
            bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
            bw.ready.connect(lambda t, mv: (self.active_threads.discard(bw), self.start_processing(t, mv)))
            bw.start(); self.active_threads.add(bw)

    def repair_all_trigger(self):
        m = self.ask_mode()
        if m == "cancel": return
        if m == "convert": targets = [p for p, c in self.cards.items() if c.status_code not in (4, 5)]
        else: targets = [p for p, c in self.cards.items() if c.status_code in (0, 1)]
        
        if not targets:
            QMessageBox.information(self, "Ottimizzazione", "Nessun file idoneo trovato.")
            return

        self.set_working(True, "Preparazione..."); bw = BatchPrepWorker(targets, m == "convert")
        bw.progress.connect(lambda v, t: self.set_working(True, f"Estrazione: {v}/{t}", v, t))
        bw.ready.connect(lambda t, mv: (self.active_threads.discard(bw), self.start_processing(t, mv)))
        bw.start(); self.active_threads.add(bw)

    def ask_mode(self):
        msg = QMessageBox(self); msg.setWindowTitle("Ottimizzazione"); msg.setText("Scegli la modalità:")
        b_c = msg.addButton("Converti WebP", QMessageBox.ButtonRole.AcceptRole)
        b_r = msg.addButton("Solo Ripara", QMessageBox.ButtonRole.ActionRole)
        b_a = msg.addButton("Annulla", QMessageBox.ButtonRole.RejectRole); msg.exec()
        if msg.clickedButton() == b_c: return "convert"
        if msg.clickedButton() == b_r: return "repair"
        return "cancel"

    def open_editor(self, path):
        self.set_working(True, "Apertura..."); l = LoadingWorker(path)
        l.progress.connect(lambda v, t: self.set_working(True, f"Apertura: Pagina {v}/{t}...", v, t))
        def done(p, t, i):
            self.set_working(False); self.active_threads.discard(l); dlg = AdvancedEditor(p, t, i, self)
            if dlg.exec(): self.start_processing([(p, dlg.get_paths(), t)], to_webp=False)
            else: shutil.rmtree(t)
        l.finished.connect(done); l.error.connect(lambda: self.set_working(False)); l.start(); self.active_threads.add(l)

    def individual_repair(self, path):
        m = self.ask_mode()
        if m != "cancel":
            self.set_working(True, "Preparazione..."); bw = BatchPrepWorker([path], m == "convert")
            bw.ready.connect(lambda t, mv: (self.active_threads.discard(bw), self.start_processing(t, mv)))
            bw.start(); self.active_threads.add(bw)

    def request_stop(self):
        if self.current_worker:
            dlg = StopDialog(self); r = dlg.exec()
            if r == 1: self.current_worker.abort_now(); self.reset_ui()
            elif r == 2: self.current_worker.stop_later()

    def check_status(self, p):
        if p.lower().endswith('.pdf'): return 0
        if not p.lower().endswith('.cbz'): return 0
        try:
            with zipfile.ZipFile(p, 'r') as z:
                imgs = [n for n in z.namelist() if n.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                return 3 if imgs and all(n.lower().endswith('.webp') for n in imgs) else 1
        except: return 0

    def load_t(self, p):
        w = ThumbWorker(p)
        w.done.connect(lambda path, pix: (self.active_threads.discard(w), self.cards[path].set_pixmap(pix) if path in self.cards else None))
        w.start(); self.active_threads.add(w)

    def clear_all(self):
        for p in list(self.cards.keys()): self.cards[p].deleteLater()
        self.cards.clear(); self.refresh_grid(); self.reset_ui()
        self.btn_trash_dupes.setVisible(False)

    def refresh_grid(self):
        for i in reversed(range(self.grid_l.count())):
            w = self.grid_l.itemAt(i).widget()
            if w: w.setParent(None)
        for i, p in enumerate(sorted(self.cards.keys(), key=get_natural_sort_key)):
            self.grid_l.addWidget(self.cards[p], i//6, i%6)

    def rem(self, p):
        if p in self.cards: self.cards.pop(p).deleteLater(); self.refresh_grid()

    def set_drop_style(self, a): 
        self.drop_zone.setStyleSheet(f"border: {4 if a else 3}px dashed {'#00e5ff' if a else '#444'}; border-radius: 15px; background: {'#2c3e50' if a else '#111'}; color: {'#00e5ff' if a else '#555'}; font-size: 18px; font-weight: bold;")
    
    def dragEnterEvent(self, e): 
        if e.mimeData().hasUrls(): e.accept()
        self.set_drop_style(True)
    
    def dragLeaveEvent(self, e): 
        self.set_drop_style(False)
    
    def dropEvent(self, e):
        self.set_drop_style(False); urls = [u.toLocalFile() for u in e.mimeData().urls()]
        if urls:
            self.set_working(True, "Scansione..."); iw = ImportWorker(urls)
            iw.progress.connect(lambda v, t: self.set_working(True, f"Importazione: {v}/{t}", v, t))
            iw.finished.connect(lambda p: (self.active_threads.discard(iw), self.import_files(p)))
            iw.start(); self.active_threads.add(iw)

if __name__ == "__main__":
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    try:
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Errore critico: {e}")
