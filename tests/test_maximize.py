"""Finestra massimizzata: griglia e banner usano tutta la larghezza (schermo finto 2000×1100). Uso:

    venv/bin/python tests/test_maximize.py
"""
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

work = tempfile.mkdtemp()
cfg = os.path.join(work, "screen.json")
json.dump({"screens": [{"name": "s", "x": 0, "y": 0, "width": 2000, "height": 1100,
                        "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}, open(cfg, "w"))
os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={cfg}"

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import comicoptimizer.main_window as mw

paths = []
for i in range(21):
    p = os.path.join(work, f"F {i}.cbz")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("1.png", b"x")
    paths.append((p, 1))
w = mw.MainWindow()
w.show()
w.import_files(paths)
QTest.qWait(100)
normal_w = w.width()
assert w._grid_cols == 7 and w.minimumWidth() == w.maximumWidth() == normal_w

# massimizzata: più colonne, banner più largo, niente larghezza fissa
w.showMaximized()
QTest.qWait(300)
m = w.centralWidget().layout().contentsMargins()
assert w.isMaximized() and w.width() > normal_w
assert w._grid_cols == w._cols_fit(w.width(), 50) and w._grid_cols > 7, (w._grid_cols, w.width())
assert w.grid_l.itemAtPosition(0, w._grid_cols - 1) is not None       # la prima fila è piena
assert w.title_lbl.pixmap().width() == min(w.width() - m.left() - m.right(), 2000)
assert w.grid_w.width() <= w.scroll.viewport().width()                # tutte le card visibili
first, last = w.grid_l.itemAtPosition(0, 0).widget(), w.grid_l.itemAtPosition(0, w._grid_cols - 1).widget()
left, right = first.geometry().left(), w.grid_w.width() - last.geometry().right()
assert abs(left - right) <= 20, (left, right)                         # griglia centrata

# di nuovo normale: torna la larghezza calcolata
w.showNormal()
QTest.qWait(300)
assert not w.isMaximized() and w._grid_cols == 7 and w.width() == normal_w
assert w.minimumWidth() == w.maximumWidth()
w._closing = True
print("TUTTO OK")
