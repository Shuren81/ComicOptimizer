"""Funzioni di utilità: cestino, 7z/unrar, nomi, cartelle temporanee, formattazione."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .config import IS_WIN, RES_DIR, TMP_PREFIX
from .logsetup import log


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

# --- WORKERS ---

_ARCHIVE_EXTS = ('.cbz', '.cbr', '.zip', '.rar', '.pdf')

_IMAGE_EXTS   = _PAGE_EXTS
