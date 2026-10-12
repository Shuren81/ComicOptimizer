"""Lettura, controllo ed estrazione degli archivi (CBZ, CBR, ZIP, RAR, PDF)."""

import os
import subprocess
import zipfile

from .logsetup import log
from .pdf import HAS_PDF, extract_pdf_pages, fitz
from .utils import get_natural_sort_key, is_page_file, run_tool

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
