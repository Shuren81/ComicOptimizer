"""Test della scheda Libreria (headless, su una libreria finta in una cartella temporanea). Uso:

    venv/bin/python tests/test_library.py
"""
import os
import shutil
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def attendi(app, condizione, secondi=20):
    fine = time.time() + secondi
    while time.time() < fine:
        app.processEvents()
        if condizione():
            return True
        time.sleep(0.01)
    return False


def cbz(path, colors):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for i, c in enumerate(colors):
            tmp = path + f".{i}.png"
            Image.new("RGB", (60, 90), c).save(tmp)
            z.write(tmp, f"{i + 1:03d}.png")
            os.remove(tmp)
    return path


def test_vista(app, lib):
    from comicoptimizer import library
    from comicoptimizer.main_window import MainWindow
    a = cbz(os.path.join(lib, "Batman", "Batman 01.cbz"), [(250, 0, 0)])
    b = cbz(os.path.join(lib, "Batman", "Batman 02.cbz"), [(0, 250, 0)])
    c = cbz(os.path.join(lib, "Robin", "Robin 01.cbz"), [(0, 0, 250)])
    open(os.path.join(lib, "Batman", "note.txt"), "w").write("non è un fumetto")

    win = MainWindow()
    v = win.library
    assert win.views.currentWidget() is v and v.root == "", "si parte dalla Libreria (vuota)"
    v.set_root(lib)
    assert v.paths == [], "nella cartella principale non ci sono fumetti sciolti"
    v.chk_sub.setChecked(True)
    assert v.paths == [a, b, c], v.paths
    v.chk_sub.setChecked(False)
    v.show_folder(os.path.join(lib, "Batman"))
    assert v.paths == [a, b] and v.list.count() == 2
    v.go_root()
    assert v.folder == lib and v.paths == [], "⌂ torna alla cartella principale"
    v.show_folder(os.path.join(lib, "Batman"))

    # la Libreria allarga la finestra di una colonna in più della lista più grande (se lo schermo basta)
    from comicoptimizer import config
    if win._cols_fit(10 ** 5, config.COLS_MAX + 1) == win._cols_fit_screen() + 1:
        assert win._view_cols() == config.COLS_MAX + 1

    # la finestra finisce poco dopo l'ultima colonna di copertine
    win.show()
    win.show_view(v)
    assert attendi(app, lambda: v.list.viewport().width() % v.list.gridSize().width() <= 8)
    assert attendi(app, lambda: (v.list.viewport().height() - 8) % v.list.gridSize().height() == 0), \
        "in altezza righe intere di copertine"
    assert win.title_lbl.pixmap().width() < win.width(), "il banner sta nella finestra stretta"
    win.hide()

    # file trascinati da fuori sull'albero: nella lista di lavoro, non spostati nella libreria
    from PyQt6.QtCore import QMimeData, QPointF, QUrl, Qt as _Qt
    from PyQt6.QtGui import QDropEvent
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(c)])
    ev = QDropEvent(QPointF(5, 5), _Qt.DropAction.MoveAction, md, _Qt.MouseButton.LeftButton,
                    _Qt.KeyboardModifier.NoModifier)
    importati = []
    vero_import, win.import_paths = win.import_paths, importati.append
    v.eventFilter(v.tree.viewport(), ev)
    win.import_paths = vero_import
    assert importati == [[c]] and os.path.exists(c), importati

    # menu col tasto destro: Unisci solo con 2 o più fumetti
    voci = lambda: [x.text() for x in v.list_menu().actions() if x.text()]
    v.list.item(0).setSelected(True)
    assert "Pagine" in voci() and "Unisci" not in voci(), voci()
    v.list.item(1).setSelected(True)
    assert "Unisci" in voci() and "Pagine" not in voci(), voci()
    v.list.clearSelection()

    # file trascinati: compare la lista di lavoro; svuotata, si torna alla Libreria
    win.import_paths([c])
    assert win.views.currentWidget() is win.work_tab
    assert attendi(app, lambda: c in win.cards)
    assert win.views.currentWidget() is win.work_tab and "Torna alla lista di lavoro" in voci()
    # tasto destro su una card non selezionata: la seleziona e mostra il menu
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QMenu
    menu_aperti = []
    vero_exec, QMenu.exec = QMenu.exec, lambda self, *a: menu_aperti.append([x.text() for x in self.actions()])
    try:
        win.refresh_grid()
        app.sendEvent(win.cards[c], QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5)))
    finally:
        QMenu.exec = vero_exec
    assert win.cards[c].selected and menu_aperti and "Sposta in libreria" in menu_aperti[0], menu_aperti
    assert win.btn_move.isVisibleTo(win)
    win.show_view(v)
    assert win.views.currentWidget() is v and c in win.cards, "← LIBRERIA non svuota la lista"
    win.clear_all()
    assert win.views.currentWidget() is v

    # miniature: create in background e salvate in cache
    assert attendi(app, lambda: all(os.path.exists(library.thumb_path(p)) for p in (a, b)))
    assert attendi(app, lambda: not v._running)
    v.show_folder(os.path.join(lib, "Batman"))
    assert not v._queue, "alla seconda apertura le miniature vengono dalla cache"

    # refresh senza cambiamenti non ricostruisce la griglia (selezione e scorrimento restano)
    v.list.item(1).setSelected(True)
    v.refresh()
    assert v.selected() == [b]
    os.remove(b)
    v.refresh()
    assert v.paths == [a] and v.selected() == []

    # i dati che trascinando arrivano all'albero sono i percorsi dei fumetti
    v.list.item(0).setSelected(True)
    urls = v.list.mimeData(v.list.selectedItems()).urls()
    assert [u.toLocalFile() for u in urls] == [a]
    v.stop()
    win.close()


