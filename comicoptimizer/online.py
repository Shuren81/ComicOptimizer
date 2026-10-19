"""Ricerca online dell'autore di un fumetto (Wikidata, poi AniList).

Viene inviato SOLO il titolo cercato, e solo quando l'utente preme "Cerca"."""

import json
import os
import re
import urllib.parse
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from .config import APP_VERSION

USER_AGENT = f"ComicOptimizer/{APP_VERSION} (https://github.com/Shuren81/ComicOptimizer)"
TIMEOUT = 10
MAX_RESULTS = 8
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
ANILIST_API = "https://graphql.anilist.co"
_AUTHOR_PROPS = ("P50", "P170", "P110")       # Wikidata: autore, creatore, illustratore
_COMIC_WORDS = re.compile(r'(?i)manga|manhwa|manhua|fumett|comic|graphic novel|bande dessin')
_ANILIST_QUERY = """query ($s: String) { Page(perPage: 5) { media(search: $s, type: MANGA) {
  title { romaji english } staff(perPage: 10) { edges { role node { name { full } } } } } } }"""

# numero (anche con Vol./v/Ch./Cap./#) non attaccato a lettere: "20th" fa parte del titolo
_NUMBER = re.compile(
    r'(?i)(?:\b(?:vol(?:ume)?|v|ch(?:apter)?|c|cap(?:itolo)?|ep)\.?\s*#?|#|\b)\d+(?![^\W\d_])')


def _cut_number(s):
    """Taglia dal primo numero che segue un po' di titolo (e tutto ciò che viene dopo)."""
    for m in _NUMBER.finditer(s):
        if s[:m.start()].strip(' -.#'):
            return s[:m.start()]
    return s


def clean_title(name):
    """Titolo da cercare, dal nome del file: senza estensione, parentesi, _, numeri e ciò che segue.
    Se fuori dalle quadre non resta niente ("[Titolo] - Capitolo 8"), il titolo è nelle quadre."""
    s = re.sub(r'(?i)\.(cbz|cbr|zip|rar|pdf|cb7|7z)$', '', os.path.basename(name)).replace('_', ' ')
    s = re.sub(r'[({][^)}]*[)}]', ' ', s)              # (2024) (Digital) {…}: dati, non titolo
    outside = _cut_number(re.sub(r'\[[^\]]*\]', ' ', s))
    # fuori dalle quadre solo "Capitolo #008", "Vol. 3"…: nessun titolo
    if not re.sub(r'(?i)\b(?:vol(?:ume)?|ch(?:apter)?|cap(?:itolo)?|v|c|n|no)\b|[\d#.\s-]', '', outside):
        inside = re.findall(r'\[([^\]]*)\]', s)
        outside = _cut_number(inside[0]) if inside else outside
    return ' '.join(outside.split()).strip(' -.#')


def _get_json(url, data=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _wikidata(title):
    """Cerca in italiano e in inglese; restituisce le voci che hanno un autore/creatore."""
    ids, label, desc = [], {}, {}
    for lang in ("it", "en"):
        q = urllib.parse.urlencode({"action": "wbsearchentities", "search": title, "language": lang,
                                    "uselang": lang, "type": "item", "limit": 7, "format": "json"})
        for hit in _get_json(f"{WIKIDATA_API}?{q}").get("search", []):
            if hit["id"] not in ids:
                ids.append(hit["id"])
                label[hit["id"]] = hit.get("label") or hit.get("match", {}).get("text", "")
                desc[hit["id"]] = hit.get("description", "")
    if not ids:
        return []
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
                                "format": "json"})
    authors = {}
    for qid, ent in _get_json(f"{WIKIDATA_API}?{q}").get("entities", {}).items():
        found = []
        for prop in _AUTHOR_PROPS:
            for claim in ent.get("claims", {}).get(prop, []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                aid = value.get("id") if isinstance(value, dict) else None
                if aid and aid not in found:
                    found.append(aid)
        if found:
            authors[qid] = found
    if not authors:
        return []
    people = list(dict.fromkeys(a for qid in ids if qid in authors for a in authors[qid]))[:50]
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(people), "props": "labels",
                                "languages": "it|en", "format": "json"})
    ents = _get_json(f"{WIKIDATA_API}?{q}").get("entities", {})

    def name(aid):
        labels = ents.get(aid, {}).get("labels", {})
        return (labels.get("it") or labels.get("en") or {}).get("value")

    return [{"title": label[qid], "desc": desc[qid], "source": "Wikidata",
             "authors": [n for n in map(name, authors[qid]) if n]}
            for qid in ids if qid in authors]


def _anilist(title):
    data = json.dumps({"query": _ANILIST_QUERY, "variables": {"s": title}}).encode()
    media = _get_json(ANILIST_API, data).get("data", {}).get("Page", {}).get("media", []) or []
    out = []
    for m in media:
        names = [e["node"]["name"]["full"] for e in m.get("staff", {}).get("edges", [])
                 if re.match(r'(?i)(original )?(story|art|creator)', e.get("role") or "")]
        out.append({"title": m["title"].get("english") or m["title"].get("romaji") or "",
                    "desc": "manga", "source": "AniList", "authors": list(dict.fromkeys(names))})
    return out


def search_authors(title):
    """
    Risultati [{title, desc, source, authors}] con almeno un autore, senza doppioni,
    al massimo MAX_RESULTS. Solleva OSError se nessun servizio ha risposto.
    """
    results, errors = [], []
    for source, fn in (("Wikidata", _wikidata), ("AniList", _anilist)):
        try:
            results += fn(title)
        except Exception as e:                        # rete assente, servizio giù, risposta strana
            errors.append(f"{source}: {e}")
    if len(errors) == 2:
        raise OSError("; ".join(errors))
    # prima i fumetti (manga, serie a fumetti, comics…), poi film, serie TV e il resto
    results.sort(key=lambda r: 0 if _COMIC_WORDS.search(r["desc"]) else 1)
    seen, unique = set(), []
    for r in results:
        key = (r["title"].lower(), tuple(r["authors"]))
        if r["authors"] and key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:MAX_RESULTS]


def result_label(r):
    parts = [r["title"]] + ([r["desc"]] if r["desc"] else []) + [", ".join(r["authors"])]
    return " — ".join(parts) + f"  ({r['source']})"


class AuthorSearchWorker(QThread):
    """Ricerca in un thread: la finestra non si blocca."""
    found = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, title):
        super().__init__()
        self.title = title

    def run(self):
        try:
            self.found.emit(search_authors(self.title))
        except Exception as e:
            self.failed.emit(str(e))
