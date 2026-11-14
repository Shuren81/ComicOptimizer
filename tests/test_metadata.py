"""Test della finestra Info e rinomina (headless), senza rete. Uso:

    venv/bin/python tests/test_metadata.py
"""
import os
import shutil
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QEvent, QPointF, QSettings, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox


def cbz(path, ci=None):
    immagine = path + ".png"
    Image.new("RGB", (40, 60), "red").save(immagine)
    with zipfile.ZipFile(path, "w") as z:
        z.write(immagine, "0001.png")
        z.writestr("0002.png", open(immagine, "rb").read())
        if ci:
            z.writestr("ComicInfo.xml", ci)
    os.remove(immagine)
    return path


def xml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("ComicInfo.xml"))


def attendi(app, condizione, secondi=20):
    fine = time.time() + secondi
    while time.time() < fine:
        app.processEvents()
        if condizione():
            return True
        time.sleep(0.01)
    return False


def seleziona(d, *righe):
    d.lista.clearSelection()
    for r in righe:
        d.lista.item(r).setSelected(True)
    app = QApplication.instance()
    app.processEvents()


def scrivi(d, campo, testo):
    """Come se lo scrivessi tu: textEdited parte solo per le modifiche dell'utente."""
    casella = d.caselle[campo]
    casella.setText(testo)
    casella.textEdited.emit(testo)


def rispondi(app, si=True):
    """Risponde al prossimo messaggio o alla prossima conferma."""
    def premi():
        w = app.activeModalWidget()
        if isinstance(w, QMessageBox):
            w.button(w.StandardButton.Yes if si else w.StandardButton.No).click()
        elif w is not None and hasattr(w, "b_si"):
            (w.b_si if si else w.b_no).click()
        else:
            QTimer.singleShot(20, premi)
    QTimer.singleShot(20, premi)


