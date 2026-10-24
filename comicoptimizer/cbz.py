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

# campi della finestra Info: ruolo (come nella Rinomina) → elemento di ComicInfo.xml
INFO_FIELDS = (("titolo", "Series"), ("num", "Number"), ("sottotitolo", "Title"), ("anno", "Year"),
               ("autore", "Writer"), ("editore", "Publisher"), ("edizione", "Format"),
               ("lingua", "LanguageISO"))
# LanguageISO vuole il codice ISO 639 ("it"); nei nomi si scrive spesso "ITA"
LANG_ISO = {"ITA": "it", "IT": "it", "ENG": "en", "EN": "en", "JPN": "ja", "JAP": "ja", "JP": "ja",
            "FRA": "fr", "FR": "fr", "ESP": "es", "SPA": "es", "ES": "es", "DEU": "de", "GER": "de",
            "DE": "de", "POR": "pt", "PT": "pt", "KOR": "ko", "KO": "ko", "CHI": "zh", "ZH": "zh",
            "ITALIANO": "it", "ITALIAN": "it", "INGLESE": "en", "ENGLISH": "en", "GIAPPONESE": "ja",
            "JAPANESE": "ja", "FRANCESE": "fr", "FRENCH": "fr", "FRANÇAIS": "fr", "SPAGNOLO": "es",
            "SPANISH": "es", "ESPAÑOL": "es", "TEDESCO": "de", "GERMAN": "de", "DEUTSCH": "de",
            "PORTOGHESE": "pt", "PORTUGUESE": "pt", "COREANO": "ko", "KOREAN": "ko",
            "CINESE": "zh", "CHINESE": "zh"}
# ordine dello schema ComicInfo (alcuni programmi lo vogliono); gli elementi sconosciuti vanno in fondo
_CI_ORDER = ("Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber",
             "AlternateCount", "Summary", "Notes", "Year", "Month", "Day", "Writer", "Penciller",
             "Inker", "Colorist", "Letterer", "CoverArtist", "Editor", "Translator", "Publisher",
             "Imprint", "Genre", "Tags", "Web", "PageCount", "LanguageISO", "Format",
             "BlackAndWhite", "Manga", "Characters", "Teams", "Locations", "ScanInformation",
             "StoryArc", "SeriesGroup", "AgeRating", "Pages", "CommunityRating", "MainCharacterOrTeam",
             "Review", "GTIN")


def _set_info(root, info):
    """Scrive i campi della finestra Info: un campo vuoto toglie l'elemento; gli altri restano."""
    for role, tag in INFO_FIELDS:
        if role not in info:
            continue
        value = str(info[role]).strip()
        if tag == "LanguageISO":
            value = LANG_ISO.get(value.upper(), value.lower())
        el = root.find(tag)
        if not value:
            if el is not None:
                root.remove(el)
            continue
        if el is None:
            el = ET.SubElement(root, tag)
        el.text = value
    if "manga" in info:
        el = root.find("Manga")
        if not info["manga"]:
            if el is not None:
                root.remove(el)
        elif el is None or not (el.text or "").startswith("Yes"):
            if el is None:
                el = ET.SubElement(root, "Manga")
            el.text = "YesAndRightToLeft"            # i manga si leggono da destra a sinistra
    order = {t: i for i, t in enumerate(_CI_ORDER)}
    root[:] = sorted(root, key=lambda e: order.get(e.tag, len(order)))


def read_comicinfo(path):
    """{ruolo: valore, "manga": bool} dal ComicInfo.xml di un CBZ o di una cartella; {} se non c'è
    o non si legge. shortcut: CBR e PDF non vengono letti (si parte dal nome), da fare se servisse."""
    try:
        if os.path.isdir(path):
            ci = next((e.path for e in os.scandir(path) if e.is_file()
                       and e.name.lower() == "comicinfo.xml"), None)
            if not ci:
                return {}
            with open(ci, "rb") as f:
                raw = f.read()
        else:
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if os.path.basename(n).lower() == "comicinfo.xml"), None)
                if not name:
                    return {}
                raw = z.read(name)
        root = ET.fromstring(raw)
    except Exception:
        return {}
    out = {role: (root.findtext(tag) or "").strip() for role, tag in INFO_FIELDS}
    out["manga"] = (root.findtext("Manga") or "").startswith("Yes")
    return out


def build_comicinfo(path, page_count, edited=False, title=None, info=None):
    """
    Restituisce i byte di ComicInfo.xml da inserire nel nuovo CBZ.
    Se il numero di pagine è cambiato (o le pagine sono state riordinate
    nell'editor) aggiorna <PageCount> e rimuove <Pages>, che non sarebbe più valido.
    Con `title` (unione di più fumetti) imposta <Title> e rimuove <Number>.
    Con `info` (finestra Info) scrive quei campi; senza `path` crea un ComicInfo nuovo.
    """
    if path is None:
        root = ET.Element("ComicInfo")
        ET.SubElement(root, "PageCount").text = str(page_count)
        _set_info(root, info or {})
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
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
        elif not pc_wrong and not pages_wrong and not info:
            return raw
        if pc_wrong:
            pc.text = str(page_count)
        if pages_wrong:
            root.remove(pages)
        if info:
            _set_info(root, info)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except Exception as e:
        if info:                                      # illeggibile: se ne scrive uno nuovo con le info
            log.warning(f"  ComicInfo.xml non analizzabile ({e}): sostituito con le info nuove")
            return build_comicinfo(None, page_count, info=info)
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
