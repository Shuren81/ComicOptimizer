"""EPUB a fumetti: pagine nell'ordine di lettura (spine), info dal content.opf, controlli."""

import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from .utils import is_page_file

_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container",
       "opf": "http://www.idpf.org/2007/opf",
       "dc": "http://purl.org/dc/elements/1.1/"}
# immagine di una pagina XHTML: <img src="…"> o <svg><image xlink:href="…">
_IMG_REF = re.compile(r'<(?:img|image)\b[^>]*?\s(?:src|xlink:href|href)\s*=\s*["\']([^"\']+)', re.I)
_FONT_EXTS = (".ttf", ".otf", ".woff", ".woff2")


def _resolve(base, href):
    return posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href.split("#")[0])))


def _opf(z):
    """(percorso, radice XML) del content.opf indicato da META-INF/container.xml."""
    container = ET.fromstring(z.read("META-INF/container.xml"))
    path = container.find(".//c:rootfile", _NS).get("full-path")
    return path, ET.fromstring(z.read(path))


def epub_pages(path):
    """Immagini delle pagine, nell'ordine dello spine (nomi dentro lo ZIP); [] se non ce ne sono."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            opf_path, opf = _opf(z)
            base = posixpath.dirname(opf_path)
            manifest = {it.get("id"): it for it in opf.iterfind("opf:manifest/opf:item", _NS)}
            pages = []
            for ref in opf.iterfind("opf:spine/opf:itemref", _NS):
                item = manifest.get(ref.get("idref"))
                if item is None:
                    continue
                href = _resolve(base, item.get("href", ""))
                if item.get("media-type", "").startswith("image/"):
                    found = [href]                    # voce dello spine che è già un'immagine
                else:
                    try:
                        text = z.read(href).decode("utf-8", "replace")
                    except KeyError:
                        continue
                    found = [_resolve(posixpath.dirname(href), r) for r in _IMG_REF.findall(text)]
                pages += [f for f in found if f in names and is_page_file(f) and f not in pages]
            return pages
    except Exception:
        return []


def epub_problem(path):
    """Perché l'EPUB non diventa un fumetto: DRM, solo testo, illeggibile; None se va bene."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "META-INF/rights.xml" in names:
                return "EPUB protetto (DRM)"
            if "META-INF/encryption.xml" in names:
                enc = z.read("META-INF/encryption.xml").decode("utf-8", "replace")
                # i font "offuscati" sono normali; cifrare pagine o immagini è DRM
                uris = re.findall(r'URI\s*=\s*["\']([^"\']+)', enc)
                if any(not u.lower().endswith(_FONT_EXTS) for u in uris):
                    return "EPUB protetto (DRM)"
    except Exception:
        return "EPUB illeggibile"
    if not epub_pages(path):
        return "EPUB di solo testo (nessuna pagina a immagine)"
    return None


def epub_meta(path):
    """Info dal content.opf, con le chiavi della finestra Info ("" dove mancano)."""
    out = {"titolo": "", "num": "", "sottotitolo": "", "anno": "", "autore": "",
           "editore": "", "edizione": "", "lingua": "", "manga": False}
    try:
        with zipfile.ZipFile(path) as z:
            meta = _opf(z)[1].find("opf:metadata", _NS)
    except Exception:
        return out
    if meta is None:
        return out

    def dc(tag):
        return [(e.text or "").strip() for e in meta.iterfind(f"dc:{tag}", _NS) if (e.text or "").strip()]

    title = (dc("title") or [""])[0]
    series = index = ""
    for m in meta.iterfind("opf:meta", _NS):
        name, prop = m.get("name", ""), m.get("property", "")
        if name == "calibre:series":
            series = m.get("content", "").strip()
        elif name == "calibre:series_index":
            index = m.get("content", "").strip()
        elif prop == "belongs-to-collection" and not series:
            series = (m.text or "").strip()
        elif prop == "group-position" and not index:
            index = (m.text or "").strip()
    if index.endswith(".0"):
        index = index[:-2]                            # Calibre scrive "3.0"
    year = next((d[:4] for d in dc("date") if d[:4].isdigit()), "")
    out.update(titolo=series or title, num=index, sottotitolo=title if series else "", anno=year,
               autore=", ".join(dc("creator")), editore=(dc("publisher") or [""])[0],
               lingua=(dc("language") or [""])[0])
    return out
