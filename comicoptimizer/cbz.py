"""Creazione e verifica dei CBZ, ComicInfo.xml."""

import os
import xml.etree.ElementTree as ET
import zipfile

from .archives import detect_real_format
from .config import APP_VERSION
from .logsetup import log
from .utils import is_page_file

# --- COMICINFO / STATO CBZ ---

CBZ_MARK = f"ComicOptimizer {APP_VERSION}"

def build_comicinfo(path, page_count, edited=False, title=None):
    """
    Restituisce i byte di ComicInfo.xml da inserire nel nuovo CBZ.
    Se il numero di pagine è cambiato (o le pagine sono state riordinate
    nell'editor) aggiorna <PageCount> e rimuove <Pages>, che non sarebbe più valido.
    Con `title` (unione di più fumetti) imposta <Title> e rimuove <Number>.
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        root = ET.fromstring(raw)
        pc = root.find("PageCount")
        pages = root.find("Pages")
        pc_wrong = pc is not None and (pc.text or "").strip() != str(page_count)
        pages_wrong = pages is not None and (edited or len(pages) != page_count)
        if title is not None:
            t = root.find("Title")
            if t is None:
                t = ET.SubElement(root, "Title")
            t.text = title
            num = root.find("Number")
            if num is not None:
                root.remove(num)
        elif not pc_wrong and not pages_wrong:
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

def file_status(path):
    """
    Stato di un fumetto integro, dal formato REALE (non dall'estensione):
    0 = da sistemare (PDF, RAR, cartella, ZIP illeggibile, altro), 1 = CBZ ok, 3 = convertito.
    Unica regola, usata sia all'importazione sia nell'analisi.
    """
    if os.path.isdir(path):
        return 0
    real = detect_real_format(path)
    ext = os.path.splitext(path)[1].lower()
    if real == 'zip' or (real is None and ext in ('.cbz', '.zip')):
        try:
            return cbz_status(path)
        except Exception as e:
            log.debug(f"file_status: '{os.path.basename(path)}' non leggibile come ZIP: {e}")
    return 0

def verify_cbz(path, expected_pages):
    """Controlla il CBZ appena creato PRIMA di toccare l'originale."""
    with zipfile.ZipFile(path, 'r') as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"archivio creato corrotto ('{bad}')")
        n = sum(1 for name in z.namelist() if is_page_file(name))
    if n != expected_pages:
        raise RuntimeError(f"il nuovo archivio ha {n} pagine invece di {expected_pages}")