def test_finestra(app, work, md):
    a = cbz(os.path.join(work, "a_01.cbz"),
            "<ComicInfo><Series>DYLAN DOG</Series><Notes>tienimi</Notes><Number>007</Number></ComicInfo>")
    b = cbz(os.path.join(work, "b_02.cbz"), "<ComicInfo><Series>Altra</Series></ComicInfo>")
    rinominati = []

    def rinomina(coppie):
        for v, n in coppie:
            os.rename(v, n)
        rinominati.extend(coppie)
        return coppie

    d = md.MetadataDialog([b, a], on_rename=rinomina)
    assert d.paths == [a, b] and d.selezione == [a, b]

    # Anche nella finestra più piccola Salva e Rinomina restano in vista
    d.resize(d.minimumSize())
    d.show()
    app.processEvents()
    for pulsante in (d.b_salva, d.b_rinomina):
        fondo = pulsante.mapTo(d, pulsante.rect().bottomRight())
        assert pulsante.isVisible() and d.rect().contains(fondo), (fondo, d.size())

    # --- più file: i valori diversi si segnalano e guardarli non basta a modificarli
    assert d.caselle["Series"].text() == "" and "Series" in d.diversi and d.legenda.isHidden() is False
    assert d.etichette["Series"].text() == "Series ≠"
    seleziona(d, 0)
    seleziona(d, 0, 1)
    assert not d.pending

    # --- un file: maiuscole corrette a video, numero pulito, niente modifiche senza un tuo gesto
    seleziona(d, 0)
    assert d.caselle["Series"].text() == "Dylan Dog" and d.caselle["Number"].text() == "7"
    seleziona(d, 1)
    assert not d.pending

    # --- la modifica resta al file giusto cambiando selezione
    scrivi(d, "Title", "Il titolo")
    seleziona(d, 0)
    assert d.pending == {b: {"Title": "Il titolo"}} and d.caselle["Title"].text() == ""
    seleziona(d, 1)
    assert d.caselle["Title"].text() == "Il titolo"
    scrivi(d, "Title", "")                            # tornata uguale al file: nessuna modifica
    seleziona(d, 0)
    assert not d.pending

    # --- più file: valore comune su tutti, Svuota toglie
    seleziona(d, 0, 1)
    scrivi(d, "Writer", "Sclavi")
    scrivi(d, "LanguageISO", "Italiano")
    d._ricorda_lingua()
    assert QSettings(*md.SETTINGS).value("metadati/ultima_lingua") == "it"
    d.numera.setChecked(True)
    d.inizio.setValue(10)
    rispondi(app)
    d.salva()
    assert attendi(app, lambda: not d.salvataggio_in_corso)
    ra, rb = xml(a), xml(b)
    assert ra.findtext("Writer") == rb.findtext("Writer") == "Sclavi"
    assert ra.findtext("LanguageISO") == "it"
    assert (ra.findtext("Number"), rb.findtext("Number")) == ("10", "11")
    assert ra.findtext("Notes") == "tienimi", "i tag non gestiti restano"
    assert ra.findtext("Series") == "Dylan Dog", "un file salvato non resta tutto maiuscolo"
    assert rb.findtext("Series") == "Altra"
    assert not d.pending
    d.numera.setChecked(False)

    d.svuota["Writer"].setChecked(True)
    assert not d.caselle["Writer"].isEnabled()
    rispondi(app)
    d.salva()
    assert attendi(app, lambda: not d.salvataggio_in_corso)
    assert xml(a).find("Writer") is None and xml(b).find("Writer") is None

    # --- lingua sbagliata: non si scrive nulla
    seleziona(d, 0)
    prima = open(a, "rb").read()
    scrivi(d, "LanguageISO", "italiano!")
    QTimer.singleShot(20, lambda: app.activeModalWidget().accept())
    d.salva()
    assert open(a, "rb").read() == prima
    scrivi(d, "LanguageISO", "it")

    # --- manga: su più file diversi la casella non tocca nulla finché non la cambi
    d.manga.click()
    d.salva()
    assert attendi(app, lambda: not d.salvataggio_in_corso)
    assert xml(a).findtext("Manga") == "YesAndRightToLeft"
    seleziona(d, 0, 1)
    assert d.manga.checkState() == Qt.CheckState.PartiallyChecked
    seleziona(d, 0)
    assert not d.pending

    # --- bottoni dei tag: verdi se in uso, il secondo clic toglie
    d.schema.setEditText("<Series> - #<Number> - <Title>")
    assert d.bottoni_tag["Number"].property("variant") == "success"
    assert not d.bottoni_tag["Year"].property("variant")
    d.bottoni_tag["Number"].click()
    assert d.schema.currentText() == "<Series> - <Title>"
    assert not d.bottoni_tag["Number"].property("variant")
    d.schema.lineEdit().setCursorPosition(len(d.schema.currentText()))
    d.bottoni_tag["Year"].click()
    assert d.schema.currentText() == "<Series> - <Title><Year>"
    assert d.bottoni_tag["Year"].property("variant") == "success"

    # --- estrazione: "_" come spazio, non trovato segnalato
    attiva, combo, dopo, fino = d.regole[0]
    combo.setCurrentText("Series")
    fino.setText("0")
    fino.textEdited.emit("0")
    attiva.setChecked(True)
    assert d.caselle["Series"].text() == "A", d.caselle["Series"].text()
    assert "Series" in d.automatici
    attiva.setChecked(False)
    fino.setText("")
    seleziona(d, 0, 1)
    seleziona(d, 0)

    # --- rinomina: nome dai metadati, barre e due punti ripuliti, conferma per più file
    scrivi(d, "Series", "Batman/Tartarughe")
    scrivi(d, "Title", "Crisi: guscio")
    d.schema.setEditText("<Series> - #<Number> - <Title>")
    assert d.anteprima_nome.text() == "Batman-Tartarughe - #010 - Crisi - Guscio.cbz", d.anteprima_nome.text()
    d.rinomina()
    nuovo_a = os.path.join(work, "Batman-Tartarughe - #010 - Crisi - Guscio.cbz")
    assert rinominati == [(a, nuovo_a)] and os.path.exists(nuovo_a)
    assert d.paths[0] == nuovo_a and d.lista.item(0).text() == os.path.basename(nuovo_a)
    assert nuovo_a in d.pending, "le modifiche non salvate seguono il file"
    assert QSettings(*md.SETTINGS).value("metadati/schemi_recenti")[0] == "<Series> - #<Number> - <Title>"
    d.salva()                                         # un file solo: nessuna conferma
    assert attendi(app, lambda: not d.salvataggio_in_corso)
    assert xml(nuovo_a).findtext("Series") == "Batman/Tartarughe"

    # --- stesso nome su più file: suffisso, mai sovrascrivere; Annulla non cambia nulla
    seleziona(d, 0, 1)
    d.schema.setEditText("Uguale")
    rinominati.clear()
    rispondi(app, si=False)
    d.rinomina()
    assert not rinominati and os.path.exists(nuovo_a) and os.path.exists(b)
    rispondi(app)
    d.rinomina()
    assert sorted(os.path.basename(n) for _v, n in rinominati) == ["Uguale.cbz", "Uguale_1.cbz"]

    # --- chiusura con modifiche: chiede prima
    seleziona(d, 0)
    scrivi(d, "Title", "Non salvato")
    rispondi(app, si=False)
    d.reject()
    assert d.pending and d.result() == 0
    d.pending.clear()
    d.toccati.clear()
    d.reject()