def test_controllo(app, lib):
    from comicoptimizer import library, workers
    a = cbz(os.path.join(lib, "Batman", "Batman 01.cbz"), [(250, 0, 0), (0, 250, 0)])
    b = os.path.join(lib, "Copie", "Batman 01 (1).cbz")
    os.makedirs(os.path.dirname(b))
    shutil.copy(a, b)                                 # stesso contenuto in un'altra cartella
    c = os.path.join(lib, "Rotto.cbz")
    open(c, "wb").write(b"PK\x03\x04 non uno zip vero")
    d = cbz(os.path.join(lib, "Robin 01.cbz"), [(0, 0, 250)])

    letture = []
    vero = workers.check_integrity
    workers.check_integrity = lambda p: (letture.append(p), vero(p))[1]
    try:
        def controlla():
            out = []
            w = library.LibraryScanWorker(lib)
            w.finished.connect(lambda res, fresh: out.append((res, fresh)))
            w.run()
            return out[0]

        res, fresh = controlla()
        assert res == {a: 1, b: 4, c: 5, d: 1}, res
        assert sorted(fresh) == sorted([a, b, c, d]) and len(letture) == 4

        # seconda volta: niente da rileggere, anche dopo aver chiuso il programma (indice su disco)
        workers._ANALYSIS_CACHE.clear()
        workers.load_index()
        letture.clear()
        res, fresh = controlla()
        assert res == {a: 1, b: 4, c: 5, d: 1} and fresh == [] and letture == [], (res, fresh, letture)

        # un fumetto spostato (o rinominato) fuori dall'app non viene riletto
        e = os.path.join(lib, "Robin", "Robin 01 - Nuovo nome.cbz")
        os.makedirs(os.path.dirname(e))
        os.rename(d, e)
        res, fresh = controlla()
        assert res[e] == 1 and d not in res and fresh == [] and letture == [], (res, fresh, letture)

        # cambiato: si rilegge solo lui
        cbz(e, [(1, 2, 3)])
        res, fresh = controlla()
        assert fresh == [e] and letture == [e], (fresh, letture)
    finally:
        workers.check_integrity = vero

    # filtro della scheda: i doppioni di tutta la libreria, letti dal controllo
    from comicoptimizer.main_window import MainWindow
    win = MainWindow()
    v = win.library
    v.set_root(lib)
    v.results = res
    v.filtro.setCurrentIndex(2)
    assert v.paths == [b], v.paths
    v.filtro.setCurrentIndex(3)
    assert v.paths == [c] and "danneggiato" in v.list.item(0).toolTip()
    v.stop()
    win.close()


