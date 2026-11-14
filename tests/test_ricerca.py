"""Controlli sulle fonti di ricerca, senza rete e senza aprire finestre: python3 -m unittest"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comicoptimizer import ricerca
from bs4 import BeautifulSoup

RISULTATI = """
<a href="/serie/ALTRA">ALTRA DYLAN DOG (X)</a>
<a href="/albo/DD_099">DYLAN DOG # 99 - Prima (Bonelli)</a>
<a href="/albo/DD_100">DYLAN DOG # 100 - Giusto (Bonelli)</a>
<a href="/albo/DD_100">DYLAN DOG # 100 - Giusto (Bonelli)</a>
<a href="/forum/F">DYLAN DOG forum</a>
<a href="/serie/C">x</a>
"""

ALBO = """
<div id="container_cover_cb"><img src="/cover/DD_100.jpg"></div>
<div id="intestazione"><h1>Dylan Dog # 100 <span id="subtitolo_issue">| Giusto</span></h1>
<span id="editore_issue">Bonelli</span><span id="data_issue">Gennaio 1995</span></div>
<div class="alboita_dettagli"><a href="/autore/a">Anna Rossi</a> (script) /
<a href="/autore/b">Bruno Bianchi</a> (art)</div>
<div class="sinossi">Una trama.</div>
"""


def errore_429(*_args, **_kwargs):
    raise ricerca.ErroreRicerca("HTTP 429", codice=429)


class TestComicsBox(unittest.TestCase):

    def setUp(self):
        ricerca.cb_pagine.clear()

    def test_etichetta_albo(self):
        self.assertEqual(
                ricerca.cb_analizza_etichetta("DYLAN DOG # 100 - Il titolo (Sergio Bonelli Editore)"),
                {"Publisher": "Sergio Bonelli Editore", "Series": "DYLAN DOG", "Number": "100", "Title": "Il titolo"},
        )

    def test_etichetta_serie_con_parentesi(self):
        self.assertEqual(
                ricerca.cb_analizza_etichetta("LIBRI (CARTONATI) (Bonelli)"),
                {"Publisher": "Bonelli", "Series": "LIBRI (CARTONATI)"},
        )

    def test_pagina_scarta_doppioni_e_mette_prima_il_numero_cercato(self):
        risultati = ricerca.cb_analizza_pagina(RISULTATI, "dylan dog 100")
        self.assertEqual(len(risultati), 3)
        self.assertEqual(risultati[0]["campi"]["Number"], "100")
        self.assertTrue(risultati[-1]["etichetta"].startswith("ALTRA"))

    def test_scheda_albo(self):
        campi = ricerca.cb_campi_albo(BeautifulSoup(ALBO, "html.parser"))
        self.assertEqual(campi["Series"], "Dylan Dog")
        self.assertEqual(campi["Title"], "Giusto")
        self.assertEqual(campi["Year"], "1995")
        self.assertEqual(campi["Writer"], "Anna Rossi")
        self.assertEqual(campi["Penciller"], "Bruno Bianchi")
        self.assertEqual(campi["Summary"], "Una trama.")

    def test_link_alla_scheda_all_inizio_del_summary(self):
        url = "https://www.comicsbox.it/albo/DD_001"
        risultato = {"grezzo": {"url": url}, "note": [f"Scheda ComicsBox: {url}"]}
        with mock.patch.object(ricerca, "cb_scarica", return_value=ALBO):
            campi = ricerca.cb_dettagli("", risultato)
        self.assertEqual(campi["Summary"], f"{url}\n\nUna trama.")
        self.assertEqual(risultato["note"], [])

        maiuscolo = ALBO.replace("Una trama.", "UNA TRAMA.")
        with mock.patch.object(ricerca, "cb_scarica", return_value=maiuscolo):
            self.assertEqual(ricerca.cb_dettagli("", risultato)["Summary"], f"{url}\n\nUna trama.")

        with mock.patch.object(ricerca, "cb_scarica", return_value="<html></html>"):
            self.assertEqual(ricerca.cb_dettagli("", risultato)["Summary"], url)

    def test_429_riprova_e_poi_si_arrende(self):
        with mock.patch.object(ricerca, "richiesta_bytes", side_effect=errore_429) as richiesta, \
                mock.patch.object(ricerca.time, "sleep") as attesa:
            with self.assertRaises(ricerca.ErroreRicerca):
                ricerca.cb_scarica("http://x/1")
        self.assertEqual(richiesta.call_count, 3)
        self.assertEqual([c.args[0] for c in attesa.call_args_list], [15, 30])

    def test_stessa_pagina_scaricata_una_volta(self):
        with mock.patch.object(ricerca, "richiesta_bytes", return_value=b"ok") as richiesta:
            self.assertEqual(ricerca.cb_scarica("http://x/2"), "ok")
            self.assertEqual(ricerca.cb_scarica("http://x/2"), "ok")
        self.assertEqual(richiesta.call_count, 1)


class TestAniList(unittest.TestCase):

    VOCE = {
            "title": {"romaji": "Sensha Isu: TANK CHAIR", "english": "Tank Chair"},
            "format": "MANGA",
            "startDate": {"year": 2022},
            "volumes": None,
            "coverImage": {"extraLarge": None, "large": "http://x/c.jpg"},
            "genres": ["Action"],
            "description": "Trama.<br><br>~!Segreto!~\n(Source: Sito)",
            "staff": {"edges": [
                    {"role": "Story & Art (vols 1-41)", "node": {"name": {"full": "Anna"}}},
                    {"role": "Story", "node": {"name": {"full": "Bruno"}}},
                    {"role": "Touch-up Art & Lettering", "node": {"name": {"full": "Carlo"}}},
                    {"role": "Translator (Spanish)", "node": {"name": {"full": "Dario"}}},
            ]},
            "characters": {"nodes": [{"name": {"full": "Nagi"}}, {"name": {"full": "Nagi"}}, {"name": {"full": "Shizuka"}}]},
    }

    def test_campi(self):
        campi = ricerca.al_risultato(self.VOCE)["campi"]
        self.assertEqual(campi["Series"], "Tank Chair")
        self.assertEqual(campi["Year"], "2022")
        self.assertEqual(campi["Count"], "")
        self.assertEqual(campi["Writer"], "Anna, Bruno")
        self.assertEqual(campi["Penciller"], "Anna")
        self.assertEqual(campi["Characters"], "Nagi, Shizuka")
        self.assertEqual(campi["Summary"], "Trama.")

    def test_campi_mancanti_non_rompono(self):
        risultato = ricerca.al_risultato({"title": None, "staff": None, "characters": None})
        self.assertEqual(risultato["campi"]["Series"], "Senza titolo")

    def test_errore_del_server_visibile(self):
        with mock.patch.object(ricerca, "richiesta_json", return_value={"errors": [{"message": "No"}]}):
            with self.assertRaisesRegex(ricerca.ErroreRicerca, "No"):
                ricerca.al_cerca("", "x")


class TestRicercaPerTitolo(unittest.TestCase):

    def test_titolo_da_nome(self):
        casi = {
                "Batman - L'ultimo cavaliere sulla terra": "L'ultimo cavaliere sulla terra",
                "Batman_-_Hush_(2020)_[Digital]": "Hush",
                "Dylan Dog - 100": "Dylan Dog",
                "Dylan Dog 100": "Dylan Dog 100",
                "Spider-Man": "Spider-Man",
                "100": "100",
        }
        for da, a in casi.items():
            self.assertEqual(ricerca.titolo_da_nome(da), a)

    def test_filtro_ignora_ordine_punteggiatura_e_accenti(self):
        etichetta = "DC BLACK LABEL # 1 - Batman: L'ultimo cavaliere sulla Terra (Panini)"
        self.assertTrue(ricerca.passa_filtro("terra batman ultimo", etichetta))
        self.assertTrue(ricerca.passa_filtro("Batman - L'ultimo cavali", etichetta))
        self.assertTrue(ricerca.passa_filtro("", etichetta))
        self.assertFalse(ricerca.passa_filtro("batman hush", etichetta))
        self.assertTrue(ricerca.passa_filtro("citta", "La Città"))

    def test_ordine_per_parole_in_comune_senza_scartare(self):
        risultati = [{"etichetta": e} for e in ("Altro albo", "Batman: Hush (DC)", "Batman: L'ultimo cavaliere (DC)")]
        ordinati = ricerca.ordina_per_parole(risultati, "Batman - L'ultimo cavaliere")
        self.assertEqual([r["etichetta"] for r in ordinati], ["Batman: L'ultimo cavaliere (DC)", "Batman: Hush (DC)", "Altro albo"])
        # il numero conta dopo il nome: senza "Superman #25" fra i risultati, prima gli altri Superman
        risultati = [{"etichetta": "Absolute Batman #25 - The Zoo (2026)"},
                     {"etichetta": "Absolute Superman #24 - Kansas (2026)"}]
        ordinati = ricerca.ordina_per_parole(risultati, "absolute superman 25")
        self.assertEqual(ordinati[0]["etichetta"], "Absolute Superman #24 - Kansas (2026)")
        risultati.append({"etichetta": "Absolute Superman #25 - Sol (2026)"})
        ordinati = ricerca.ordina_per_parole(risultati, "absolute superman 25")
        self.assertEqual([r["etichetta"].split(" - ")[0] for r in ordinati],
                         ["Absolute Superman #25", "Absolute Superman #24", "Absolute Batman #25"])


class TestNumero(unittest.TestCase):

    def test_separa_numero(self):
        self.assertEqual(ricerca.separa_numero("Dylan Dog #100"), ("dylan dog", "100"))
        self.assertEqual(ricerca.separa_numero("Dylan Dog"), ("dylan dog", None))


if __name__ == "__main__":
    unittest.main()
