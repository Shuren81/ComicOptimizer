"""Test della rinomina (headless). Uso, dalla cartella del progetto:

    venv/bin/python tests/test_rename.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPointF, QSettings, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from comicoptimizer.utils import (
    apply_schema,
    capitalize_words,
    clean_filename,
    name_parts,
    underscores_to_spaces,
    wildcard_replace,
)


def test_utils():
    # <num>: tiene il numero vero e lo uniforma nelle cifre (numerazione sparsa)
    for stem, want in (("naruto_12", "Naruto - #012"), ("Naruto ch 3", "Naruto - #003"),
                       ("NARUTO-007", "Naruto - #007"), ("Naruto 1000", "Naruto - #1000")):
        assert apply_schema(stem, "Naruto - #<num>", 1, 3) == want, stem
    # parti: ai " - " e ai numeri staccati (anche con #); non nelle parole né nei numeri attaccati
    for stem, want in (("titolo 43 sottotitolo", ["titolo", "43", "sottotitolo"]),
                       ("Batman #12 La notte", ["Batman", "12", "La notte"]),
                       ("zagor_-_45_-_il_ritorno_-_2", ["zagor", "45", "il_ritorno", "2"]),
                       ("Spider-Man 2099 - Nuovo", ["Spider-Man", "2099", "Nuovo"]),
                       ("Cap 12 13 foo", ["Cap", "12", "13", "foo"]),
                       ("X-Men2 storia", ["X-Men2 storia"]), ("Vol.3 x", ["Vol.3 x"])):
        assert name_parts(stem) == want, (stem, name_parts(stem))
    assert name_parts("Fantastici 4 - La saga", split_numbers=False) == ["Fantastici 4", "La saga"]
    # A: le parti di sole cifre prendono le cifre scelte
    assert apply_schema("titolo 43 sottotitolo", "<parte1> - #<parte2> - <parte3>", 1, 3) \
        == "titolo - #043 - sottotitolo"
    z = "zagor_-_45_-_il_ritorno_-_2"
    assert capitalize_words(underscores_to_spaces(
        apply_schema(z, "<parte1> - #<num> - <parte3>", 1, 3))) == "Zagor - #045 - Il Ritorno"
    assert apply_schema("x", "<nome> <n>", 7, 2) == "x 07"
    # <anno>: preferito quello tra parentesi; 0245 non è un anno
    assert apply_schema("Absolute Batman 024 (2024) (Digital) (Shan-Empire)", "<parte1> (<anno>) #<parte2>", 1, 3) \
        == "Absolute Batman (2024) #024"
    assert apply_schema("Batman 2016 050 (2025)", "<anno>", 1, 3) == "2025"
    assert apply_schema("Batman 2016 050", "<anno>", 1, 3) == "2016"
    try:
        apply_schema("Zagor 0245 x 12025", "<anno>", 1, 3)
        raise AssertionError("doveva fallire")
    except ValueError as e:
        assert "anno" in str(e)
    assert capitalize_words(underscores_to_spaces(apply_schema("jujika_no_rokunin_v3", "<parte1> Vol. <num:2>", 1, 3))) \
        == "Jujika No Rokunin V3 Vol. 03"
    assert apply_schema("Jujika no Rokunin 3", "<parte1> Vol. <parte2:2>", 1, 3) == "Jujika no Rokunin Vol. 03"
    assert apply_schema("Jujika no Rokunin 12", "<parte1> Ch. <parte2>", 1, 3) == "Jujika no Rokunin Ch. 012"
    # campi scritti a mano: autore, editore, edizione, lingua
    full = {"autore": "Kentaro Miura", "editore": "Panini", "edizione": "Ultimate", "lingua": "ITA"}
    assert apply_schema("Berserk 3", "<parte1> (<autore>) (<editore>) (<edizione>) Vol. <parte2:2> [<lingua>]",
                        1, 3, fields=full) == "Berserk (Kentaro Miura) (Panini) (Ultimate) Vol. 03 [ITA]"
    for key in full:
        try:
            apply_schema("Berserk 3", f"<parte1> <{key}>", 1, 3, fields={**full, key: "  "})
            raise AssertionError("doveva fallire")
        except ValueError as e:
            assert str(e) == f"campo {key} vuoto"
    assert apply_schema("Berserk 3", "<parte1>", 1, 3, fields={}) == "Berserk"     # campi non usati: ignorati
    # cifre per singolo segnaposto
    assert apply_schema("a 45 b 2", "<parte2> <parte4:1> <num:4> <n:2>", 7, 3) == "045 2 0045 07"
    corvo = apply_schema("romanzi_a_fumetti_008_il_corvo_2", "<parte1> #<parte2> - <parte3> (Vol. <parte4:1>)", 1, 3)
    assert capitalize_words(underscores_to_spaces(corvo)) == "Romanzi A Fumetti #008 - Il Corvo (Vol. 2)"
    for stem, schema, err in (("Senza numeri", "<num>", "numero"), ("zagor 12", "<parte3>", "parte 3")):
        try:
            apply_schema(stem, schema, 1, 3)
            raise AssertionError("doveva fallire")
        except ValueError as e:
            assert err in str(e)
    # jolly
    assert wildcard_replace("Titolo (2019) (Digital)", "(*)", "") == "Titolo  "
    assert wildcard_replace("Naruto Vol 3 extra", "Vol*", "Volume") == "Naruto Volume"
    assert wildcard_replace("Cap 12 e cap 07", "cap ??", "C") == "C e C"
    assert wildcard_replace("NARUTO", "naruto", "N") == "N"
    assert wildcard_replace("NARUTO", "naruto", "N", case=True) == "NARUTO"
    assert wildcard_replace("abc", "*", "X") == "X"
    assert wildcard_replace("a.b", ".", "\\1") == "a\\1b"              # tutto alla lettera
    assert wildcard_replace("abc", "", "X") == "abc"
    # jolly in Sostituisci: rimettono il testo trovato, in ordine
    post = lambda s: " ".join(s.split())                           # spazi doppi tolti, come nella finestra
    assert post(wildcard_replace("Titolo [ testo ] 2", "[*]", "*")) == "Titolo testo 2"
    assert wildcard_replace("Zagor (Il ritorno)", "(*)", "- *") == "Zagor - Il ritorno"
    assert wildcard_replace("Cap 07", "Cap ??", "Capitolo ??") == "Capitolo 07"
    assert wildcard_replace("Tex - Speciale", "* - *", "* (*)") == "Tex (Speciale)"
    assert wildcard_replace("a [b] c [d]", "[*]", "<*>") == "a <b> c <d>"   # ogni gruppo
    assert wildcard_replace("x (y)", "(*)", "* * *") == "x y  "             # jolly in più: vuoti
    assert wildcard_replace("abc", "*", "X *") == "X abc"
    assert underscores_to_spaces("a__b_ c_") == "a b c"
    assert capitalize_words("l'alba dei DC (edizione) spider-man") == "L'alba Dei DC (Edizione) Spider-Man"
    assert clean_filename(' a/b:c? ') == "a_b_c_"


def click_row(table, row, drag_to=None, ctrl=False):
    """Click su una riga (o trascinamento fino a `drag_to`) nella tabella, con Ctrl se `ctrl`."""
    vp = table.viewport()
    p0 = table.visualRect(table.model().index(row, 0)).center()
    p1 = table.visualRect(table.model().index(drag_to if drag_to is not None else row, 0)).center()
    L = Qt.MouseButton.LeftButton
    send = lambda kind, p, btns: QApplication.sendEvent(
        vp, QMouseEvent(kind, QPointF(p), QPointF(vp.mapToGlobal(p)), L, btns,
                        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, p0, L)
    if drag_to is not None:
        send(QEvent.Type.MouseMove, p1, L)
    send(QEvent.Type.MouseButtonRelease, p1, Qt.MouseButton.NoButton)


def test_dialog(work):
    from comicoptimizer.dialogs import RenameDialog

    def touch(name):
        p = os.path.join(work, name)
        open(p, "wb").write(b"x")
        return p

    a, b, c = touch("naruto_10.cbz"), touch("naruto_2.cbr"), touch("altro.pdf")
    touch("Naruto - #002.cbz")                       # occupa un nome
    folder = os.path.join(work, "cartella_img")
    os.makedirs(folder)

    d = RenameDialog([a, b, c, folder])
    d.show()
    col = lambda: [d.table.item(i, 1).text() for i in range(4)]
    note = lambda i: d.table.item(i, 2).text()
    assert [os.path.basename(p) for p in d.paths] == ["altro.pdf", "cartella_img", "naruto_2.cbr", "naruto_10.cbz"]
    assert d.renames() == [] and not d.b_ok.isEnabled()           # <nome>: niente da fare
    d.schema.setEditText("Naruto - #<num>")
    assert "numero" in note(0) and "numero" in note(1)           # altro.pdf, cartella: rosse
    assert len(d.renames()) == 2 and d.b_ok.text() == "Rinomina 2 di 4"   # (bug "<n> di")

    # Cerca/Sostituisci in tempo reale, con jolly; svuotando torna com'era
    d.schema.setEditText("<nome>")
    d.find.setText("naruto_*")
    d.repl.setText("N ")
    assert col() == ["altro", "cartella_img", "N", "N"]
    d.find.setText("NARUTO")                                       # senza maiuscole/minuscole: trova
    assert col()[2] == "N _2"
    d.case.setChecked(True)
    assert col()[2] == "naruto_2"
    d.case.setChecked(False)
    d.find.setText("")
    assert col() == ["altro", "cartella_img", "naruto_2", "naruto_10"]
    # interruttori: accesi/spenti
    d.b_us.setChecked(True)
    d.b_cap.setChecked(True)
    assert col() == ["Altro", "Cartella Img", "Naruto 2", "Naruto 10"]
    d.b_cap.setChecked(False)
    assert col()[1] == "cartella img"

    # selezione col mouse: le operazioni valgono solo sulle righe selezionate
    click_row(d.table, 1)
    assert col() == ["altro", "cartella img", "naruto_2", "naruto_10"]
    click_row(d.table, 1)                                          # click di nuovo: deseleziona
    assert d.table.selectedIndexes() == [] and col()[2] == "naruto 2"
    click_row(d.table, 0, drag_to=2)                               # trascina: seleziona 0-2
    rows = lambda: sorted({i.row() for i in d.table.selectedIndexes()})
    assert rows() == [0, 1, 2] and col()[3] == "naruto_10"
    click_row(d.table, 1, drag_to=2, ctrl=True)                    # Ctrl da una selezionata: toglie
    assert rows() == [0]
    # con righe selezionate si rinominano solo quelle, e <n> conta solo loro
    click_row(d.table, 3, ctrl=True)                               # Ctrl+click: aggiunge
    d.schema.setEditText("X <n>")
    assert col() == ["X 001", "cartella_img", "naruto_2", "X 002"]
    assert [os.path.basename(t) for _, t in d.renames()] == ["X 001.pdf", "X 002.cbz"]
    assert d.b_ok.text() == "Rinomina 2 di 4"
    d.schema.setEditText("<nome>")
    d.table.clearSelection()
    d.b_us.setChecked(False)

    # una sola riga selezionata: lo Schema mostra il suo nome e vale solo per lei
    d.table.clearSelection()
    d.schema.setEditText("X <n>")
    click_row(d.table, 2)
    assert d.schema.currentText() == "naruto_2"
    d.schema.setEditText("Naruto due")
    assert col() == ["altro", "cartella_img", "Naruto due", "naruto_10"]
    click_row(d.table, 3, ctrl=True)                               # seconda riga: torna lo schema
    assert d.schema.currentText() == "X <n>" and "a mano" in note(2)
    assert col() == ["altro", "cartella_img", "Naruto due", "X 001"]
    click_row(d.table, 3, ctrl=True)                               # di nuovo una sola (la 2)
    assert d.schema.currentText() == "Naruto due"                  # mostra la correzione a mano
    click_row(d.table, 0)                                          # click semplice: solo quella riga
    assert rows() == [0] and d.schema.currentText() == "altro"
    click_row(d.table, 0)                                          # di nuovo sulla stessa: deseleziona
    assert rows() == []
    assert d.schema.currentText() == "X <n>" and col()[2] == "Naruto due"
    click_row(d.table, 0)                                          # nome non cambiato: niente "a mano"
    d.table.clearSelection()
    assert "a mano" not in note(0)
    d.table.item(2, 1).setText("")                                 # via la correzione
    d.schema.setEditText("<nome>")

    # correzioni a mano: fisse; svuotando la cella torna l'automatico
    d.table.item(3, 1).setText("Naruto - #002")
    assert "esiste già" in note(3) and "a mano" in note(3)
    d.schema.setEditText("X <n>")
    assert d.table.item(3, 1).text() == "Naruto - #002" and col()[2] == "X 003"
    d.table.item(3, 1).setText("")
    assert d.table.item(3, 1).text() == "X 004" and "a mano" not in note(3)

    # aiuto: area che scorre (il testo è più lungo della finestra)
    h = d.help_dialog()
    h.resize(500, 350)
    h.show()
    QApplication.processEvents()
    assert h.text.verticalScrollBar().maximum() > 0 and "Come conviene" in h.text.toPlainText()
    h.close()

    # caselle Autore/Editore/…: anteprima subito, casella vuota → riga rossa, "/" → "_"
    d.schema.setEditText("<nome> (<autore>)")
    assert "campo autore vuoto" in note(0) and not d.b_ok.isEnabled()
    d.fields["autore"].setText("AC/DC")
    assert col()[0] == "altro (AC/DC)" and os.path.basename(d.renames()[0][1]) == "altro (AC_DC).pdf"
    d.fields["autore"].setText("")
    d.schema.setEditText("<nome>")

    # due righe con lo stesso nome finale (stessa estensione)
    e1, e2 = touch("x 1.cbz"), touch("x 2.cbz")
    d2 = RenameDialog([e1, e2])
    d2.schema.setEditText("Uguale")
    assert "⚠" not in d2.table.item(0, 2).text() and "ripetuto" in d2.table.item(1, 2).text()
    assert len(d2.renames()) == 1 and d2.b_ok.text() == "Rinomina 1 di 2"
    # caso singolo: lo schema è il nome attuale; solo maiuscole sullo stesso file è permesso
    d3 = RenameDialog([e1])
    assert d3.schema.currentText() == "x 1" and not d3.b_ok.isEnabled()
    d3.schema.setEditText("X 1")
    assert d3.renames() == [(e1, os.path.join(work, "X 1.cbz"))]

    # B: schemi recenti (solo schemi con segnaposto, max 10, senza doppioni)
    for i in range(12):
        dd = RenameDialog([e1, e2])
        dd.schema.setEditText(f"S{i} <n>")
        dd.accept()
    dd = RenameDialog([e1, e2])
    dd.schema.setEditText("S5 <n>")
    dd.accept()
    d3.accept()                                                    # nome singolo: non salvato
    recent = RenameDialog([e1]).schema
    items = [recent.itemText(i) for i in range(recent.count())]
    assert items[0] == "S5 <n>" and items.count("S5 <n>") == 1, items
    assert items[:10] == ["S5 <n>"] + [f"S{i} <n>" for i in (11, 10, 9, 8, 7, 6, 4, 3, 2)], items
    assert items[10] == "" and "X 1" not in items                  # separatore, poi gli schemi pronti
    assert [recent.itemData(i) for i in range(11, recent.count())] == [s for s, _ in RenameDialog.PRESETS]
    assert items[11] == "Manga a volumi  ·  <parte1> (<autore>) Vol. <parte2:2>"   # con la descrizione
    recent.activated.emit(11)                                      # scelto dal menu: nel campo solo lo schema
    assert recent.currentText() == "<parte1> (<autore>) Vol. <parte2:2>"
    # uno schema pronto già tra i recenti non compare due volte
    dd = RenameDialog([e1, e2])
    dd.schema.setEditText(RenameDialog.PRESETS[1][0])
    dd.accept()
    combo = RenameDialog([e1]).schema
    items = [combo.itemText(i) for i in range(combo.count())]
    schemas = [combo.itemData(i) or items[i] for i in range(combo.count())]
    assert schemas.count(RenameDialog.PRESETS[1][0]) == 1 and items[0] == RenameDialog.PRESETS[1][0]


def test_window(work):
    import comicoptimizer.main_window as mw
    from comicoptimizer.main_window import MainWindow

    def touch(name):
        p = os.path.join(work, name)
        open(p, "wb").write(b"x")
        return p

    a, b = touch("naruto_10.cbz"), touch("naruto_2.cbr")
    taken = touch("Naruto - #002.cbz")
    w = MainWindow()
    w.show()
    w.import_files([(a, 1), (b, 1)])
    w.cards[a].selected = True
    w.handle_selection(w.cards[a], Qt.KeyboardModifier.NoModifier)
    QApplication.processEvents()
    assert w.btn_rename.isVisible() and not w.btn_undo_rename.isVisible()

    new_a = os.path.join(work, "Naruto - #010.cbz")

    class FakeDialog:
        def __init__(self, paths, parent=None, on_rename=None):
            self.on_rename = on_rename

        def exec(self):
            self.done_pairs = self.on_rename(self.renames())    # come un click su "Rinomina"
            return 0

        def renames(self):
            return [(a, new_a), (b, taken)]                      # la seconda esiste: va rifiutata

    mw.RenameDialog = FakeDialog
    warnings = []
    mw.QMessageBox.warning = lambda *args: warnings.append(args[-1])
    w.rename_cards([a, b])
    assert os.path.exists(new_a) and not os.path.exists(a)
    assert os.path.exists(b) and open(taken, "rb").read() == b"x"
    assert sorted(os.path.basename(p) for p in w.cards) == ["Naruto - #010.cbz", "naruto_2.cbr"]
    assert w.cards[new_a].name.text() == "Naruto - #010.cbz"
    assert not w.btn_rename.isVisible() and len(warnings) == 1
    QApplication.processEvents()

    # C: annulla rinomina
    assert w.btn_undo_rename.isVisible() and w._last_renames == [(a, new_a)]
    w.undo_rename()
    assert os.path.exists(a) and not os.path.exists(new_a) and a in w.cards
    assert not w.btn_undo_rename.isVisible()
    # vecchio nome occupato nel frattempo: quel file non si tocca
    w.rename_cards([a, b])
    touch("naruto_10.cbz")
    w.undo_rename()
    assert os.path.exists(new_a) and new_a in w.cards and len(warnings) == 3
    # "Pulisci lista" toglie la possibilità di annullare
    w.rename_cards([a, b])
    w.clear_all()
    assert w._last_renames == [] and not w.btn_undo_rename.isVisible()
    w._closing = True


def test_keep_open(work):
    """Dopo "Rinomina" la finestra resta aperta e riparte dai nomi nuovi; si annulla tutto."""
    from comicoptimizer.dialogs import RenameDialog
    from comicoptimizer.main_window import MainWindow

    paths = []
    for n in ("berserk_1.cbz", "berserk_2.cbz"):
        p = os.path.join(work, n)
        open(p, "wb").write(b"x")
        paths.append(p)
    w = MainWindow()
    w.import_files([(p, 1) for p in paths])
    d = RenameDialog(paths, w, on_rename=w._do_renames)
    d.show()
    # 1° passaggio: _ → spazio e maiuscole
    d.b_us.setChecked(True)
    d.b_cap.setChecked(True)
    d.schema.lineEdit().returnPressed.emit()                       # Invio: rinomina senza chiudere
    assert d.isVisible() and d.status.text() == "✓ 2 rinominati"
    first = [os.path.join(work, "Berserk 1.cbz"), os.path.join(work, "Berserk 2.cbz")]
    assert all(os.path.exists(p) for p in first) and d.paths == first
    assert d.table.item(0, 0).text() == "Berserk 1.cbz" and d.schema.currentText() == "<nome>"
    assert not d.b_us.isChecked() and d.renames() == [] and not d.b_ok.isEnabled()
    # 2° passaggio sui nomi nuovi, con il campo Autore
    d.fields["autore"].setText("Kentaro Miura")
    d.schema.setEditText("<parte1> (<autore>) Vol. <parte2:2>")
    d.b_ok.click()
    final = [os.path.join(work, f"Berserk (Kentaro Miura) Vol. 0{i}.cbz") for i in (1, 2)]
    assert d.paths == final and all(os.path.exists(p) for p in final)
    assert d.fields["autore"].text() == "Kentaro Miura"            # le caselle restano
    assert sorted(w.cards) == final
    # 🔍 Cerca (ricerca finta, senza rete): titolo proposto dal nome, scelta, casella riempita
    import comicoptimizer.dialogs as dg
    import comicoptimizer.online as online
    from PyQt6.QtTest import QTest
    asked = []
    dg.QInputDialog.getText = lambda *a, **k: (asked.append(k.get("text")), ("Berserk", True))[1]
    dg.QInputDialog.getItem = lambda parent, title, label, items, *a: (items[1], True)
    online.search_authors = lambda title: [
        {"title": "Berserk", "desc": "film", "source": "Wikidata", "authors": ["Qualcuno"]},
        {"title": "Berserk", "desc": "manga", "source": "Wikidata", "authors": ["Kentarō Miura", "Kouji Mori"]}]
    d.fields["autore"].clear()
    d.b_search.click()
    for _ in range(100):
        QTest.qWait(20)
        if d.b_search.isEnabled():
            break
    assert asked == ["Berserk"], asked                            # titolo pulito proposto
    assert d.fields["autore"].text() == "Kentarō Miura, Kouji Mori"
    # Chiudi: "Annulla rinomina" annulla tutti e due i passaggi
    d.reject()
    w._set_undo(d.done_pairs)
    w.undo_rename()
    assert all(os.path.exists(p) for p in paths) and sorted(w.cards) == sorted(paths)
    w._closing = True


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        # impostazioni (schemi recenti) in una cartella temporanea, non in quelle vere
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, work)
        test_utils()
        os.makedirs(os.path.join(work, "d"))
        test_dialog(os.path.join(work, "d"))
        os.makedirs(os.path.join(work, "w"))
        test_window(os.path.join(work, "w"))
        os.makedirs(os.path.join(work, "k"))
        test_keep_open(os.path.join(work, "k"))
    print("TUTTO OK")
