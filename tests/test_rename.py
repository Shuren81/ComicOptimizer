"""Test della rinomina (headless). Uso, dalla cartella del progetto:

    venv/bin/python tests/test_rename.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from comicoptimizer.utils import apply_schema, capitalize_words, clean_filename, underscores_to_spaces


def test_utils():
    # <num>: tiene il numero vero e lo uniforma nelle cifre (numerazione sparsa)
    for stem, want in (("naruto_12", "Naruto - #012"), ("Naruto ch 3", "Naruto - #003"),
                       ("NARUTO-007", "Naruto - #007"), ("Naruto 1000", "Naruto - #1000")):
        assert apply_schema(stem, "Naruto - #<num>", 1, 3) == want, stem
    # <parteN>: testata - numero - storia - numero
    z = "zagor_-_45_-_il_ritorno_-_2"
    assert apply_schema(z, "<parte1> - #<num> - <parte3>", 1, 3) == "zagor - #045 - il_ritorno"
    assert capitalize_words(underscores_to_spaces(
        apply_schema(z, "<parte1> - #<num> - <parte3>", 1, 3))) == "Zagor - #045 - Il Ritorno"
    assert apply_schema("Spider-Man - 3", "<parte1>", 1, 3) == "Spider-Man"   # trattino senza spazi
    # <n> progressivo, <nome>
    assert apply_schema("x", "<nome> <n>", 7, 2) == "x 07"
    for stem, schema, err in (("Senza numeri", "<num>", "numero"), ("zagor 12", "<parte3>", "parte 3")):
        try:
            apply_schema(stem, schema, 1, 3)
            raise AssertionError("doveva fallire")
        except ValueError as e:
            assert err in str(e)
    assert underscores_to_spaces("a__b_ c_") == "a b c"
    assert capitalize_words("l'alba dei DC (edizione) spider-man") == "L'alba Dei DC (Edizione) Spider-Man"
    assert clean_filename(' a/b:c? ') == "a_b_c_"


def test_dialog_and_window(work):
    from comicoptimizer.dialogs import RenameDialog
    from comicoptimizer.main_window import MainWindow

    def touch(name):
        p = os.path.join(work, name)
        open(p, "wb").write(b"x")
        return p

    a, b, c = touch("naruto_10.cbz"), touch("naruto_2.cbr"), touch("altro.pdf")
    touch("Naruto - #002.cbz")                       # occupa già il nome di b
    folder = os.path.join(work, "cartella_img")
    os.makedirs(folder)

    d = RenameDialog([a, b, c, folder])
    assert [os.path.basename(p) for p in d.paths] == ["altro.pdf", "cartella_img", "naruto_2.cbr", "naruto_10.cbz"]
    assert d.renames() == [] and not d.b_ok.isEnabled()           # <nome>: niente da fare
    d.schema.setText("Naruto - #<num>")
    notes = [d.table.item(i, 2).text() for i in range(4)]
    assert "numero" in notes[0] and "numero" in notes[1]         # altro.pdf, cartella: rosse
    assert "⚠" not in notes[2] and "⚠" not in notes[3]           # .cbr vs .cbz: estensioni diverse, ok
    assert len(d.renames()) == 2
    d.table.item(2, 1).setText("Naruto - #002")                   # niente: ext .cbr, il file esistente è .cbz
    d.table.item(3, 1).setText("Naruto - #002")
    d.start.setValue(1)
    # modifica a mano: la .cbz finisce su un nome già esistente → rossa
    d.schema.setText("Naruto - #<num>")
    d.table.item(3, 1).setText("Naruto - #002")
    assert "esiste già" in d.table.item(3, 2).text()
    d.table.item(3, 1).setText("Naruto - #010")
    d.table.item(1, 1).setText("Naruto - #010")                   # cartella: nessuna estensione, ok
    d.table.item(0, 1).setText("Naruto - #010")                   # .pdf: ok (estensione diversa)
    assert {os.path.basename(t) for _, t in d.renames()} == {"Naruto - #010", "Naruto - #010.pdf",
                                                             "Naruto - #002.cbr", "Naruto - #010.cbz"}
    # stesso nome ma estensioni diverse: nessun problema
    for r in (0, 2, 3):
        d.table.item(r, 1).setText("Uguale")
    assert not any("⚠" in d.table.item(r, 2).text() for r in (0, 2, 3))
    d.table.item(0, 1).setText("Naruto - #010")
    # tasti sulle righe selezionate
    d.table.item(1, 1).setText("cartella_img")
    d.table.selectRow(1)
    d._transform(underscores_to_spaces)
    d._transform(capitalize_words)
    assert d.table.item(1, 1).text() == "Cartella Img"
    assert d.table.item(0, 1).text() == "Naruto - #010"           # riga non selezionata: intatta

    # due righe con lo stesso nome finale (stessa estensione)
    e1, e2 = touch("x 1.cbz"), touch("x 2.cbz")
    d2 = RenameDialog([e1, e2])
    d2.schema.setText("Uguale")
    assert "⚠" not in d2.table.item(0, 2).text() and "ripetuto" in d2.table.item(1, 2).text()
    assert len(d2.renames()) == 1
    # caso singolo: lo schema è il nome attuale; solo maiuscole sullo stesso file è permesso
    d3 = RenameDialog([e1])
    assert d3.schema.text() == "x 1" and not d3.b_ok.isEnabled()
    d3.schema.setText("X 1")
    assert d3.renames() == [(e1, os.path.join(work, "X 1.cbz"))]

    # finestra principale: pulsante, rinomina reale, card aggiornate, nessuna sovrascrittura
    w = MainWindow()
    w.show()
    w.import_files([(a, 1), (b, 1)])
    w.cards[a].selected = True
    w.handle_selection(w.cards[a], Qt.KeyboardModifier.NoModifier)
    QApplication.processEvents()
    assert w.btn_rename.isVisible()

    import comicoptimizer.main_window as mw

    class FakeDialog:
        def __init__(self, paths, parent=None):
            pass

        def exec(self):
            return True

        def renames(self):
            return [(a, os.path.join(work, "Naruto - #010.cbz")),
                    (b, os.path.join(work, "Naruto - #002.cbz"))]   # esiste: va rifiutata

    mw.RenameDialog = FakeDialog
    mw.QMessageBox.warning = lambda *args: None
    w.rename_cards([a, b])
    assert os.path.exists(os.path.join(work, "Naruto - #010.cbz")) and not os.path.exists(a)
    assert os.path.exists(b) and open(os.path.join(work, "Naruto - #002.cbz"), "rb").read() == b"x"
    assert sorted(os.path.basename(p) for p in w.cards) == ["Naruto - #010.cbz", "naruto_2.cbr"]
    assert w.cards[os.path.join(work, "Naruto - #010.cbz")].name.text() == "Naruto - #010.cbz"
    assert not w.btn_rename.isVisible()
    w._closing = True


if __name__ == "__main__":
    app = QApplication([])
    test_utils()
    with tempfile.TemporaryDirectory() as work:
        test_dialog_and_window(work)
    print("TUTTO OK")
