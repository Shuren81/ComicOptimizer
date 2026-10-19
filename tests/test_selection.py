"""Test della selezione delle card (headless). Uso, dalla cartella del progetto:

    venv/bin/python tests/test_selection.py
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication

NO = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


def mouse(widget, kind, pos, mods=NO, buttons=LEFT):
    """Invia un evento del mouse a `widget` (pos nelle sue coordinate)."""
    p = QPointF(pos)
    ev = QMouseEvent(kind, p, QPointF(widget.mapToGlobal(pos)), LEFT,
                     buttons if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton, mods)
    QApplication.sendEvent(widget, ev)


def main(work):
    import comicoptimizer.main_window as mw

    png = os.path.join(work, "p.png")
    Image.new("RGB", (20, 30), (200, 0, 0)).save(png)
    paths = []
    for i in range(1, 31):
        p = os.path.join(work, f"Fumetto {i}.cbz")
        with zipfile.ZipFile(p, "w") as z:
            z.write(png, "1.png")
        paths.append(p)

    w = mw.MainWindow()
    opened, renamed = [], []
    w.open_editor = opened.append            # prima dell'import: i segnali si collegano qui
    w.rename_cards = renamed.extend
    w.show()
    w.import_files([(p, 1) for p in paths])
    for _ in range(3):   # la griglia si sistema in più passaggi
        QApplication.processEvents()
    grid, sel = w.grid_w, w._drag_selector
    card = lambda r, c: w.grid_l.itemAtPosition(r, c).widget()
    selected = lambda: {c for c in w.cards.values() if c.selected}
    center = lambda c: c.geometry().center()

    assert w.btn_sel_all.isVisible() and w.btn_sel_all.text() == "SELEZIONA TUTTO"
    assert not w.btn_rename.isVisible()

    # click su una card (sull'immagine: l'evento passa dalla card alla griglia)
    a = card(0, 0)
    mouse(a.thumb, QEvent.Type.MouseButtonPress, QPoint(10, 10))
    mouse(a.thumb, QEvent.Type.MouseButtonRelease, QPoint(10, 10))
    assert selected() == {a} and w.btn_trash_sel.isVisible() and w.btn_rename.isVisible()
    assert w.btn_sel_all.text() == "DESELEZIONA TUTTO"            # anche con una selezione parziale
    assert not w.btn_merge.isVisible()
    # Shift+click: intervallo
    b = card(0, 2)
    mouse(b, QEvent.Type.MouseButtonPress, QPoint(10, 10), Qt.KeyboardModifier.ShiftModifier)
    mouse(b, QEvent.Type.MouseButtonRelease, QPoint(10, 10), Qt.KeyboardModifier.ShiftModifier)
    assert selected() == {card(0, i) for i in range(3)} and w.btn_merge.isVisible()
    # click di nuovo: deseleziona
    mouse(b, QEvent.Type.MouseButtonPress, QPoint(10, 10))
    mouse(b, QEvent.Type.MouseButtonRelease, QPoint(10, 10))
    assert b not in selected()

    # Esc, Ctrl+A, pulsante seleziona/deseleziona tutto
    key = lambda k, m=NO: w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, m))
    key(Qt.Key.Key_Escape)
    assert selected() == set() and not w.btn_rename.isVisible()
    key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(selected()) == 30 and w.btn_sel_all.text() == "DESELEZIONA TUTTO"
    w.btn_sel_all.click()
    assert selected() == set() and w.btn_sel_all.text() == "SELEZIONA TUTTO"
    w.btn_sel_all.click()
    assert len(selected()) == 30
    key(Qt.Key.Key_Escape)
    card(0, 0).selected = True                                    # selezione parziale: un click la toglie
    w._update_sel_buttons()
    w.btn_sel_all.click()
    assert selected() == set() and w.btn_sel_all.text() == "SELEZIONA TUTTO"

    # trascinamento: dal centro di (0,0) al centro di (1,1) → 4 card
    mouse(card(0, 0).thumb, QEvent.Type.MouseButtonPress, QPoint(10, 10))
    mouse(grid, QEvent.Type.MouseMove, center(card(1, 1)))
    box = {card(0, 0), card(0, 1), card(1, 0), card(1, 1)}
    assert selected() == box and sel.band.isVisible()
    mouse(grid, QEvent.Type.MouseMove, center(card(0, 0)) + QPoint(10, 10))   # torno indietro
    assert selected() == {card(0, 0)}
    mouse(grid, QEvent.Type.MouseMove, center(card(1, 1)))
    mouse(grid, QEvent.Type.MouseButtonRelease, center(card(1, 1)))
    assert selected() == box and not sel.band.isVisible() and w.btn_merge.isVisible()
    # Ctrl+trascinamento: toglie solo la riga 0
    ctrl = Qt.KeyboardModifier.ControlModifier
    mouse(grid, QEvent.Type.MouseButtonPress, center(card(0, 0)), ctrl)
    mouse(grid, QEvent.Type.MouseMove, center(card(0, 1)), ctrl)
    mouse(grid, QEvent.Type.MouseButtonRelease, center(card(0, 1)), ctrl)
    assert selected() == {card(1, 0), card(1, 1)}

    # i pulsanti dentro la card non cambiano la selezione
    before = selected()
    mouse(card(2, 0).btn_d, QEvent.Type.MouseButtonPress, QPoint(5, 5))
    assert selected() == before and sel.origin is None

    # doppio click: sul nome → rinomina, sull'immagine → editor
    c = card(2, 0)
    QApplication.sendEvent(c.name, QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(5, 5),
                                               QPointF(c.name.mapToGlobal(QPoint(5, 5))), LEFT, LEFT, NO))
    QApplication.sendEvent(c.thumb, QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(5, 5),
                                                QPointF(c.thumb.mapToGlobal(QPoint(5, 5))), LEFT, LEFT, NO))
    assert renamed == [c.file_path] and opened == [c.file_path]

    # scorrimento automatico: cursore sotto la griglia visibile durante il trascinamento
    key(Qt.Key.Key_Escape)
    bar, vp = w.scroll.verticalScrollBar(), w.scroll.viewport()
    assert bar.maximum() > 0, "servono più card della finestra per provare lo scorrimento"
    mouse(grid, QEvent.Type.MouseButtonPress, center(card(0, 0)))
    mouse(grid, QEvent.Type.MouseMove, center(card(0, 1)))

    class FakeCursor:
        @staticmethod
        def pos():
            return vp.mapToGlobal(QPoint(30, vp.height() + 40))

    mw.QCursor = FakeCursor
    for _ in range(200):
        sel._autoscroll()
    assert bar.value() == bar.maximum()
    last_row = (len(w.cards) - 1) // w.grid_l.columnCount()
    assert card(last_row, 0).selected and len(selected()) > 4
    mouse(grid, QEvent.Type.MouseButtonRelease, center(card(0, 1)))
    assert not sel.timer.isActive()

    # le card rimosse non restano come punto di partenza dello Shift+click
    w.last_clicked = card(0, 0)
    w.rem(card(0, 0).file_path)
    assert w.last_clicked is None
    w._closing = True
    print("TUTTO OK")


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        main(work)
