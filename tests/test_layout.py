"""Test delle colonne della griglia rispetto alla larghezza dello schermo (headless). Uso:

    venv/bin/python tests/test_layout.py
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication


def fake_screen(width, height=None):
    """Sostituisce la larghezza (e l'altezza) disponibile dello schermo vista dalla finestra."""
    import comicoptimizer.main_window as mw
    real = QApplication.primaryScreen()

    class Screen:
        def availableGeometry(self):
            g = real.availableGeometry()
            return QRect(0, 0, width, height or g.height())

    class App:
        def __getattr__(self, name):
            return getattr(QApplication, name)

        @staticmethod
        def primaryScreen():
            return Screen()

    mw.QApplication = App()


def window_with(n, work):
    import comicoptimizer.main_window as mw
    w = mw.MainWindow()
    w.show()
    paths = []
    for i in range(n):
        p = os.path.join(work, f"F {i}.cbz")
        if not os.path.exists(p):
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("1.png", b"x")
        paths.append(p)
    w.import_files([(p, 1) for p in paths])
    for _ in range(3):
        QApplication.processEvents()
    return w


def main(work):
    # schermo stretto (800 px): 3 colonne, tutte le card dentro l'area visibile
    fake_screen(800)
    w = window_with(30, work)
    assert w.grid_l.columnCount() == 3, w.grid_l.columnCount()
    assert w.width() <= 800
    vp = w.scroll.viewport().width()
    assert w.grid_w.width() <= vp, (w.grid_w.width(), vp)
    assert all(c.geometry().right() < vp for c in w.cards.values())
    w._closing = True
    w.close()

    # schermo largo (1920 px): come prima, 7 colonne con 30 fumetti e 4 con 2
    fake_screen(1920)
    w = window_with(30, work)
    assert w.grid_l.columnCount() == 7, w.grid_l.columnCount()
    assert w._cols_for_count(2) == 4 and w._cols_for_count(5) == 5 and w._cols_for_count(0) == 4
    w._closing = True
    w.close()

    # schermo minuscolo: almeno una colonna
    fake_screen(150)
    assert w._cols_fit_screen() == 1
    fake_screen(1920)
    banner_and_empty_grid(work)
    print("TUTTO OK")


def banner_and_empty_grid(work):
    import comicoptimizer.main_window as mw
    from comicoptimizer import config

    # banner: largo quanto la griglia (meno i margini), proporzioni 2000×260
    w = window_with(0, work)
    assert not hasattr(w, "drop_zone")
    pix = w.title_lbl.pixmap()
    m = w.centralWidget().layout().contentsMargins()
    grid_w = min(w._win_width_for_cols(w._cols_for_count(0)), w.width())
    assert pix.width() == grid_w - m.left() - m.right(), (pix.width(), w.width())
    assert abs(pix.height() - pix.width() * 260 / 2000) <= 1
    # lista vuota: scritta con disegno, niente pulsanti, frase d'invito;
    # con fumetti: griglia, pulsanti e suggerimento di sempre; "Pulisci lista" → di nuovo vuota
    def is_empty_screen():
        return (w.grid_stack.currentWidget() is w.empty_lbl and not w.top_bar_scroll.isVisible()
                and w.hint_lbl.text() in mw._EMPTY_HINTS)
    assert is_empty_screen() and not w.empty_lbl.art.isNull()
    w.import_files([(os.path.join(work, "F 0.cbz"), 1)])
    assert w.grid_stack.currentWidget() is w.scroll and w.top_bar_scroll.isVisible()
    assert w.hint_lbl.text() == mw._HINT_CARDS and "Shift" in w.hint_lbl.toolTip()
    w.clear_all()
    assert is_empty_screen()
    # riscontro durante il trascinamento dei file
    w.set_drop_style(True)
    assert "dashed" in w.grid_stack.styleSheet() and "#00e5ff" in w.empty_lbl.label.styleSheet()
    w.set_drop_style(False)
    assert w.grid_stack.styleSheet() == ""

    # fine lavoro: lista pulita solo se tutti i fumetti sono CONVERTITI
    mw.QMessageBox.exec = lambda self: 0          # niente popup bloccante nel test
    w.chk_notify.setChecked(False)
    summary = {'aborted': False, 'errors': [], 'mode': 'webp', 'done': 2, 'total': 2,
               'skipped': 0, 'size_before': 0, 'size_after': 0, 'pages_kept': 0, 'elapsed': 1}
    two = [(os.path.join(work, f"F {i}.cbz"), 1) for i in range(2)]
    w.import_files(two)
    for c in w.cards.values():
        c.set_status(3)
    list(w.cards.values())[1].set_status(2)       # uno solo riparato: la lista resta
    w._on_job_done(summary)
    assert len(w.cards) == 2
    for c in w.cards.values():
        c.set_status(3)
    w._on_job_done(summary)
    assert w.cards == {} and w.grid_stack.currentWidget() is w.empty_lbl
    for t in list(w.active_threads):
        t.wait(5000)
    w._closing = True
    w.close()

    # pochi fumetti: selezionando una card compaiono i pulsanti e la finestra si allarga,
    # ma banner e card non si spostano (il doppio click sul nome resta sulla stessa card)
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import QSize
    w = window_with(2, work)
    card = list(w.cards.values())[0]
    before = (w.title_lbl.pixmap().height(), card.mapTo(w, QPoint(0, 0)), w.width())
    w.top_bar_w.minimumSizeHint = lambda: QSize(1400, 50)   # pulsanti larghi come su uno schermo vero
    card.selected = True
    w.handle_selection(card, Qt.KeyboardModifier.NoModifier)
    QTest.qWait(QApplication.doubleClickInterval() // 2)
    assert w.width() == before[2]                 # nessun cambio di larghezza a metà doppio click
    QTest.qWait(QApplication.doubleClickInterval() + 200)
    assert w.btn_rename.isVisible() and w.width() > before[2]
    assert (w.title_lbl.pixmap().height(), card.mapTo(w, QPoint(0, 0))) == before[:2]
    w._closing = True
    w.close()

    # una sola fila di card: nessuna barra di scorrimento. Su uno schermo alto la finestra
    # si allunga, su uno basso il banner si abbassa; con più file la prima resta intera
    m = None
    for screen_h, n in ((1080, 7), (800, 7), (800, 10)):
        fake_screen(1920, screen_h)
        w = window_with(n, work)
        QTest.qWait(QApplication.doubleClickInterval() + 300)   # anche dopo il ricalcolo della larghezza
        m = w.grid_l.contentsMargins()
        assert w.grid_stack.height() >= mw.CARD_H + m.top() + m.bottom(), (screen_h, n, w.grid_stack.height())
        assert w.height() <= screen_h
        if n <= 7:
            assert not w.scroll.verticalScrollBar().isVisible(), (screen_h, n)
        w._closing = True
        w.close()
    fake_screen(1920)

    # banner mancante: torna la scritta
    real = config.RES_DIR
    config.RES_DIR = work
    w = window_with(0, work)
    assert w.title_lbl.pixmap().isNull() and "ComicOptimizer" in w.title_lbl.text()
    assert w.empty_lbl.art.isNull() and "TRASCINA" in w.empty_lbl.label.text()
    w.empty_lbl.repaint()                         # senza disegno: nessun errore
    config.RES_DIR = real
    w._closing = True
    w.close()


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        main(work)
