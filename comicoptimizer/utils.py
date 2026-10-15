"""Funzioni di utilità: cestino, 7z/unrar, nomi, cartelle temporanee, formattazione."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .config import IS_MAC, IS_WIN, RES_DIR, TMP_PREFIX
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
    if IS_MAC:
        # sul Mac 7-Zip si chiama 7zz; un'app aperta dal Finder non ha Homebrew nel PATH
        names = [name, "7zz"] if name == "7z" else [name]
        candidates += [shutil.which(n) for n in names[1:]]
        candidates += [os.path.join(d, n) for d in ("/opt/homebrew/bin", "/usr/local/bin") for n in names]
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

_JUNK_NAMES = (".ds_store", "thumbs.db", "ehthumbs.db", "desktop.ini")

def is_junk_file(path):
    name = os.path.basename(path)
    return name.startswith("._") or name.lower() in _JUNK_NAMES or "__macosx" in path.lower()

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

# --- CARTELLE DI SOLE IMMAGINI ---

def is_image_folder(folder):
    """True se la cartella (sottocartelle comprese) contiene solo immagini.
    Spazzatura e ComicInfo.xml non contano; senza nessuna immagine è False."""
    has_page = False
    for r, _, fs in os.walk(folder):
        for f in fs:
            full = os.path.join(r, f)
            if is_page_file(full):
                has_page = True
            elif not (is_junk_file(full) or is_comicinfo(f)):
                return False
    return has_page

def list_folder_pages(folder, loose_last=False):
    """
    Pagine di una cartella di sole immagini, in ordine naturale e in profondità:
    prima le immagini della cartella, poi ogni sottocartella (e così via).
    `loose_last` mette le immagini sciolte della cartella principale in fondo.
    """
    pages, subs = [], []
    for e in sorted(os.scandir(folder), key=lambda e: get_natural_sort_key(e.name)):
        if e.is_dir():
            if not is_junk_file(e.path):
                subs += list_folder_pages(e.path)
        elif is_page_file(e.path):
            pages.append(e.path)
    return subs + pages if loose_last else pages + subs

def folder_subdirs(folder, pages):
    """Sottocartelle (relative) da cui vengono le pagine, nell'ordine delle pagine."""
    dirs = dict.fromkeys(os.path.relpath(os.path.dirname(p), folder) for p in pages)
    return [d for d in dirs if d != "."]

def folder_has_loose_and_subs(folder):
    """True se la cartella ha sia immagini sciolte sia sottocartelle con immagini."""
    pages = list_folder_pages(folder)
    loose = sum(1 for p in pages if os.path.dirname(p) == folder)
    return 0 < loose < len(pages)

def folder_comicinfo(folder):
    """ComicInfo.xml della sola cartella principale (quelli nelle sottocartelle si ignorano)."""
    return next((e.path for e in os.scandir(folder) if e.is_file() and is_comicinfo(e.name)), None)

def path_size(path):
    """Dimensione di un file, o di tutti i file di una cartella."""
    if os.path.isdir(path):
        return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)
    return os.path.getsize(path)

def cbz_target(path):
    """CBZ di destinazione: accanto all'originale (per una cartella: 'cartella.cbz')."""
    # una cartella non ha estensione: "Vol. 2" non deve diventare "Vol.cbz"
    return path + ".cbz" if os.path.isdir(path) else os.path.splitext(path)[0] + ".cbz"

_CHAPTER_TAIL = re.compile(
    r'(?:[\s._#-]*\b(?:cap(?:itolo)?|ch(?:apter)?|vol(?:ume)?|n[or]?|ep)\b)?[\s._#(\[-]*\d*$', re.I)

def merge_name_hint(paths):
    """Nome suggerito per l'unione: la parte comune dei nomi, senza il numero del capitolo."""
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    common = _CHAPTER_TAIL.sub("", os.path.commonprefix(stems)).strip(" -_.#([")
    return common or stems[0]

# --- RINOMINA ---

_BAD_CHARS = re.compile(r'[\\/:*?"<>|]')

def clean_filename(name):
    """Nome di file valido su ogni sistema: i caratteri vietati diventano '_'."""
    return _BAD_CHARS.sub("_", name).strip()

# "-" con spazi o "_" almeno da un lato: "Spider-Man" resta una parte sola
_PART_SEP = re.compile(r'[\s_]+-[\s_]*|[\s_]*-[\s_]+')
_SCHEMA_TOKEN = re.compile(r'<(nome|num|n|parte(\d+))>')

def apply_schema(stem, schema, n, digits):
    """
    Nuovo nome da uno schema con <nome> (nome attuale), <num> (primo numero
    del nome), <n> (progressivo) e <parte1>, <parte2>… (pezzi separati da " - ").
    Solleva ValueError se nel nome manca il numero o la parte richiesta.
    """
    parts = _PART_SEP.split(stem)

    def sub(m):
        key = m.group(1)
        if key == "nome":
            return stem
        if key == "n":
            return str(n).zfill(digits)
        if key == "num":
            found = re.search(r'\d+', stem)
            if not found:
                raise ValueError("numero non trovato")
            return found.group().lstrip("0").zfill(digits)
        i = int(m.group(2))
        if not 1 <= i <= len(parts) or not parts[i - 1]:
            raise ValueError(f"parte {i} mancante")
        return parts[i - 1]

    return _SCHEMA_TOKEN.sub(sub, schema)

def underscores_to_spaces(s):
    return re.sub(r" {2,}", " ", s.replace("_", " ")).strip()

def capitalize_words(s):
    """Maiuscola la prima lettera di ogni parola, senza abbassare le altre (DC resta DC)."""
    return re.sub(r"(^|[\s(\[\"-])(\w)", lambda m: m.group(1) + m.group(2).upper(), s)

def split_name(path):
    """(nome senza estensione, estensione); una cartella non ha estensione."""
    name = os.path.basename(path)
    return (name, "") if os.path.isdir(path) else os.path.splitext(name)

def rename_problem(old, new_path, taken):
    """Perché `old` non si può rinominare in `new_path` (None se si può).
    `taken` = destinazioni già scelte per le righe precedenti (normcase)."""
    if os.path.normcase(new_path) in taken:
        return "nome ripetuto"
    if os.path.exists(new_path) and not os.path.samefile(old, new_path):
        return "esiste già"
    return None

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
