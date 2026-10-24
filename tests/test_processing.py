"""Test dell'elaborazione dei fumetti (headless): riparazione, WebP, cartelle, unione,
originali al sicuro, analisi, un lavoro alla volta. Uso, dalla cartella del progetto:

    venv/bin/python tests/test_processing.py
"""
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(work):
    from PIL import Image
    import pymupdf
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from comicoptimizer import utils, workers
    from comicoptimizer.cbz import file_status

    trash = os.path.join(work, "_cestino")
    os.makedirs(trash)
    trash_ok = [True]

    def fake_trash(p):
        if not trash_ok[0]:
            return False
        shutil.move(p, os.path.join(trash, os.path.basename(p)))
        return True
    workers._trash_file_cross_platform = fake_trash

    def png(path, color):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.new("RGB", (60, 90), color).save(path)

    def cbz(path, colors, ci=None):
        with zipfile.ZipFile(path, "w") as z:
            for i, c in enumerate(colors):
                p = os.path.join(work, "_tmp.png")
                png(p, c)
                z.write(p, f"pag {i + 1}.png")
            z.writestr("__MACOSX/._x.png", b"junk")
            if ci:
                z.writestr("ComicInfo.xml", ci)
        return path

    def run(paths, webp=False, loose=(), merged=None):
        out = []
        bw = workers.BatchPrepWorker(paths, webp, loose)
        bw.ready.connect(lambda t, m: out.extend(t))
        bw.run()
        if merged:
            out = [merged(out)]
        pw = workers.ProcessingWorker(out, to_webp=webp)
        summ = []
        pw.job_done.connect(summ.append)
        pw.run()
        return summ[0]

    def first_pixel(z, name):
        with z.open(name) as f:
            return Image.open(f).convert("RGB").getpixel((5, 5))

    R, G, B = (250, 0, 0), (0, 250, 0), (0, 0, 250)
    CI = ('<ComicInfo><Title>Cap 2</Title><Number>2</Number><PageCount>9</PageCount>'
          '<Pages><Page Image="0"/></Pages></ComicInfo>')

    # --- riparazione: pagine 0001…, ComicInfo aggiornato, spazzatura fuori, originale nel cestino
    d = os.path.join(work, "ripara")
    os.makedirs(d)
    src = cbz(os.path.join(d, "Fumetto 1.zip"), [R, G, B], CI)
    s = run([src])
    out = os.path.join(d, "Fumetto 1.cbz")
    assert s["done"] == 1 and not os.path.exists(src) and os.path.exists(os.path.join(trash, "Fumetto 1.zip"))
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == ["0001.png", "0002.png", "0003.png", "ComicInfo.xml"], z.namelist()
        ci = z.read("ComicInfo.xml").decode()
        assert "<PageCount>3</PageCount>" in ci and "<Pages" not in ci
    assert file_status(out) == 1

    # --- conversione WebP (su più processi): pagine .webp, stato CONVERTITO
    d = os.path.join(work, "webp")
    os.makedirs(d)
    src = cbz(os.path.join(d, "W.cbr"), [R, G])
    s = run([src], webp=True)
    out = os.path.join(d, "W.cbz")
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == ["0001.webp", "0002.webp"], z.namelist()
    assert s["done"] == 1 and file_status(out) == 3

    # --- cartella di immagini: ordine in profondità, ComicInfo solo della principale
    f = os.path.join(work, "Saga Vol. 2")
    png(os.path.join(f, "2.jpg"), R)
    png(os.path.join(f, "10.jpg"), R)
    png(os.path.join(f, "Cap 2", "a.png"), G)
    png(os.path.join(f, "Cap 10", "a.png"), B)
    open(os.path.join(f, "Thumbs.db"), "wb").write(b"x")
    open(os.path.join(f, "ComicInfo.xml"), "w").write("<ComicInfo><Title>S</Title><PageCount>1</PageCount></ComicInfo>")
    open(os.path.join(f, "Cap 2", "ComicInfo.xml"), "w").write("<ComicInfo><Title>SUB</Title></ComicInfo>")
    assert file_status(f) == 0
    s = run([f])
    out = f + ".cbz"                                   # "Vol. 2" non perde il ". 2"
    with zipfile.ZipFile(out) as z:
        pages = [n for n in z.namelist() if n != "ComicInfo.xml"]
        assert len(pages) == 4
        assert [first_pixel(z, n)[1] > 200 for n in pages] == [False, False, True, False]   # 2, 10, Cap 2, Cap 10
        assert "<Title>S</Title>" in z.read("ComicInfo.xml").decode()
    assert not os.path.exists(f) and os.path.isdir(os.path.join(trash, "Saga Vol. 2"))

    # --- unione: CBZ (con ComicInfo) + ZIP + PDF, in quest'ordine
    m = os.path.join(work, "unione")
    os.makedirs(m)
    a = cbz(os.path.join(m, "Naruto 2.cbz"), [R, R], CI)
    doc = pymupdf.open()
    doc.new_page()
    doc.save(os.path.join(m, "Naruto 3.pdf"))
    c = cbz(os.path.join(m, "Naruto 10.zip"), [B])
    sel = [a, os.path.join(m, "Naruto 3.pdf"), c]
    final = os.path.join(m, "Naruto.cbz")

    def merged(tasks):
        assert len(tasks) == 3
        return {"src": sel[0], "extra_srcs": sel[1:], "dest": final,
                "images": [i for t in tasks for i in t["images"]],
                "tmp": tasks[0]["tmp"], "extra_tmps": [t["tmp"] for t in tasks[1:]],
                "comicinfo": tasks[0]["comicinfo"], "edited": True, "title": "Naruto"}
    s = run(sel, merged=merged)
    with zipfile.ZipFile(final) as z:
        pages = [n for n in z.namelist() if n != "ComicInfo.xml"]
        assert [n.split(".")[0] for n in pages] == ["0001", "0002", "0003", "0004"]
        assert first_pixel(z, pages[0])[0] > 200 and first_pixel(z, pages[-1])[2] > 200
        ci = z.read("ComicInfo.xml").decode()
        assert "<Title>Naruto</Title>" in ci and "<Number>" not in ci and "<PageCount>4</PageCount>" in ci
    assert sorted(os.listdir(m)) == ["Naruto.cbz"]

    # --- cestino non disponibile: l'originale resta (mai cancellazioni definitive)
    trash_ok[0] = False
    d = os.path.join(work, "senza_cestino")
    os.makedirs(d)
    src = cbz(os.path.join(d, "P.zip"), [R])
    run([src])
    assert os.path.exists(src) and os.path.exists(os.path.join(d, "P.cbz"))
    # riparazione "sul posto" di un .cbz: il vecchio file resta come .bak
    inplace = cbz(os.path.join(d, "Q.cbz"), [G])
    old = open(inplace, "rb").read()
    run([inplace])
    assert os.path.exists(inplace) and open(inplace + ".bak", "rb").read() == old
    run([inplace])                                     # di nuovo: non sovrascrive il .bak
    assert os.path.exists(inplace + ".bak.1")
    trash_ok[0] = True

    # --- analisi: ricontrolla solo i file cambiati; cartella e CBZ omonimi non sono doppioni
    calls = []
    real_check = workers.check_integrity
    workers.check_integrity = lambda p: (calls.append(p), real_check(p))[1]
    an = os.path.join(work, "analisi")
    os.makedirs(an)
    x = cbz(os.path.join(an, "X.cbz"), [R])
    folder_x = os.path.join(an, "X")
    png(os.path.join(folder_x, "1.jpg"), G)
    y = cbz(os.path.join(an, "Y.cbz"), [B])

    def analyse():
        res = []
        aw = workers.AnalysisWorker([x, folder_x, y])
        aw.finished.connect(lambda r, dup: res.append((r, dup)))
        aw.run()
        return res[0]
    res, dupes = analyse()
    assert dupes == 0 and res[folder_x] == 0 and res[x] == 1, res
    n_first = len(calls)
    analyse()
    assert len(calls) == n_first + 1                   # solo la cartella (non costa nulla)
    with zipfile.ZipFile(y, "a") as z:                 # Y cambia: viene ricontrollato
        z.writestr("nuova.png", b"x")
    analyse()
    assert calls[-2:] == [folder_x, y] or y in calls[n_first + 1:]
    workers.check_integrity = real_check

    # --- editor: LoadingWorker estrae ZIP e PDF; archivio rotto → errore
    for path in (x, os.path.join(trash, "Naruto 3.pdf")):
        got = []
        lw = workers.LoadingWorker(path)
        lw.finished.connect(lambda p, t, pages: got.append((t, pages)))
        lw.run()
        assert got and got[0][1], path
        shutil.rmtree(got[0][0])
    broken = os.path.join(an, "rotto.cbz")
    open(broken, "wb").write(b"PK\x03\x04rotto")
    errs = []
    lw = workers.LoadingWorker(broken)
    lw.error.connect(errs.append)
    lw.run()
    assert errs

    # --- Mac: il percorso va come argomento di osascript, mai dentro lo script
    import types
    seen = []
    real_run, real_platform = utils.subprocess.run, sys.platform
    sys.modules["send2trash"] = types.SimpleNamespace(
        send2trash=lambda p: (_ for _ in ()).throw(OSError("no")))
    utils.subprocess.run = lambda args, **kw: (seen.append(args), types.SimpleNamespace(returncode=0))[1]
    sys.platform = "darwin"
    try:
        evil = '/tmp/x" & (do shell script "touch /tmp/pwned") & ".cbz'
        assert utils._trash_file_cross_platform(evil)
    finally:
        sys.platform = real_platform
        utils.subprocess.run = real_run
        del sys.modules["send2trash"]
    assert seen[0][-1] == evil and not any(evil in a for a in seen[0][:-1])

    # --- audit: errori che prima bloccavano l'app o rovinavano un fumetto
    au = os.path.join(work, "audit")
    os.makedirs(au)
    # fumetto senza pagine (editor con tutte le pagine tolte): errore, originale intatto
    keep = cbz(os.path.join(au, "Intatto.cbz"), [R])
    before = open(keep, "rb").read()
    summ = []
    pw = workers.ProcessingWorker([{"src": keep, "images": [], "tmp": None, "comicinfo": None,
                                    "edited": True}])
    pw.job_done.connect(summ.append)
    pw.run()
    assert summ[0]["done"] == 0 and summ[0]["errors"] and open(keep, "rb").read() == before
    # file senza permesso di lettura: l'importazione lo salta e finisce
    locked = cbz(os.path.join(au, "Bloccato.cbz"), [R])
    os.chmod(locked, 0)
    got = []
    iw = workers.ImportWorker([au])
    iw.finished.connect(lambda ok, skipped: got.append((ok, skipped)))
    iw.run()
    os.chmod(locked, 0o644)
    assert got and [p for p, _ in got[0][0]] == [keep] and [p for p, _ in got[0][1]] == [locked], got
    # errore imprevisto nella preparazione: quel fumetto è saltato, "ready" arriva comunque
    real_tmp = workers.make_temp_dir
    workers.make_temp_dir = lambda: (_ for _ in ()).throw(OSError("disco pieno"))
    ready = []
    bw = workers.BatchPrepWorker([keep], False)
    bw.ready.connect(lambda t, m: ready.append(t))
    bw.run()
    workers.make_temp_dir = real_tmp
    assert ready == [[]]
    # editor su una cartella con ComicInfo.xml illeggibile: messaggio di errore, non blocco
    fold = os.path.join(au, "Cartella")
    png(os.path.join(fold, "1.jpg"), R)
    ci_path = os.path.join(fold, "ComicInfo.xml")
    open(ci_path, "w").write("<ComicInfo/>")
    os.chmod(ci_path, 0)
    errs = []
    lw = workers.LoadingWorker(fold)
    lw.error.connect(errs.append)
    lw.run()
    os.chmod(ci_path, 0o644)
    assert errs and "apertura" in errs[0]
    # Windows, disco di rete: niente "cestino" (cancellerebbe per sempre), il file resta
    assert utils._is_network_path(keep) is False                 # non Windows
    real_net = utils._is_network_path
    utils._is_network_path = lambda p: True
    assert utils._trash_file_cross_platform(keep) is False and os.path.exists(keep)
    utils._is_network_path = real_net

    # --- editor: due immagini aggiunte con lo stesso nome restano due pagine diverse
    import comicoptimizer.editor as ed
    etmp = os.path.join(au, "editor_tmp")
    png(os.path.join(etmp, "0001.png"), R)
    png(os.path.join(au, "a", "01.png"), G)
    png(os.path.join(au, "b", "01.png"), B)
    ed.QFileDialog.getOpenFileNames = lambda *a: ([os.path.join(au, "a", "01.png"),
                                                    os.path.join(au, "b", "01.png")], "")
    dlg = ed.AdvancedEditor(keep, etmp, [os.path.join(etmp, "0001.png")])
    dlg.add_ext()
    paths = dlg.get_paths()
    assert len(paths) == 3 and len(set(paths)) == 3, paths
    colors = [Image.open(p).convert("RGB").getpixel((5, 5)) for p in paths[1:]]
    assert colors[0][1] > 200 and colors[1][2] > 200, colors
    dlg.reject()

    window_checks(app, work)
    print("TUTTO OK")


