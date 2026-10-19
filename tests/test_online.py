"""Test della ricerca dell'autore online, SENZA rete (risposte finte). Uso:

    venv/bin/python tests/test_online.py
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comicoptimizer import online
from comicoptimizer.online import clean_title, result_label, search_authors

# titolo da cercare ricavato dal nome del file
for name, want in (("jujika_no_rokunin_v03 (Digital).cbz", "jujika no rokunin"),
                   ("[Juujika no Rokunin] - Capitolo #008.pdf", "Juujika no Rokunin"),
                   ("[Grp] Berserk 12.cbz", "Berserk"),
                   ("Absolute Batman 024 (2026) (Digital) (Shan-Empire).cbz", "Absolute Batman"),
                   ("20th Century Boys 05.cbz", "20th Century Boys"),
                   ("Dylan Dog #045 - L'alba dei morti viventi.cbz", "Dylan Dog"),
                   ("L'attacco dei giganti Vol. 3.cbr", "L'attacco dei giganti"),
                   ("Tex", "Tex")):
    assert clean_title(name) == want, (name, clean_title(name))

# risposte finte di Wikidata e AniList
SEARCH = {"it": [{"id": "Q1", "label": "L'attacco dei giganti", "description": "manga di Hajime Isayama"},
                 {"id": "Q9", "label": "L'attacco dei giganti", "description": "film del 2015"},
                 {"id": "Q8", "label": "Senza autori", "description": "manga"}],
          "en": [{"id": "Q1", "label": "Attack on Titan", "description": "manga"}]}
CLAIMS = {"Q1": {"claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "P100"}}}}]}},
          "Q9": {"claims": {"P170": [{"mainsnak": {"datavalue": {"value": {"id": "P200"}}}}]}},
          "Q8": {"claims": {}}}
LABELS = {"P100": {"labels": {"it": {"value": "Hajime Isayama"}}},
          "P200": {"labels": {"en": {"value": "Shinji Higuchi"}}}}
ANILIST = {"data": {"Page": {"media": [
    {"title": {"english": "Attack on Titan", "romaji": "Shingeki no Kyojin"},
     "staff": {"edges": [{"role": "Story & Art", "node": {"name": {"full": "Hajime Isayama"}}},
                         {"role": "Assistant", "node": {"name": {"full": "Qualcuno"}}}]}}]}}}


def fake_get(url, data=None):
    if data is not None:
        assert json.loads(data)["variables"]["s"] == "titolo"      # ad AniList va solo il titolo
        return ANILIST
    q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
    if q["action"] == "wbsearchentities":
        assert q["search"] == "titolo"                               # a Wikidata va solo il titolo
        return {"search": SEARCH[q["language"]]}
    ids = q["ids"].split("|")
    pool = CLAIMS if q["props"] == "claims" else LABELS
    return {"entities": {i: pool[i] for i in ids if i in pool}}


online._get_json = fake_get
res = search_authors("titolo")
assert [r["authors"] for r in res] == [["Hajime Isayama"], ["Hajime Isayama"], ["Shinji Higuchi"]], res
assert res[0]["source"] == "Wikidata" and res[1]["source"] == "AniList"   # i fumetti prima del film
assert "film" in res[2]["desc"]
assert result_label(res[0]) == "L'attacco dei giganti — manga di Hajime Isayama — Hajime Isayama  (Wikidata)"

# un servizio giù: si usano i risultati dell'altro
def half_down(url, data=None):
    if data is not None:
        raise OSError("AniList non risponde")
    return fake_get(url, data)
online._get_json = half_down
assert [r["source"] for r in search_authors("titolo")] == ["Wikidata", "Wikidata"]

# rete assente: errore chiaro (la finestra mostra un messaggio)
online._get_json = lambda url, data=None: (_ for _ in ()).throw(OSError("rete assente"))
try:
    search_authors("titolo")
    raise AssertionError("doveva fallire")
except OSError as e:
    assert "Wikidata" in str(e) and "AniList" in str(e)

# nessun risultato
online._get_json = lambda url, data=None: {"data": {"Page": {"media": []}}} if data else {"search": []}
assert search_authors("titolo") == []
print("TUTTO OK")
