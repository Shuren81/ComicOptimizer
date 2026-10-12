"""Finestre di dialogo e widget generici (log, interruzione)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .logsetup import _qt_log_handler, log
from .style import set_variant

# NON aggiungere al root logger: causerebbe duplicati perché log è già figlio di root


class LogWindow(QDialog):
    """Finestra di log in-app, aperta con il tasto L o dal footer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log operazioni")
        fit_dialog_to_screen(self, 900, 500, min_w=500, min_h=320)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Barra superiore: filtro + pulsanti
        top = QHBoxLayout()
        from PyQt6.QtWidgets import QComboBox, QLineEdit
        self._level_box = QComboBox()
        self._level_box.addItems(["TUTTI", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self._level_box.setFixedWidth(110)
        self._level_box.currentTextChanged.connect(self._apply_filter)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Cerca nel log...")
        self._search.textChanged.connect(self._apply_filter)

        btn_clear = QPushButton("Pulisci")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._clear)

        btn_save = QPushButton("Salva")
        btn_save.setFixedWidth(80)
        btn_save.clicked.connect(self._save)

        top.addWidget(QLabel("Livello:"))
        top.addWidget(self._level_box)
        top.addSpacing(10)
        top.addWidget(QLabel("Filtro:"))
        top.addWidget(self._search, 1)
        top.addSpacing(10)
        top.addWidget(btn_clear)
        top.addWidget(btn_save)
        layout.addLayout(top)

        from PyQt6.QtWidgets import QPlainTextEdit
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            "QPlainTextEdit { background: #0d0d0d; color: #e0e0e0; "
            "font-family: monospace; font-size: 11px; border: 1px solid #333; }"
        )
        layout.addWidget(self._text)

        self._all_lines = []   # tutte le righe, per il filtro
        _qt_log_handler.new_record.connect(self._append_line)

    def _append_line(self, msg):
        self._all_lines.append(msg)
        if self._matches(msg):
            self._write(msg)

    def _matches(self, msg):
        level_filter = self._level_box.currentText()
        search_text  = self._search.text().lower()
        if level_filter != "TUTTI" and f"[{level_filter}]" not in msg:
            return False
        if search_text and search_text not in msg.lower():
            return False
        return True

    def _write(self, msg):
        # Colora le righe per livello
        if "[ERROR]" in msg or "[CRITICAL]" in msg:
            color = "#ff6b6b"
        elif "[WARNING]" in msg:
            color = "#ffd93d"
        elif "[DEBUG]" in msg:
            color = "#888"
        else:
            color = "#e0e0e0"
        self._text.appendHtml(
            f'<span style="color:{color}; white-space:pre;">{msg.replace("&","&amp;").replace("<","&lt;")}</span>'
        )
        # Auto-scroll in fondo
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _apply_filter(self):
        self._text.clear()
        for line in self._all_lines:
            if self._matches(line):
                self._write(line)

    def _clear(self):
        self._all_lines.clear()
        self._text.clear()

    def _save(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Salva log", "comicoptimizer.log", "Log (*.log *.txt)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(self._all_lines))
                log.info(f"Log salvato su '{path}'")
            except Exception as e:
                log.error(f"Impossibile salvare il log: {e}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

# --- ADATTAMENTO ALLO SCHERMO ---

def fit_dialog_to_screen(dialog, want_w, want_h, min_w=520, min_h=380, margin=60):
    """
    Apre `dialog` con la dimensione desiderata (want_w x want_h), ma senza mai
    superare lo schermo disponibile (barra delle applicazioni esclusa). Se lo
    schermo è più piccolo, la finestra si apre più piccola: il contenuto che
    non ci sta è già dentro una QScrollArea, quindi resta raggiungibile con lo
    scorrimento invece di finire fuori dalla parte visibile. `min_w`/`min_h`
    sono un limite minimo di comodità, MAI più grande dello schermo stesso.
    """
    screen = QApplication.primaryScreen().availableGeometry()
    avail_w, avail_h = max(screen.width() - margin, 200), max(screen.height() - margin, 150)
    w, h = min(want_w, avail_w), min(want_h, avail_h)
    dialog.resize(w, h)
    dialog.setMinimumSize(min(min_w, avail_w), min(min_h, avail_h))

# --- COMPONENTS ---

class StopDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Interruzione")
        self.setFixedSize(450, 180)
        l = QVBoxLayout(self)
        lbl = QLabel("<b>Cosa desideri fare?</b>")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        btns = QHBoxLayout()
        b1 = QPushButton("Annulla Subito")
        set_variant(b1, "danger")
        b1.clicked.connect(lambda: self.done(1))
        b2 = QPushButton("Termina in corso")
        set_variant(b2, "primary")
        b2.clicked.connect(lambda: self.done(2))
        b3 = QPushButton("Prosegui")
        
        b3.clicked.connect(lambda: self.done(0))
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addWidget(b3)
        l.addLayout(btns)

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")

    def wheelEvent(self, e):
        e.ignore()