def test_sposta(app, work):
    from PyQt6.QtWidgets import QDialog, QMessageBox
    from comicoptimizer import history, library, metadata_dialog
    from comicoptimizer.main_window import MainWindow
    assert library.cartella_da_schema("<Publisher>/<Series>", {"Publisher": "DC Comics", "Series": "batman"}) \
        == os.path.join("DC Comics", "Batman")
    assert library.cartella_da_schema("<Publisher>/<Series> (<Year>)", {"Series": "Robin"}) == "Robin"
    assert library.cartella_da_schema("<Publisher>/<Series>", {}) == ""

    lib, lavoro = os.path.join(work, "lib"), os.path.join(work, "da sistemare")
    os.makedirs(lib)
    ci = "<ComicInfo><Series>Batman</Series><Publisher>DC Comics</Publisher></ComicInfo>"

    def con_info(path, xml=ci):
        cbz(path, [(250, 0, 0)])
        with zipfile.ZipFile(path, "a") as z:
            z.writestr("ComicInfo.xml", xml)
        return path
    a = con_info(os.path.join(lavoro, "Batman 01.cbz"))
    gia = con_info(os.path.join(lib, "DC Comics", "Batman", "Batman 01.cbz"))   # stesso nome già in libreria
    senza = cbz(os.path.join(lavoro, "Senza info.cbz"), [(0, 0, 250)])
    dentro = con_info(os.path.join(lib, "Batman 02.cbz"))                    # già in libreria: resta

    avvisi = []
    QMessageBox.information = staticmethod(lambda *a, **k: avvisi.append(a[2]))
    win = MainWindow()
    v = win.library
    v.set_root(lib)
    v.auto_move([a, senza, dentro])
    assert os.path.exists(a), "spostamento automatico spento: niente si muove"

    win.on_file_done(a, a, 2)                          # come a fine lavoro
    assert win._job_outputs == [a]
    # opzioni: più librerie (nome e cartella), schema di ognuna; i tasti valgono per lo schema cliccato
    from comicoptimizer import library
    from comicoptimizer.library import OpzioniLibreria, impostazione
    manga = os.path.join(work, "manga")
    os.makedirs(manga)
    o = OpzioniLibreria(v)
    _r, nome, dove, schema = o.righe[0]
    assert not o.righe[1][0].isVisibleTo(o), "di serie una libreria sola"
    nome.setText("Comics")
    dove.setText(lib)
    schema.setText("<Publisher>/<Series>")
    o._attiva(schema)
    o.inverti("Publisher", schema)
    assert schema.text() == "<Series>", schema.text()
    schema.insert("/")
    o.inverti("Year", schema)
    o.inverti("Publisher", schema)
    assert schema.text() == "<Series>/<Year><Publisher>", schema.text()
    schema.setText("<Publisher>/<Series>")
    o.quante.setValue(2)
    assert o.righe[1][0].isVisibleTo(o)
    o.righe[1][1].setText("Manga")
    o.righe[1][2].setText(manga)
    o.righe[1][3].setText("<Writer>")
    o.auto.setChecked(True)
    from comicoptimizer.images import webp_quality
    assert o.qualita.currentData() == 85, "di serie il livello Medio, quello di prima"
    o.qualita.setCurrentIndex(0)
    o.accept()
    assert impostazione("auto") and library.librerie() == [lib, manga]
    assert library.info_libreria(manga)["nome"] == "Manga" and os.path.exists(os.path.join(manga, library.INFO_FILE))
    assert v.schema() == "<Publisher>/<Series>"
    assert webp_quality() == 75 and OpzioniLibreria(v).qualita.currentIndex() == 0
    v._riempi_scelta()
    assert [v.scelta.itemText(i) for i in range(v.scelta.count())] == ["Comics", "Manga"]
    v.scelta.setCurrentIndex(1)
    assert v.root == manga and v.schema() == "<Writer>"
    v.scelta.setCurrentIndex(0)
    assert v.root == lib

    # primo controllo: avvisa che è lungo (solo per le librerie che l'indice non conosce ancora e che
    # hanno dei fumetti); "No" non lo avvia. Già controllate: parte senza chiedere, e lo Stop è subito
    from comicoptimizer import workers
    v.report = lambda: None                            # niente finestra di riepilogo nel test
    workers._ANALYSIS_CACHE.clear()
    m = cbz(os.path.join(manga, "M.cbz"), [(1, 1, 1)])
    domande = []
    vera_domanda = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: (domande.append(a[2]), QMessageBox.StandardButton.No)[1])
    v.scan()
    assert len(domande) == 1 and "molte ore" in domande[0] and "Manga" in domande[0] and "Comics" in domande[0]
    assert v.scanner is None
    workers._ANALYSIS_CACHE[os.path.join(lib, "x.cbz")] = ((0, 0), True, "", 1)   # Comics già controllata
    v.scan()
    assert len(domande) == 2 and "Manga" in domande[1] and "Comics" not in domande[1], domande
    os.remove(m)                                       # libreria vuota: niente da avvisare
    v.scan()
    QMessageBox.question = vera_domanda
    assert len(domande) == 2 and v.scanner is not None
    v.scanner.wait()
    attendi(app, lambda: v.scanner is None)
    cbz(m, [(1, 1, 1)])
    lento, vero_controllo = workers._integrity_and_signature, workers._integrity_and_signature
    workers._ANALYSIS_CACHE.clear()                    # tutti da rileggere, ma librerie già conosciute:
    for finto in (os.path.join(lib, "x.cbz"), os.path.join(manga, "x.cbz")):   # niente avviso
        workers._ANALYSIS_CACHE[finto] = ((0, 0), True, "", 1)
    workers._integrity_and_signature = lambda p: (time.sleep(3), lento(p))[1]   # fumetti enormi
    v.scan()
    assert v.scanner is not None
    attendi(app, lambda: False, 0.3)
    inizio = time.time()
    v._stop_scan()
    assert attendi(app, lambda: v.scanner is None, 5) and time.time() - inizio < 1.5, \
        "Ferma controllo si ferma subito, senza aspettare i file in lettura"
    workers._integrity_and_signature = vero_controllo
    time.sleep(3)                                      # i controlli rimasti finiscono in background
    o = OpzioniLibreria(v)
    o.miniature.setCurrentIndex(2)
    o.inverti("Number", o.rinomina)
    o.rinomina.insert(" - ")
    o.inverti("Title", o.rinomina)
    o.accept()
    v.set_thumb_size()
    assert v.list.iconSize().width() == 180 and v.list.gridSize().width() == 204
    md = metadata_dialog.MetadataDialog([dentro], win)
    assert md.schema.currentText() == "<Number> - <Title>", md.schema.currentText()
    md.reject()
    v.auto_move([a, senza, dentro])
    nuovo = os.path.join(lib, "DC Comics", "Batman", "Batman 01_1.cbz")
    assert os.path.exists(nuovo) and not os.path.exists(a) and os.path.exists(gia), "mai sovrascrivere"
    assert os.path.exists(senza) and os.path.exists(dentro) and avvisi and "Senza info.cbz" in avvisi[-1]

    # si annulla dalla cronologia come una rinomina
    metadata_dialog.ConfermaRinomina.exec = lambda self: QDialog.DialogCode.Accepted
    win.undo_batch(history.batches()[0])
    assert os.path.exists(a) and not os.path.exists(nuovo)

    # SPOSTA IN LIBRERIA dalla lista di lavoro: un fumetto già sistemato trascinato nella finestra
    win.import_files([(a, 1)])
    win.cards[a].selected = True
    win._update_sel_buttons()
    win.btn_move.click()
    spostato = os.path.join(lib, "DC Comics", "Batman", "Batman 01_1.cbz")
    assert os.path.exists(spostato) and spostato in win.cards and a not in win.cards
    win.clear_all()

    # Riordina dalle info, dentro la libreria
    v.show_folder(lib)
    v.list.item(0).setSelected(True)
    assert v.selected() == [dentro]
    v.reorder()
    assert os.path.exists(os.path.join(lib, "DC Comics", "Batman", "Batman 02.cbz")) and not os.path.exists(dentro)
    v.stop()
    win.close()


def main():
    work = tempfile.mkdtemp(prefix="comicopt_library_")
    try:
        os.environ["XDG_CACHE_HOME"] = os.path.join(work, "cache")   # miniature non nella cache vera
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        app.setApplicationName("ComicOptimizer")
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, os.path.join(work, "cfg"))
        from comicoptimizer import history
        history.HISTORY_PATH = os.path.join(work, "rinomine.jsonl")
        for prova in (test_vista, test_controllo, test_sposta):
            cartella = os.path.join(work, prova.__name__)
            os.makedirs(cartella)
            prova(app, cartella)
            print("ok:", prova.__name__)
        print("TUTTO OK")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
