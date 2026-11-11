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
    assert win.tabs.count() == 2 and v.root == "", "senza libreria scelta la scheda è vuota"
    v.set_root(lib)
    assert v.paths == [], "nella cartella principale non ci sono fumetti sciolti"
    v.chk_sub.setChecked(True)
    assert v.paths == [a, b, c], v.paths
    v.chk_sub.setChecked(False)
    v.show_folder(os.path.join(lib, "Batman"))
    assert v.paths == [a, b] and v.list.count() == 2

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
        for prova in (test_vista, test_controllo):
            cartella = os.path.join(work, prova.__name__)
            os.makedirs(cartella)
            prova(app, cartella)
            print("ok:", prova.__name__)
        print("TUTTO OK")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
