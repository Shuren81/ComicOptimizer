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


def fake_screen(width):
    """Sostituisce la larghezza disponibile dello schermo vista dalla finestra."""
    import comicoptimizer.main_window as mw
    real = QApplication.primaryScreen()

    class Screen:
        def availableGeometry(self):
            g = real.availableGeometry()
            return QRect(0, 0, width, g.height())

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
    print("TUTTO OK")


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        main(work)
