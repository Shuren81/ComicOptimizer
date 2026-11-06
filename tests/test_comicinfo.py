"""Controlli su scrittura del ComicInfo e pulizia dei testi, senza finestre: python3 -m unittest"""
import io
import os
import tempfile
import sys
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comicoptimizer import comicinfo


class TestScrittura(unittest.TestCase):

    def setUp(self):
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        self.percorso = os.path.join(cartella.name, "prova.cbz")

    def crea(self, xml=None):
        with zipfile.ZipFile(self.percorso, "w") as z:
            z.writestr("001.webp", b"immagine")
            if xml is not None:
                z.writestr("ComicInfo.xml", xml)

    def test_conserva_immagini_e_tag_non_gestiti(self):
        self.crea("<ComicInfo><Series>Vecchia</Series><Notes>tienimi</Notes></ComicInfo>")
        comicinfo.scrivi_cbz(self.percorso, {"Series": "Nuova"})
        radice = comicinfo.leggi_radice(self.percorso)
        self.assertEqual(radice.findtext("Series"), "Nuova")
        self.assertEqual(radice.findtext("Notes"), "tienimi")
        with zipfile.ZipFile(self.percorso) as z:
            self.assertEqual(z.read("001.webp"), b"immagine")
            self.assertEqual(z.namelist().count("ComicInfo.xml"), 1)

    def test_lascia_le_immagini_dove_sono_e_resta_leggibile_se_interrotto(self):
        self.crea("<ComicInfo><Series>Vecchia</Series></ComicInfo>")
        with open(self.percorso, "rb") as f:
            prima = f.read()
        avanzato = []
        comicinfo.scrivi_cbz(self.percorso, {"Series": "Nuova"}, avanzato.append)
        with open(self.percorso, "rb") as f:
            dopo = f.read()
        self.assertTrue(dopo.startswith(prima))
        self.assertEqual(comicinfo.leggi_radice(self.percorso).findtext("Series"), "Nuova")
        with zipfile.ZipFile(self.percorso) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(sorted(z.namelist()), ["001.webp", "ComicInfo.xml"])
        self.assertEqual(len(avanzato), 1)
        # Interrotto prima dell'ultimo record dello zip: si legge ancora il dato vecchio
        with zipfile.ZipFile(io.BytesIO(dopo[:len(dopo) - 22])) as z:
            self.assertIn(b"Vecchia", z.read("ComicInfo.xml"))

    def test_errore_di_scrittura_ripristina_il_file(self):
        self.crea("<ComicInfo><Series>Vecchia</Series></ComicInfo>")
        with open(self.percorso, "rb") as f:
            prima = f.read()
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("disco pieno")):
            with self.assertRaises(OSError):
                comicinfo.scrivi_cbz(self.percorso, {"Series": "Nuova"})
        with open(self.percorso, "rb") as f:
            self.assertEqual(f.read(), prima)
        self.assertEqual(comicinfo.leggi_radice(self.percorso).findtext("Series"), "Vecchia")

    def test_valore_vuoto_toglie_il_tag(self):
        self.crea("<ComicInfo><Series>Via</Series></ComicInfo>")
        comicinfo.scrivi_cbz(self.percorso, {"Series": ""})
        self.assertIsNone(comicinfo.leggi_radice(self.percorso).find("Series"))

    def test_crea_il_comicinfo_se_manca(self):
        self.crea()
        comicinfo.scrivi_cbz(self.percorso, {"Title": "Nuovo"})
        self.assertEqual(comicinfo.leggi_radice(self.percorso).findtext("Title"), "Nuovo")

    def test_caratteri_di_controllo_non_rompono_il_file(self):
        self.crea("<ComicInfo/>")
        comicinfo.scrivi_cbz(self.percorso, {"Summary": "riga\x0cuno\nriga\x00due"})
        self.assertEqual(comicinfo.leggi_radice(self.percorso).findtext("Summary"), "rigauno\nrigadue")

    def test_errore_lascia_intatto_il_file(self):
        with open(self.percorso, "wb") as f:
            f.write(b"non sono uno zip")
        with self.assertRaises(zipfile.BadZipFile):
            comicinfo.scrivi_cbz(self.percorso, {"Title": "x"})
        with open(self.percorso, "rb") as f:
            self.assertEqual(f.read(), b"non sono uno zip")


class TestTesti(unittest.TestCase):

    def test_maiuscole_e_numeri_romani(self):
        casi = {
                "DYLAN DOG": "Dylan Dog", "ROCKY II": "Rocky II", "CAPITOLO (IV)": "Capitolo (IV)",
                "X-MEN": "X-Men", "Già Corretto": "Già Corretto", "MIX VIVI": "Mix Vivi",
        }
        for da, a in casi.items():
            self.assertEqual(comicinfo.togli_maiuscole("Series", da), a)

    def test_maiuscole_summary_e_codici(self):
        self.assertEqual(comicinfo.togli_maiuscole("Summary", "UNA STORIA"), "Una storia")
        self.assertEqual(comicinfo.togli_maiuscole("LanguageISO", "IT"), "IT")

    def test_lingua(self):
        casi = {"Italiano": "it", "ita": "it", "fi": "fi", "it-it": "it-IT", "tha": "tha", "italiano!": None, "x": None, "": None}
        for da, a in casi.items():
            self.assertEqual(comicinfo.normalizza_lingua(da), a)

    def test_togli_tag_schema(self):
        schema = "<Series> - #<Number> - <Title>"
        casi = {
                (schema, "Series"): "#<Number> - <Title>",
                (schema, "Number"): "<Series> - <Title>",
                (schema, "Title"): "<Series> - #<Number>",
                ("<Series> (<Year>) - <Title>", "Year"): "<Series> - <Title>",
                ("<Series> [<Year>]", "Year"): "<Series>",
                ("<Series>_<Title>_<Series>", "Series"): "<Title>",
                ("<Series>", "Series"): "",
        }
        for (da, campo), a in casi.items():
            self.assertEqual(comicinfo.togli_tag_schema(da, campo), a)

    def test_nome_campi_vuoti(self):
        v = {"Series": "Batwoman", "Year": "2026", "Number": "3", "Title": "Open Season"}
        casi = {
                ("<Series> (<Year>) - <Title>", "Title"): "Batwoman (2026)",
                ("<Series> - #<Number> - <Title>", "Number"): "Batwoman - Open Season",
                ("<Series> - <Number> - <Title>", "Series"): "03 - Open Season",
                ("<Series> (<Year>) - <Title>", "Year"): "Batwoman - Open Season",
                ("<Series> - <Title>", None): "Batwoman - Open Season",
        }
        for (schema, vuoto), atteso in casi.items():
            self.assertEqual(comicinfo.nome_da_schema(schema, {**v, vuoto: ""}, 2), atteso)
        self.assertEqual(comicinfo.nome_da_schema("<Title>", {}, 2), "")


if __name__ == "__main__":
    unittest.main()