def test_altri_formati(app, work, md):
    """Un file che non è un CBZ non si tocca: va alla conversione con le info."""
    rar = os.path.join(work, "finto.cbr")
    with open(rar, "wb") as f:
        f.write(b"Rar!\x1a\x07\x00altro")
    d = md.MetadataDialog([rar])
    assert not d.pending
    scrivi(d, "Series", "Serie Rar")
    scrivi(d, "Writer", "Autore")
    rispondi(app)
    d.salva()
    assert attendi(app, lambda: d.conversioni)
    info, destinazione = d.conversioni[rar]
    assert destinazione == os.path.join(work, "finto.cbz")
    assert info["titolo"] == "Serie Rar" and info["autore"] == "Autore" and info["manga"] is False
    assert open(rar, "rb").read().startswith(b"Rar!")


def test_cartella(app, work, md):
    """Rinominando una cartella non si aggiunge un'estensione."""
    cartella = os.path.join(work, "Vol. 2")
    os.makedirs(cartella)
    coppie = []
    d = md.MetadataDialog([cartella], on_rename=lambda c: (coppie.extend(c), c)[1])
    scrivi(d, "Series", "Serie")
    d.schema.setEditText("<Series>")
    d.rinomina()
    assert coppie == [(cartella, os.path.join(work, "Serie"))]
    d.pending.clear()
    d.toccati.clear()
    d.reject()


def test_ricerca(app, work, md):
    """Finestra di ricerca con una fonte finta: filtro, dettagli, chiave, Applica."""
    chiamate = []

    def cerca(chiave, query):
        chiamate.append((chiave, query))
        return [{"etichetta": "ROBIN 2", "copertina": None, "campi": {"Series": "ROBIN", "Number": "2"}, "note": ["una nota"]},
                {"etichetta": "BATMAN 1", "copertina": None, "campi": {"Series": "BATMAN", "Number": "1"}, "note": []}]

    def dettagli(_chiave, _r):
        return {"Writer": "Morrison", "Summary": "https://x\n\nTrama"}

    md.FONTI_RICERCA["Finta"] = {
        "chiave_config": "chiave_finta", "etichetta_chiave": "Chiave:", "aiuto": "aiuto",
        "url_aiuto": "https://example.invalid", "cerca": cerca, "dettagli": dettagli,
        "query_iniziale": lambda s, n: f"{s} {n}".strip(), "formatta_titoli": True}
    QSettings(*md.SETTINGS).setValue("ricerca/fonte", "Finta")

    a = cbz(os.path.join(work, "ricerca.cbz"), "<ComicInfo><Series>batman</Series></ComicInfo>")
    d = md.MetadataDialog([a])
    s = md.SearchDialog("ricerca", {c: d._leggi(c) for c in md.CAMPI_TESTO}, d)
    assert s.combo_fonte.currentText() == "Finta" and s.query.text() == "batman"

    # senza chiave non cerca, e il messaggio non lascia la finestra bloccata
    QTimer.singleShot(20, lambda: app.activeModalWidget().accept())
    s.cerca()
    assert not chiamate

    s.chiave.setText("segreta")
    s.cerca()
    assert attendi(app, lambda: s.lista.count() == 2)
    assert chiamate == [("segreta", "batman")] and s.b_cerca.isEnabled()
    assert [r["etichetta"] for r in s.visibili] == ["BATMAN 1", "ROBIN 2"], "prima chi somiglia alla ricerca"
    assert QSettings(*md.SETTINGS).value("ricerca/chiave_finta") == "segreta", "la chiave valida si ricorda"
    if os.name == "posix":
        assert os.stat(QSettings(*md.SETTINGS).fileName()).st_mode & 0o077 == 0, "chiavi leggibili solo da te"

    s.filtro.setText("robin")
    assert s.lista.count() == 1 and s.visibili[0]["etichetta"] == "ROBIN 2"
    s.lista.setCurrentRow(0)
    assert "una nota" in s.anteprima.toPlainText()
    assert s._selezionato()["dettagli_stato"] == "in corso"
    QTimer.singleShot(20, lambda: app.activeModalWidget().accept())
    s.applica()
    assert s.scelti is None, "Applica aspetta i dettagli"
    assert attendi(app, lambda: s._selezionato()["dettagli_stato"] == "ok")
    assert "Morrison" in s.anteprima.toPlainText()
    s.applica()
    assert s.scelti["Series"] == "ROBIN" and s.scelti["Writer"] == "Morrison"

    # Errore della fonte: messaggio chiaro e Cerca di nuovo attivo
    def rotta(_k, _q):
        raise md.ErroreRicerca("sito giù")
    md.FONTI_RICERCA["Finta"]["cerca"] = rotta
    s2 = md.SearchDialog("ricerca", {}, d)
    QTimer.singleShot(200, lambda: app.activeModalWidget().accept())
    s2.cerca()
    assert attendi(app, lambda: s2.b_cerca.isEnabled())

    # Applica riempie i campi come una tua modifica
    md.SearchDialog.exec = lambda self: setattr(self, "scelti", {"Series": "Robin", "Fuori": "x"}) or 1
    d.apri_ricerca()
    assert d.caselle["Series"].text() == "Robin" and d.pending == {} and "Series" in d.toccati
    d.toccati.clear()
    d.reject()

    # zeri davanti al numero: via dalla ricerca ("Green Lantern 040" troverebbe prima il 4, il 5…)
    assert md.senza_zeri("Green Lantern 040 (2026) (digital)") == "Green Lantern 40 (2026) (digital)"
    assert md.senza_zeri("Batman 0 - 007 #00") == "Batman 0 - 7 #0"
    assert md.SearchDialog("Green Lantern 040 (2026) (digital) (Pyrate-DCP)", {}, d).query.text() \
        .startswith("Green Lantern 40 (2026)")

    # più fumetti selezionati: uno alla volta. Applica → il prossimo, Salta lo lascia, Chiudi smette
    fs = [cbz(os.path.join(work, f"seq {i}.cbz"), "<ComicInfo></ComicInfo>") for i in (1, 2, 3)]
    d = md.MetadataDialog(fs)
    assert d.b_cerca.isEnabled() and d.b_chiudi.text() == "Chiudi"
    viste = []

    def una_scelta(self):
        viste.append((self.windowTitle(), d.selezione))
        n = len(viste)
        if n == 1:
            self.scelti = {"Series": "Uno"}
        elif n == 2:
            self._salta()
            return 1
        return 0 if n == 3 else 1                      # al terzo: Chiudi
    md.SearchDialog.exec, md.SearchDialog.cerca = una_scelta, lambda self: None
    d.apri_ricerca()
    assert [v[1] for v in viste] == [[fs[0]], [fs[1]], [fs[2]]], viste
    assert viste[0][0] == "Ricerca online — 1 di 3: seq 1", viste[0][0]
    d._conserva()
    assert d.pending == {fs[0]: {"Series": "Uno"}}, d.pending
    d.pending.clear()
    d.reject()
    assert md.MetadataDialog(fs[:1], chiudi="Avanti ▸ Lista di lavoro").b_chiudi.text() == "Avanti ▸ Lista di lavoro"
    del md.FONTI_RICERCA["Finta"]


