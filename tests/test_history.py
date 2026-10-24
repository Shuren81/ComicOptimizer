"""Test della cronologia delle rinomine (annullabili anche dopo un riavvio) e del log. Uso:

    venv/bin/python tests/test_history.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def touch(work, name):
    p = os.path.join(work, name)
    open(p, "wb").write(b"x")
    return p


def test_registry(work):
    from comicoptimizer import history
    b1, b2 = history.new_batch(), history.new_batch()
    history.record(b1, "/a", "/A")
    history.record(b1, "/b", "/B")
    history.record(b2, "/c", "/C")
    history.record_undo(b1, "/a")
    with open(history.HISTORY_PATH, "a") as f:
        f.write('{"batch": rovinata\n')                        # riga a metà (es. corrente saltata)
    ops = history.batches()
    assert [op["id"] for op in ops] == [b2, b1]                 # dalla più recente
    assert ops[1]["pairs"] == [("/a", "/A"), ("/b", "/B")] and ops[1]["pending"] == [("/b", "/B")]
    # limite: solo le ultime 50 operazioni
    for i in range(60):
        history.record(f"x{i}", f"/{i}", f"/N{i}")
    history.prune()
    ops = history.batches()
    assert len(ops) == 50 and ops[0]["id"] == "x59" and ops[-1]["id"] == "x10"
    os.remove(history.HISTORY_PATH)


def test_after_restart(work):
    """Rinomina, "chiusura", nuova finestra: l'annullamento funziona dal registro su disco."""
    import comicoptimizer.main_window as mw
    from comicoptimizer import history
    a, b = touch(work, "naruto_1.cbz"), touch(work, "naruto_2.cbz")
    w = mw.MainWindow()
    batch = history.new_batch()
    # due passaggi nella stessa finestra: a → A → AA
    A, B = os.path.join(work, "Naruto 1.cbz"), os.path.join(work, "Naruto 2.cbz")
    AA = os.path.join(work, "Naruto - 001.cbz")
    w._do_renames([(a, A), (b, B)], batch)
    w._do_renames([(A, AA)], batch)
    w._closing = True                                           # "chiusura" (senza toccare il log vero)
    lines = [json.loads(x) for x in open(history.HISTORY_PATH)]
    assert [(x["old"], x["new"]) for x in lines] == [(a, A), (b, B), (A, AA)]   # scritto subito
    # "riavvio": una finestra nuova legge il registro
    w2 = mw.MainWindow()
    assert w2._undo_batch and w2._undo_batch["id"] == batch
    w2.import_files([(AA, 1)])
    w2.show()
    QApplication.processEvents()
    assert w2.btn_undo_rename.isVisible()
    # B è stato spostato nel frattempo: si salta con un avviso, gli altri tornano indietro
    os.makedirs(os.path.join(work, "altrove"))
    os.rename(B, os.path.join(work, "altrove", "Naruto 2.cbz"))
    warns = []
    mw.QMessageBox.warning = lambda *x: warns.append(x[-1])
    assert w2.undo_rename() is None and os.path.exists(a) and not os.path.exists(AA)
    assert len(warns) == 1 and "Naruto 2.cbz" in warns[0]
    assert a in w2.cards                                        # la card segue il nome
    op = history.batches()[0]
    assert op["pending"] == [(b, B)] and not w2.btn_undo_rename.isVisible()   # B non c'è più
    # tornato al suo posto: dalla Cronologia si annulla anche quello
    os.rename(os.path.join(work, "altrove", "Naruto 2.cbz"), B)
    assert w2.undo_batch(history.batches()[0]) == 1 and os.path.exists(b)
    assert history.batches()[0]["pending"] == []
    w2._closing = True


def test_dialog(work):
    import comicoptimizer.main_window as mw
    from comicoptimizer import history
    from comicoptimizer.dialogs import HistoryDialog
    c = touch(work, "tex.cbz")
    C = os.path.join(work, "Tex 001.cbz")
    batch = history.new_batch()
    w = mw.MainWindow()
    w._do_renames([(c, C)], batch)
    calls = []
    d = HistoryDialog(w, lambda op: (calls.append(op["id"]), w.undo_batch(op)))
    assert d.table.item(0, 3).text() == "annullabile (1)" and "tex.cbz → Tex 001.cbz" in d.table.item(0, 2).text()
    d.table.cellWidget(0, 4).click()
    assert calls == [batch] and os.path.exists(c)
    assert d.table.item(0, 3).text() == "già annullata" and not d.table.cellWidget(0, 4).isEnabled()
    assert d.table.item(1, 3).text() == "già annullata"           # l'operazione del test precedente
    d.reject()
    w._closing = True


def test_log_rotation():
    import logging.handlers
    from comicoptimizer import logsetup
    h = [x for x in logsetup._log_handlers if isinstance(x, logging.handlers.RotatingFileHandler)]
    assert h and h[0].maxBytes == 2_000_000 and h[0].backupCount == 3


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        from comicoptimizer import history
        history.HISTORY_PATH = os.path.join(work, "rinomine.jsonl")
        test_registry(work)
        test_after_restart(work)
        test_dialog(work)
        test_log_rotation()
    print("TUTTO OK")