def window_checks(app, work):
    import comicoptimizer.main_window as mw
    from comicoptimizer.workers import BatchPrepWorker
    from PyQt6.QtTest import QTest

    infos = []
    mw.QMessageBox.information = lambda *a: infos.append(a[-1])
    w = mw.MainWindow()
    w.show()

    # un lavoro alla volta: con un lavoro in corso, Fix/Edita/Unisci/Rinomina/Cestina aspettano
    started = []
    real_start = BatchPrepWorker.start
    BatchPrepWorker.start = lambda self: started.append(self)
    w.ask_mode = lambda: "repair"
    w.current_worker = object()
    for call in (lambda: w.individual_repair("x"), w.repair_trigger, w.repair_selected, w.repair_all_trigger,
                 w.merge_selected, lambda: w.open_editor("x"), lambda: w.rename_cards(["x"]),
                 w.trash_selected, w.trash_all_duplicates, lambda: w.confirm_and_trash("x")):
        call()
    assert started == [] and len(infos) == 10
    w.current_worker = None
    fake_prep = BatchPrepWorker([], False)
    w._add_thread(fake_prep)                          # estrazione in corso (prima dell'elaborazione)
    assert w._busy()
    w._discard_thread(fake_prep)
    assert not w._busy()
    BatchPrepWorker.start = real_start

    # cartella con più sottocartelle: si chiede se è davvero un solo fumetto
    from PIL import Image
    lib = os.path.join(work, "Libreria")
    for sub in ("Saga", "Naruto"):
        os.makedirs(os.path.join(lib, sub))
        Image.new("RGB", (10, 10)).save(os.path.join(lib, sub, "1.jpg"))
    answer = ["No"]
    mw.QMessageBox.exec = lambda self: 0
    mw.QMessageBox.clickedButton = lambda self: next(
        b for b in self.buttons() if b.text().startswith(answer[0]))
    w.import_files([(lib, 2)])
    assert lib not in w.cards
    answer[0] = "Sì"
    w.import_files([(lib, 2)])
    assert lib in w.cards and w.cards[lib].status_code == 0
    w.clear_all()

    # miniature: poche alla volta, e nessun thread dimenticato (anche se falliscono)
    fakes = []
    for i in range(30):
        p = os.path.join(work, f"finto {i}.cbz")
        open(p, "wb").write(b"non un archivio")
        fakes.append((p, 1))
    w.import_files(fakes)
    assert w._thumbs_running <= w.THUMBS_AT_ONCE
    for _ in range(200):
        QTest.qWait(50)
        if not w._thumbs_running and not w._thumb_queue:
            break
    assert w._thumbs_running == 0 and not w._thumb_queue
    assert not any(isinstance(t, mw.ThumbWorker) for t in w.active_threads)

    # SISTEMA: con una selezione chiede "Selezionati" o "Tutti"; senza selezione, tutti
    calls = []
    w.repair_selected = lambda: calls.append("sel")
    w.repair_all_trigger = lambda: calls.append("all")
    w.repair_trigger()
    list(w.cards.values())[0].selected = True
    answer[0] = "Selezionati"
    w.repair_trigger()
    answer[0] = "Tutti"
    w.repair_trigger()
    answer[0] = "Annulla"
    w.repair_trigger()
    assert calls == ["all", "sel", "all"], calls
    assert w.btn_all.text() == "SISTEMA" and w.btn_rename.text() == "RINOMINA"

    # cestino non disponibile per più file: un solo messaggio, i file restano
    warns = []
    mw.QMessageBox.warning = lambda *a: warns.append(a[-1])
    mw._trash_file_cross_platform = lambda p: False
    w.trash_files(list(w.cards)[:3])
    assert len(warns) == 1 and "3 file non spostati" in warns[0] and len(w.cards) == 30
    w._closing = True


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as work:
        main(work)