def test_catena_e_cronologia(app, work, md):
    """Dal pulsante alla conversione vera e all'annullamento dopo il riavvio."""
    import comicoptimizer.main_window as mw
    from comicoptimizer import workers
    workers._trash_file_cross_platform = lambda p: bool(shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)) or True

    cartella = os.path.join(work, "Una cartella")
    os.makedirs(cartella)
    for i in range(2):
        Image.new("RGB", (40, 60), "blue").save(os.path.join(cartella, f"{i}.png"))
    a = cbz(os.path.join(work, "naruto_1.cbz"), "<ComicInfo><Series>Naruto</Series></ComicInfo>")

    w = mw.MainWindow()
    lavori = []
    w.process_paths = lambda paths, webp, extra: lavori.extend({"src": p, "lazy": True, "pages": 2, **extra(p)} for p in paths)

    def agisci(self):
        seleziona(self, 0)
        assert self.selezione == [cartella]
        scrivi(self, "Series", "Serie Cartella")
        scrivi(self, "Penciller", "Disegnatore")
        self.caselle["Summary"].setPlainText("Trama lunga")
        self.manga.click()
        rispondi(app)
        self.salva()
        assert attendi(app, lambda: self.conversioni)
        self.accept()
        return 1

    md.MetadataDialog.exec = agisci
    w.rename_cards([cartella])
    assert len(lavori) == 1 and lavori[0]["info_job"]
    uscite = []
    pw = workers.ProcessingWorker(lavori, to_webp=False)
    pw.job_done.connect(uscite.append)
    pw.run()
    finale = os.path.join(work, "Una cartella.cbz")
    r = xml(finale)
    assert r.findtext("Series") == "Serie Cartella" and r.findtext("Penciller") == "Disegnatore"
    assert r.findtext("Summary") == "Trama lunga" and r.findtext("Manga") == "YesAndRightToLeft"
    assert not os.path.exists(cartella), "originale nel cestino"

    # La rinomina dalla finestra finisce nella cronologia e si annulla da una finestra nuova
    def rinomina(self):
        seleziona(self, 0)
        self.schema.setEditText("<Series> - <Number>")
        scrivi(self, "Number", "3")
        self.rinomina()
        self.pending.clear()
        self.toccati.clear()
        return 0

    md.MetadataDialog.exec = rinomina
    w.rename_cards([a])
    nuovo = os.path.join(work, "Naruto - 003.cbz")
    assert os.path.exists(nuovo) and not os.path.exists(a) and w.btn_undo_rename.isHidden() is False
    w2 = mw.MainWindow()
    mw.ConfermaRinomina.exec = lambda self: 1
    w2.undo_rename()
    del mw.ConfermaRinomina.exec
    assert os.path.exists(a) and not os.path.exists(nuovo)
    w.close()
    w2.close()
    del md.MetadataDialog.exec


