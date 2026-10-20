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


def _is_network_path(path):
    """Windows: file su un disco di rete (NAS, unità mappata, \\\\server\\…), che non ha cestino."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(root) == 4          # DRIVE_REMOTE
    except Exception as e:
        log.warning(f"Tipo di disco non riconosciuto per '{path}': {e}")
        return True                                   # nel dubbio non si cestina: il file resta


# --- TRASH HELPER (cross-platform) FIX #2 ---
def _trash_file_cross_platform(path):
    """
    Sposta il file nel cestino in modo cross-platform.
    Prova send2trash se disponibile, altrimenti fallback per piattaforma.
    False se non si può: il file resta dov'è (mai cancellazioni definitive).
    """
    # su un disco di rete Windows "cestina" cancellando per sempre e in silenzio
    if _is_network_path(path):
        log.warning(f"Disco di rete senza cestino: '{path}' resta al suo posto")
        return False
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
            # il percorso va come argomento, mai dentro il testo dello script (nomi con " o comandi)
            res = subprocess.run(['osascript', '-e', 'on run argv',
                                  '-e', 'tell application "Finder" to delete POSIX file (item 1 of argv)',
                                  '-e', 'end run', path], capture_output=True, timeout=10)
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
# numero "staccato" (anche con # davanti): "titolo 43 sottotitolo"; "X-Men2" e "Vol.3" non dividono
# anche tra quadre ("[01]"); le tonde no: "(2016)" è un anno o un'etichetta
_NUM_PART = re.compile(r'[\s_]*(?<![^\s_])(?:#?(\d+)|\[(\d+)\])(?![^\s_])[\s_]*')
# campi scritti a mano nella finestra (non si ricavano dal nome del file) e il loro segnaposto corto
FREE_FIELDS = ("autore", "editore", "edizione", "lingua")
FIELD_TAGS = {"autore": "aut", "editore": "pub", "edizione": "edz", "lingua": "lang"}
_FIELD_OF = {**{f: f for f in FREE_FIELDS}, **{t: f for f, t in FIELD_TAGS.items()}}
# <segnaposto> oppure <segnaposto:cifre>, es. <p4:1> (cifre solo per quel segnaposto).
# Valgono anche le forme lunghe di prima (<parte1>, <autore>…): gli schemi salvati restano validi.
_SCHEMA_TOKEN = re.compile(
    r'<(nome|num|n|anno|tit(?:olo)?|sott(?:otitolo)?|aut(?:ore)?|pub|editore|edz|edizione|lang|lingua|(?:parte|p)(\d+))'
    r'(?::(\d))?>')
# ruoli che si marcano col mouse nel nome (oltre a p1, p2…) e il segnaposto che inseriscono
ROLE_TAGS = {"titolo": "tit", "num": "num", "sottotitolo": "sott", "anno": "anno", **FIELD_TAGS}
_YEAR_PAREN = re.compile(r'\((19\d\d|20\d\d)\)')
_YEAR = re.compile(r'(?<!\d)(19\d\d|20\d\d)(?!\d)')

def name_spans(stem, split_numbers=True):
    """(inizio, fine) dei pezzi del nome: separati da " - " e, con `split_numbers`,
    anche dai numeri staccati (di "#12" e "[12]" il pezzo è solo "12")."""
    spans, pos = [], 0
    for sep in [*_PART_SEP.finditer(stem), None]:
        a, end = pos, (sep.start() if sep else len(stem))
        pos = sep.end() if sep else end
        seg, last = stem[a:end], 0
        for m in (_NUM_PART.finditer(seg) if split_numbers else ()):
            g = 1 if m.group(1) is not None else 2
            spans += [(a + last, a + m.start())] if m.start() > last else []
            spans.append((a + m.start(g), a + m.end(g)))
            last = m.end()
        if last < len(seg):
            spans.append((a + last, end))
    return spans

def name_parts(stem, split_numbers=True):
    """Pezzi del nome: separati da " - " e, con `split_numbers`, anche dai numeri staccati."""
    return [stem[a:b] for a, b in name_spans(stem, split_numbers)]

# --- marcatura manuale dei pezzi (finestra Rinomina) ---
# Una regola è posizionale, non legata ai caratteri: vale per tutti i nomi con la stessa struttura.
#   split: "Dividi anche ai numeri"; kinds: "N"/"T" (numero/testo) di ogni pezzo del nome d'esempio
#   cuts:  {pezzo: [("start", k) | ("end", k), …]}  il pezzo si divide dopo le prime k parole o prima
#          delle ultime k (in ordine di posizione); le parti sono le unità (pezzo, 0), (pezzo, 1)…
#   joins: {unità}                      Unisci: l'unità va insieme alla successiva
#   marks: {ruolo: (prima unità, ultima unità)}
_WORD = re.compile(r'[^\s_]+')
_BRACKET = re.compile(r'\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}')
_TRIM = re.compile(r'[^\s_-](?:.*[^\s_-])?', re.S)

def mark_spans(stem, split_numbers=True):
    """Pezzi per la marcatura: quelli di name_spans, con i gruppi tra parentesi come pezzi a sé
    ("Titolo (Autore) Ch." → Titolo · (Autore) · Ch.)."""
    out = []
    for a, b in name_spans(stem, split_numbers):
        pos = a
        for m in [*_BRACKET.finditer(stem, a, b), None]:
            end = m.start() if m else b
            t = _TRIM.search(stem, pos, end)
            if t:
                out.append(t.span())
            if m:
                out.append(m.span())
                pos = m.end()
    return out

def new_rule(stem, split_numbers=True):
    kinds = tuple("N" if stem[a:b].isdigit() else "T" for a, b in mark_spans(stem, split_numbers))
    return {"split": split_numbers, "kinds": kinds, "cuts": {}, "joins": set(), "marks": {}}

def piece_words(stem, a, b):
    return [(a + m.start(), a + m.end()) for m in _WORD.finditer(stem[a:b])]

def cut_points(n, cuts):
    """Indici di parola dove si divide un pezzo di n parole; None se le divisioni non ci stanno."""
    pts = [k if side == "start" else n - k for side, k in cuts]
    if all(0 < p < n for p in pts) and all(x < y for x, y in zip(pts, pts[1:])):
        return pts
    return None

def rule_units(stem, rule):
    """[(unità, inizio, fine)] del nome secondo la regola; None se la struttura è diversa."""
    if new_rule(stem, rule["split"])["kinds"] != rule["kinds"]:
        return None
    units = []
    for i, (a, b) in enumerate(mark_spans(stem, rule["split"])):
        if not rule["cuts"].get(i):
            units.append(((i, 0), a, b))
            continue
        words = piece_words(stem, a, b)
        pts = cut_points(len(words), rule["cuts"][i])
        if pts is None:
            return None
        bounds = [0, *pts, len(words)]
        units += [((i, j), words[x][0], words[y - 1][1]) for j, (x, y) in enumerate(zip(bounds, bounds[1:]))]
    return units

def _strip_value(v):
    v = v.strip(" _-")
    m = re.fullmatch(r'\((.*)\)|\[(.*)\]|\{(.*)\}', v)
    return (next(g for g in m.groups() if g is not None).strip(" _-") if m else v)

def rule_values(stem, rule):
    """{ruolo: testo} dei pezzi marcati in questo nome; None se la struttura è diversa."""
    units = rule_units(stem, rule)
    if units is None:
        return None
    pos = {key: (a, b) for key, a, b in units}
    out = {}
    for role, (k1, k2) in rule["marks"].items():
        v = _strip_value(stem[pos[k1][0]:pos[k2][1]])
        year = _YEAR.search(v) if role == "anno" else None
        out[role] = year.group(1) if year else v
    return out

def _role_of(m):
    """Ruolo di un segnaposto dello schema (None per <nome> e <n>)."""
    key = m.group(1)
    if m.group(2):
        return f"p{int(m.group(2))}"
    if key in ("tit", "titolo"):
        return "titolo"
    if key in ("sott", "sottotitolo"):
        return "sottotitolo"
    return _FIELD_OF.get(key) or (key if key in ("num", "anno") else None)

def schema_roles(schema):
    return {_role_of(m) for m in _SCHEMA_TOKEN.finditer(schema)} - {None}

def _pad(num, digits):
    return num.lstrip("0").zfill(digits)

def apply_schema(stem, schema, n, digits, split_numbers=True, fields=None, rule=None):
    """
    Nuovo nome da uno schema con <nome> (nome attuale), <num> (primo numero
    del nome), <n> (progressivo), <anno> (anno nel nome, preferito quello tra
    parentesi) e <p1>, <p2>… (pezzi separati da " - "
    e dai numeri, vedi name_parts; una parte di sole cifre prende le cifre scelte).
    Con <segnaposto:C> le cifre sono C solo per quel segnaposto (:1 = numero com'è).
    <aut>, <pub>, <edz>, <lang> vengono da `fields` (scritti a mano).
    <tit> è il titolo: senza marcature, il primo pezzo di testo; <sott> l'ultimo dopo il titolo
    (i gruppi tra parentesi non contano).
    Con `rule` (marcatura manuale) i ruoli marcati vengono dal pezzo marcato; se la
    struttura del nome è diversa: autore/editore/… dalla casella, altrimenti errore.
    Solleva ValueError se nel nome manca il numero o la parte richiesta.
    """
    parts = name_parts(stem, split_numbers)
    marks = rule["marks"] if rule else {}
    cache = []                                        # rule_values calcolato una volta, se serve

    def sub(m):
        key = m.group(1)
        d = int(m.group(3)) if m.group(3) else digits
        role = _role_of(m)
        if role in marks:
            if not cache:
                cache.append(rule_values(stem, rule) or {})
            value = cache[0].get(role)
            if value:
                return _pad(value, d) if value.isdigit() and role != "anno" else value
            if not (role in FREE_FIELDS and (fields or {}).get(role, "").strip()):
                raise ValueError("schema non applicabile")
        if key == "nome":
            return stem
        if key == "n":
            return str(n).zfill(d)
        if key in _FIELD_OF:
            value = (fields or {}).get(_FIELD_OF[key], "").strip()
            if not value:
                raise ValueError(f"campo {_FIELD_OF[key]} vuoto")
            return value
        if key == "anno":
            found = _YEAR_PAREN.search(stem) or _YEAR.search(stem)
            if not found:
                raise ValueError("anno non trovato")
            return found.group(1)
        if role in ("titolo", "sottotitolo"):
            # pezzi di testo, senza i gruppi tra parentesi ("(2016)", "[ITA]": dati, non titolo)
            text = [stem[a:b] for a, b in mark_spans(stem, split_numbers)]
            text = [t for t in text if not t.isdigit() and not _BRACKET.fullmatch(t)]
            if role == "titolo" and text:
                return text[0]
            if role == "sottotitolo" and len(text) > 1:
                return text[-1]                       # l'ultimo pezzo di testo dopo il titolo
            raise ValueError(f"{role} non trovato")
        if key == "num":
            found = re.search(r'\d+', stem)
            if not found:
                raise ValueError("numero non trovato")
            return _pad(found.group(), d)
        i = int(m.group(2))
        if not 1 <= i <= len(parts):
            raise ValueError(f"parte {i} mancante")
        return _pad(parts[i - 1], d) if parts[i - 1].isdigit() else parts[i - 1]

    return _SCHEMA_TOKEN.sub(sub, schema)

def _fill_jolly(repl, found):
    """In `repl` ogni * o ? diventa, in ordine, il testo trovato dal jolly corrispondente di Cerca."""
    it = iter(found)
    return "".join(next(it, "") if c in "*?" else c for c in repl)

def wildcard_replace(s, find, repl, case=False):
    """
    Cerca/Sostituisci con i jolly: ? = un carattere, * = qualsiasi sequenza (la più
    corta, così "(*)" toglie ogni gruppo tra parentesi; alla fine dello schema arriva in fondo).
    In `repl` * e ? rimettono il testo trovato dai jolly di `find`, nello stesso ordine
    ("[*]" → "*" toglie le parentesi e tiene il testo); tutto il resto vale alla lettera.
    """
    if not find:
        return s
    if not find.strip("*"):
        return _fill_jolly(repl, [s])                 # solo "*": tutto il nome
    pat = "".join("(.*?)" if c == "*" else "(.)" if c == "?" else re.escape(c) for c in find)
    if find.endswith("*"):
        pat = pat[:-5] + "(.*)"
    return re.sub(pat, lambda m: _fill_jolly(repl, m.groups()), s, flags=0 if case else re.IGNORECASE)

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
    if not os.path.exists(old):                       # spostato o cancellato fuori dall'app
        return "file non trovato"
    if os.path.normcase(new_path) in taken:
        return "nome ripetuto"
    try:
        if os.path.exists(new_path) and not os.path.samefile(old, new_path):
            return "esiste già"
    except OSError as e:
        return f"non accessibile ({e.strerror})"
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

