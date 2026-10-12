"""Creazione e verifica dei CBZ, ComicInfo.xml."""

import xml.etree.ElementTree as ET
import zipfile

from .config import APP_VERSION
from .logsetup import log
from .utils import is_page_file

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
