"""Test dello Stop (importazione, analisi, estrazione) e del log nei processi di lavoro. Uso:

    venv/bin/python tests/test_stop.py
"""
import glob
import multiprocessing
import os
import sys
import tempfile
import threading
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def slow_tool(work):
    """Finto 7z che ci mette 30 secondi: lo Stop deve fermarlo subito."""
    path = os.path.join(work, "lento")
    with open(path, "w") as f:
        f.write("#!/bin/sh\nsleep 30\n")
    os.chmod(path, 0o755)
    return path


def wait(thread, seconds=10):
    end = time.time() + seconds
    while thread.isRunning() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    QApplication.processEvents()


def test_kill_tools(work):
    from comicoptimizer import utils
    utils.find_tool = lambda name: slow_tool(work)
    done = []
    t = threading.Thread(target=lambda: done.append(utils.run_tool(["7z", "x", "a.cb7"]).returncode))
    t0 = time.time()
    t.start()
    time.sleep(0.3)
    utils.kill_tools(t.ident)
    t.join(5)
    assert done and done[0] != 0 and time.time() - t0 < 5        # fermato, non dopo 30 secondi


def test_prep_stop(work):
    """Stop durante l'estrazione: si ferma subito, niente temporanei, nessun lavoro dopo."""
    from comicoptimizer import utils, workers
    from comicoptimizer.config import TMP_PREFIX
    utils.find_tool = lambda name: slow_tool(work)
    paths = []
    for i in range(3):
        p = os.path.join(work, f"Fumetto {i}.cbr")
        open(p, "wb").write(b"Rar!\x1a\x07\x00 non vero")          # "RAR": si estrae con il finto 7z
        paths.append(p)
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")))
    bw = workers.BatchPrepWorker(paths, False)
    ready, cancelled = [], []
    bw.ready.connect(lambda t, m: ready.append(t))
    bw.cancelled.connect(lambda: cancelled.append(1))
    t0 = time.time()
    bw.start()
    time.sleep(0.5)
    bw.abort()
    wait(bw)
    assert cancelled == [1] and ready == [] and time.time() - t0 < 6, (cancelled, ready)
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")))
    assert after == before, after - before                         # temporanei cancellati
    assert all(os.path.exists(p) for p in paths)                   # originali intatti


def test_lazy_processing(work):
    """Sistema/Converti: ogni fumetto si estrae subito prima di convertirlo; i temporanei non si
    accumulano; il CBZ creato non viene ricontrollato da capo dall'analisi."""
    import shutil
    from comicoptimizer import utils, workers
    from comicoptimizer.config import TMP_PREFIX
    from PIL import Image
    trash = os.path.join(work, "_cestino_lazy")
    os.makedirs(trash)
    workers._trash_file_cross_platform = lambda p: (shutil.move(p, trash), True)[1]
    paths = []
    for i in range(5):
        p = os.path.join(work, f"Lazy {i}.zip")
        with zipfile.ZipFile(p, "w") as z:
            for k in range(3):
                img = os.path.join(work, "_p.png")
                Image.new("RGB", (20, 30), (k * 80, i * 40, 0)).save(img)
                z.write(img, f"{k + 1}.png")
        paths.append(p)
    tmp_root = tempfile.gettempdir()
    peak = []
    real_prepare = workers.prepare_comic

    def counting(*a, **k):                                         # quante cartelle temporanee insieme
        peak.append(len(glob.glob(os.path.join(tmp_root, TMP_PREFIX + "*"))))
        return real_prepare(*a, **k)
    workers.prepare_comic = counting
    before = len(glob.glob(os.path.join(tmp_root, TMP_PREFIX + "*")))
    tasks = [{"src": p, "lazy": True, "pages": 3} for p in paths]
    done = []
    pw = workers.ProcessingWorker(tasks)
    pw.job_done.connect(done.append)
    pw.run()
    workers.prepare_comic = real_prepare
    assert done[0]["done"] == 5 and not done[0]["errors"], done
    assert max(peak) - before <= workers.ProcessingWorker.PREFETCH + 1, peak   # mai tutti insieme
    assert len(glob.glob(os.path.join(tmp_root, TMP_PREFIX + "*"))) == before
    out = os.path.join(work, "Lazy 0.cbz")
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["0001.png", "0002.png", "0003.png"]
    assert workers._ANALYSIS_CACHE[out][1] is True                 # già verificato: niente secondo controllo
    calls = []
    real_check = workers.check_integrity
    workers.check_integrity = lambda p: (calls.append(p), real_check(p))[1]
    aw = workers.AnalysisWorker([out])
    aw.run()
    workers.check_integrity = real_check
    assert calls == []
    # un file che non si estrae: errore nel riepilogo, gli altri vanno avanti
    bad = os.path.join(work, "Rotto.cbz")
    open(bad, "wb").write(b"PK\x03\x04 rotto")
    ok = os.path.join(work, "Lazy 9.zip")
    shutil.copy(os.path.join(trash, "Lazy 1.zip"), ok)
    done = []
    pw = workers.ProcessingWorker([{"src": bad, "lazy": True}, {"src": ok, "lazy": True}])
    pw.job_done.connect(done.append)
    pw.run()
    assert done[0]["done"] == 1 and done[0]["errors"] == [("Rotto.cbz", "estrazione non riuscita")], done