def test_copertina(app, work, md):
    """Copertina a piena risoluzione, zoom, cambio file, e file senza pagine."""
    a = cbz(os.path.join(work, "a.cbz"))
    b = os.path.join(work, "b.cbz")
    Image.new("RGB", (400, 600), "blue").save(b + ".png")
    with zipfile.ZipFile(b, "w") as z:
        z.write(b + ".png", "0001.png")
    os.remove(b + ".png")
    vuoto = os.path.join(work, "vuoto.cbz")
    with zipfile.ZipFile(vuoto, "w") as z:
        z.writestr("nota.txt", "niente pagine")

    d = md.MetadataDialog([a, b, vuoto])
    d.resize(1500, 800)
    d.show()
    vista = d.vista_copertina
    assert attendi(app, lambda: vista.originale is not None)
    assert vista.originale.width() == 40, "subito il primo dei selezionati"

    # scorrendo in fretta conta l'ultimo file scelto
    seleziona(d, 2)
    seleziona(d, 1)
    assert attendi(app, lambda: vista.originale is not None and vista.originale.width() == 400)
    adattata = vista.etichetta.pixmap()
    assert adattata.height() <= vista.viewport().height() and adattata.width() <= vista.viewport().width()

    d.combo_zoom.setCurrentIndex(2)
    assert vista.etichetta.pixmap().width() == 1200 and vista.etichetta.pixmap().height() == 1800
    app.processEvents()
    barra = vista.verticalScrollBar()
    assert barra.maximum() > 0 and barra.value() == 0, "ingrandita si può spostare"
    def mouse(tipo, y, tasti=Qt.MouseButton.LeftButton):
        # sull'immagine, come un clic vero: l'evento risale dall'etichetta alla vista
        punto = QPointF(50, y)
        app.sendEvent(vista.etichetta, QMouseEvent(
            tipo, punto, vista.etichetta.mapToGlobal(punto), Qt.MouseButton.LeftButton, tasti,
            Qt.KeyboardModifier.NoModifier))

    mouse(QEvent.Type.MouseButtonPress, 300)
    mouse(QEvent.Type.MouseMove, 200)
    mouse(QEvent.Type.MouseButtonRelease, 200, Qt.MouseButton.NoButton)
    assert barra.value() == 100, "trascinando verso l'alto si scende nell'immagine"

    # troppo grande: lo zoom scende invece di esaurire la memoria
    md.LIMITE_PIXEL_ZOOM, limite = 500_000, md.LIMITE_PIXEL_ZOOM
    vista.zoom(3)
    md.LIMITE_PIXEL_ZOOM = limite
    assert vista.etichetta.pixmap().width() == 400

    seleziona(d, 2)
    assert attendi(app, lambda: vista.etichetta.text() == "Nessuna copertina")
    assert vista.originale is None
    d.pending.clear()
    d.reject()


def main():
    work = tempfile.mkdtemp(prefix="comicopt_metadata_")
    app = QApplication([])
    try:
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, os.path.join(work, "cfg"))
        from comicoptimizer import history, metadata_dialog as md
        history.HISTORY_PATH = os.path.join(work, "rinomine.jsonl")   # non il registro vero
        for prova in (test_finestra, test_altri_formati, test_cartella, test_ricerca, test_copertina, test_catena_e_cronologia):
            cartella = os.path.join(work, prova.__name__)
            os.makedirs(cartella)
            prova(app, cartella, md)
            print("ok:", prova.__name__)
        print("TUTTO OK")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
