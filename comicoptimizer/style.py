"""Foglio di stile (QSS) e piccoli aiuti grafici."""

from PyQt6.QtCore import QEvent, QObject, QTimer

# --- STILE ---
# Un solo foglio di stile per tutta l'app. I pulsanti colorati usano la proprietà
# "variant" (vedi set_variant): niente più stili scritti a mano su ogni pulsante.
STYLESHEET = """
QToolTip { background: #263238; color: #eceff1; border: 1px solid #00e5ff;
           border-radius: 6px; padding: 4px 8px; }

QPushButton { background: #333; color: #f0f0f0; border: 1px solid #4a4a4a;
              border-radius: 10px; padding: 8px 16px; font-weight: 600; }
QPushButton:hover    { background: #404040; border-color: #666; }
QPushButton:pressed  { background: #262626; }
QPushButton:disabled { background: #2a2a2a; color: #777; border-color: #333; }
QPushButton:focus    { border-color: #00e5ff; }

QPushButton[variant="primary"]        { background: #e65100; border-color: #e65100; color: white; font-weight: 800; }
QPushButton[variant="primary"]:hover  { background: #f4600c; border-color: #f4600c; }
QPushButton[variant="primary"]:pressed{ background: #bf4400; }
QPushButton[variant="accent"]        { background: #00bcd4; border-color: #00bcd4; color: #002b33; }
QPushButton[variant="accent"]:hover  { background: #26d0e6; border-color: #26d0e6; }
QPushButton[variant="accent"]:pressed{ background: #0097a7; }
QPushButton[variant="info"]          { background: #0277bd; border-color: #0277bd; color: white; font-weight: 800; }
QPushButton[variant="info"]:hover    { background: #0288d1; border-color: #0288d1; }
QPushButton[variant="info"]:pressed  { background: #01579b; }
QPushButton[variant="danger"]        { background: #b71c1c; border-color: #b71c1c; color: white; }
QPushButton[variant="danger"]:hover  { background: #d32f2f; border-color: #d32f2f; }
QPushButton[variant="danger"]:pressed{ background: #8e1515; }
QPushButton[variant="success"]       { background: #2e7d32; border-color: #2e7d32; color: white; font-weight: 800; }
QPushButton[variant="success"]:hover { background: #388e3c; border-color: #388e3c; }
QPushButton[variant="success"]:pressed{ background: #1b5e20; }
QPushButton[variant="muted"]         { background: #546e7a; border-color: #546e7a; color: white; }
QPushButton[variant="muted"]:hover   { background: #64808d; border-color: #64808d; }
QPushButton[variant="muted"]:pressed { background: #455a64; }
QPushButton:disabled[variant] { background: #2a2a2a; border-color: #333; color: #777; }

/* piccoli pulsanti dentro le card e nell'editor */
QPushButton[sz="small"] { padding: 4px 6px; border-radius: 8px; font-size: 12px; }
QPushButton[sz="tiny"]  { padding: 0px; border-radius: 10px; font-size: 10px; }

/* link nel piè di pagina */
QPushButton[variant="link"]        { background: transparent; border: none; color: #FFB300;
                                     padding: 4px 8px; font-size: 13px; font-weight: 700; }
QPushButton[variant="link"]:hover  { color: #ffd54f; text-decoration: underline; }
QPushButton[variant="linklog"]     { background: transparent; border: none; color: #90caf9;
                                     padding: 4px 8px; font-size: 13px; font-weight: 700; }
QPushButton[variant="linklog"]:hover { color: #bbdefb; }

QCheckBox { color: #999; font-size: 11px; spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
                       border: 1px solid #666; background: #1e1e1e; }
QCheckBox::indicator:hover   { border-color: #00e5ff; }
QCheckBox::indicator:checked { background: #00e5ff; border-color: #00e5ff; }

QProgressBar { border: 1px solid #00e5ff; border-radius: 8px; background: #1a1a1a;
               text-align: center; color: white; font-weight: bold; }
QProgressBar::chunk { background: #00e5ff; border-radius: 7px; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical   { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:vertical   { background: #4a4a4a; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:horizontal { background: #4a4a4a; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:hover { background: #00bcd4; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMessageBox, QDialog { background: #1e1e1e; }
"""

def set_variant(widget, variant):
    """Assegna la variante di colore a un pulsante e ricarica lo stile."""
    widget.setProperty("variant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)

class _VisibilityWatcher(QObject):
    """Chiama `callback` (con un piccolo ritardo, una volta sola) quando uno dei
    widget osservati viene mostrato o nascosto."""
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._cb = callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._cb)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self._timer.start()
        return False