def test_lazy_stop(work):
    """Stop durante la conversione con estrazioni in anticipo: si ferma subito, niente temporanei."""
    from comicoptimizer import utils, workers
    from comicoptimizer.config import TMP_PREFIX
    utils.find_tool = lambda name: slow_tool(work)
    paths = []
    for i in range(4):
        p = os.path.join(work, f"Lento {i}.cbr")
        open(p, "wb").write(b"Rar!\x1a\x07\x00 non vero")
        paths.append(p)
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")))
    pw = workers.ProcessingWorker([{"src": p, "lazy": True} for p in paths])
    done = []
    pw.job_done.connect(done.append)
    t0 = time.time()
    pw.start()
    time.sleep(0.5)
    pw.abort_now()
    wait(pw)
    assert done and done[0]["aborted"] and done[0]["done"] == 0 and time.time() - t0 < 6, done
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), TMP_PREFIX + "*")))
    assert after == before, after - before
    assert all(os.path.exists(p) for p in paths)


def test_import_and_analysis_stop(work):
    from comicoptimizer import workers
    a = os.path.join(work, "A.cbz")
    with zipfile.ZipFile(a, "w") as z:
        z.writestr("1.png", b"x")
    # Stop prima ancora di cominciare: annullato, nessun risultato
    iw = workers.ImportWorker([a])
    got, cancelled = [], []
    iw.finished.connect(lambda ok, sk: got.append(ok))
    iw.cancelled.connect(lambda: cancelled.append(1))
    iw.abort()
    iw.run()
    assert cancelled == [1] and got == []
    # analisi fermata: il file controllato a metà non resta segnato come "danneggiato"
    aw = workers.AnalysisWorker([a])
    aw.cancelled.connect(lambda: cancelled.append(2))
    aw.abort()
    aw.run()
    assert cancelled == [1, 2] and a not in workers._ANALYSIS_CACHE


def test_window_stop(work):
    import comicoptimizer.main_window as mw
    infos = []
    mw.QMessageBox.information = lambda *x: infos.append(x[-1])
    w = mw.MainWindow()
    calls = []

    class FakePrep(mw.BatchPrepWorker):
        def start(self):                                            # "in corso": lo Stop lo trova
            pass

        def abort(self):
            calls.append("abort")
            self.cancelled.emit()
    mw.BatchPrepWorker = FakePrep
    w._run_prep([os.path.join(work, "x.cbr")], False, lambda t, m: calls.append("ready"))
    assert w._busy() and w.status_stack.currentIndex() == 1
    w.request_stop()
    assert calls == ["abort"] and not w._busy() and w.status_stack.currentIndex() == 0
    assert infos and "nessun fumetto è stato modificato" in infos[-1]
    w._closing = True


def _child_handlers(q):
    import logging.handlers
    from comicoptimizer import logsetup
    q.put(sum(isinstance(h, logging.handlers.RotatingFileHandler) for h in logsetup._log_handlers))


def test_log_only_in_main():
    """I processi di lavoro non aprono il file di log (lo ruotavano cancellando quello dell'app)."""
    import logging.handlers
    from comicoptimizer import logsetup
    assert sum(isinstance(h, logging.handlers.RotatingFileHandler) for h in logsetup._log_handlers) == 1
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child_handlers, args=(q,))
    p.start()
    n = q.get(timeout=30)
    p.join(30)
    assert n == 0, n


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        from comicoptimizer import history, utils
        history.HISTORY_PATH = os.path.join(work, "rinomine.jsonl")
        real_find = utils.find_tool
        test_kill_tools(work)
        test_prep_stop(work)
        test_lazy_stop(work)
        utils.find_tool = real_find
        test_lazy_processing(work)
        test_import_and_analysis_stop(work)
        test_window_stop(work)
        test_log_only_in_main()
    print("TUTTO OK")
