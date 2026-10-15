"""Finestre di dialogo e widget generici (log, interruzione, unione)."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .logsetup import _qt_log_handler, log
from .style import set_variant
from .utils import (
    apply_schema,
    capitalize_words,
    clean_filename,
    get_natural_sort_key,
    merge_name_hint,
    rename_problem,
    split_name,
    underscores_to_spaces,
)

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

class MergeDialog(QDialog):
    """Unione di più fumetti: nome del CBZ finale, destinazione e modalità."""
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unisci fumetti")
        fit_dialog_to_screen(self, 620, 460, min_w=420, min_h=320)
        self.to_webp = False
        l = QVBoxLayout(self)

        l.addWidget(QLabel(f"<b>{len(paths)} fumetti</b> da unire, in quest'ordine:"))
        lst = QListWidget()
        lst.addItems([os.path.basename(p) for p in paths])
        l.addWidget(lst, 1)

        l.addWidget(QLabel("Nome del nuovo fumetto (senza .cbz):"))
        self.name = QLineEdit(merge_name_hint(paths))
        l.addWidget(self.name)

        l.addWidget(QLabel("Destinazione:"))
        row = QHBoxLayout()
        self.dest = QLineEdit(os.path.dirname(paths[0]))
        b_dir = QPushButton("Sfoglia")
        b_dir.clicked.connect(self._browse)
        row.addWidget(self.dest, 1)
        row.addWidget(b_dir)
        l.addLayout(row)

        btns = QHBoxLayout()
        b_can = QPushButton("Annulla")
        set_variant(b_can, "danger")
        b_can.clicked.connect(self.reject)
        b_mrg = QPushButton("Unisci")
        set_variant(b_mrg, "info")
        b_mrg.clicked.connect(lambda: self._go(False))
        b_webp = QPushButton("Unisci e converti")
        set_variant(b_webp, "primary")
        b_webp.clicked.connect(lambda: self._go(True))
        btns.addWidget(b_can)
        btns.addStretch()
        btns.addWidget(b_mrg)
        btns.addWidget(b_webp)
        l.addLayout(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Destinazione", self.dest.text())
        if d:
            self.dest.setText(d)

    def values(self):
        """(nome senza caratteri non validi nei nomi di file, cartella di destinazione)"""
        return clean_filename(self.name.text()), self.dest.text().strip()

    def _go(self, to_webp):
        name, dest = self.values()
        if not name:
            QMessageBox.warning(self, "Unisci", "Scrivi il nome del nuovo fumetto.")
        elif not os.path.isdir(dest):
            QMessageBox.warning(self, "Unisci", "La cartella di destinazione non esiste.")
        else:
            self.to_webp = to_webp
            self.accept()

class RenameDialog(QDialog):
    """
    Rinomina uno o più fumetti: lo schema riempie la colonna "Nuovo nome",
    i tasti la trasformano, le celle si possono modificare a mano.
    Le righe con un problema (rosse) non vengono rinominate.
    """
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rinomina")
        fit_dialog_to_screen(self, 900, 560, min_w=560, min_h=360)
        self.paths = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        self._schema_err = [None] * len(self.paths)
        self._targets = []
        l = QVBoxLayout(self)

        row = QHBoxLayout()
        single = len(self.paths) == 1
        self.schema = QLineEdit(split_name(self.paths[0])[0] if single else "<nome>")
        self.digits = QSpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(3)
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        row.addWidget(QLabel("Schema:"))
        row.addWidget(self.schema, 1)
        row.addWidget(QLabel("Cifre:"))
        row.addWidget(self.digits)
        row.addWidget(QLabel("Parti da:"))
        row.addWidget(self.start)
        l.addLayout(row)
        hint = QLabel("Segnaposto: <nome> nome attuale · <num> numero già nel nome · "
                      "<n> progressivo · <parte1>, <parte2>… pezzi separati da \" - \"")
        hint.setStyleSheet("color: #aaa; font-size: 11px;")
        hint.setTextFormat(Qt.TextFormat.PlainText)   # altrimenti "<nome>" sembra un tag HTML
        hint.setWordWrap(True)
        l.addWidget(hint)

        row = QHBoxLayout()
        b_us = QPushButton("_ → spazio")
        b_us.clicked.connect(lambda: self._transform(underscores_to_spaces))
        b_cap = QPushButton("Iniziali Maiuscole")
        b_cap.clicked.connect(lambda: self._transform(capitalize_words))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Cerca")
        self.repl = QLineEdit()
        self.repl.setPlaceholderText("Sostituisci con")
        b_rep = QPushButton("Sostituisci")
        b_rep.clicked.connect(lambda: self.find.text() and self._transform(
            lambda s: s.replace(self.find.text(), self.repl.text())))
        for b in (b_us, b_cap, b_rep):
            b.setAutoDefault(False)
        row.addWidget(b_us)
        row.addWidget(b_cap)
        row.addSpacing(12)
        row.addWidget(self.find, 1)
        row.addWidget(self.repl, 1)
        row.addWidget(b_rep)
        l.addLayout(row)

        self.table = QTableWidget(len(self.paths), 3)
        self.table.setHorizontalHeaderLabels(["Nome attuale", "Nuovo nome", "Estensione / problema"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, p in enumerate(self.paths):
            cur = QTableWidgetItem(os.path.basename(p))
            cur.setFlags(cur.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, cur)
            self.table.setItem(i, 1, QTableWidgetItem())
            note = QTableWidgetItem()
            note.setFlags(note.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, note)
        self.table.setColumnWidth(0, 330)
        self.table.setColumnWidth(1, 330)
        l.addWidget(self.table, 1)

        btns = QHBoxLayout()
        b_can = QPushButton("Annulla")
        set_variant(b_can, "danger")
        b_can.setAutoDefault(False)
        b_can.clicked.connect(self.reject)
        b_help = QPushButton("? Aiuto")
        set_variant(b_help, "info")
        b_help.setToolTip("Come si rinomina (F1)")
        b_help.setAutoDefault(False)
        b_help.clicked.connect(self.show_help)
        self.b_ok = QPushButton("Rinomina")
        set_variant(self.b_ok, "success")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self.accept)
        btns.addWidget(b_can)
        btns.addWidget(b_help)
        btns.addStretch()
        btns.addWidget(self.b_ok)
        l.addLayout(btns)

        self.schema.textChanged.connect(self._fill)
        self.digits.valueChanged.connect(self._fill)
        self.start.valueChanged.connect(self._fill)
        self.table.itemChanged.connect(self._edited)
        self._fill()
        self.schema.selectAll()
        self.schema.setFocus()

    def _fill(self):
        """Lo schema riscrive tutta la colonna "Nuovo nome"."""
        self.table.blockSignals(True)
        for i, p in enumerate(self.paths):
            stem = split_name(p)[0]
            try:
                new, err = apply_schema(stem, self.schema.text(), self.start.value() + i,
                                        self.digits.value()), None
            except ValueError as e:
                new, err = stem, str(e)
            self.table.item(i, 1).setText(new)
            self._schema_err[i] = err
        self.table.blockSignals(False)
        self._check()

    def _edited(self, item):
        if item.column() == 1:
            self._schema_err[item.row()] = None   # corretta a mano
            self._check()

    def _transform(self, fn):
        """Applica `fn` alle righe selezionate nella tabella (o a tutte)."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or range(len(self.paths))
        self.table.blockSignals(True)
        for r in rows:
            item = self.table.item(r, 1)
            item.setText(fn(item.text()))
            self._schema_err[r] = None
        self.table.blockSignals(False)
        self._check()

    def _check(self):
        """Colora le righe, calcola le destinazioni valide e aggiorna il pulsante."""
        self.table.blockSignals(True)
        self._targets, taken = [], set()
        for i, p in enumerate(self.paths):
            stem, ext = split_name(p)
            name = clean_filename(self.table.item(i, 1).text())
            target = os.path.join(os.path.dirname(p), name + ext) if name else ""
            if self._schema_err[i]:
                problem = self._schema_err[i]
            elif not name:
                problem = "nome vuoto"
            elif target == p:
                problem = None
            else:
                problem = rename_problem(p, target, taken)
            if target:
                taken.add(os.path.normcase(target))
            changed = problem is None and target != p
            if changed:
                self._targets.append((p, target))
            bg = QColor("#5c1a1a") if problem else QColor(0, 0, 0, 0)
            for c in range(3):
                self.table.item(i, c).setBackground(bg)
            self.table.item(i, 2).setText(f"⚠ {problem}" if problem
                                          else (ext or "cartella") + ("" if changed else " · invariato"))
        self.table.blockSignals(False)
        n = len(self._targets)
        self.b_ok.setText(f"Rinomina <n> di {len(self.paths)}" if len(self.paths) > 1 else "Rinomina")
        self.b_ok.setEnabled(n > 0)

    def renames(self):
        """[(vecchio percorso, nuovo percorso)] delle sole righe valide e cambiate."""
        return list(self._targets)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F1:
            self.show_help()
        else:
            super().keyPressEvent(e)

    def show_help(self):
        box = QMessageBox(self)
        box.setWindowTitle("Rinomina: aiuto")
        box.setText(RENAME_HELP)
        box.exec()

RENAME_HELP = """
<h3>Come si rinomina</h3>
<ol>
<li><b>Schema</b>: scrivi il formato del nuovo nome. La colonna <i>Nuovo nome</i> si aggiorna mentre scrivi.</li>
<li><b>Tasti</b>: sistemano i nomi della colonna (sulle righe selezionate nella tabella, o su tutte).</li>
<li><b>A mano</b>: doppio click su una cella di <i>Nuovo nome</i> per correggere un caso particolare.</li>
<li><b>Rinomina</b>: cambia il nome dei soli file validi. Le righe rosse e quelle invariate non vengono toccate.</li>
</ol>
<p>Attenzione: cambiare lo schema riscrive tutta la colonna, comprese le correzioni fatte a mano o con i tasti.
Usa prima lo schema, poi i tasti, per ultime le correzioni a mano.</p>

<h3>Segnaposto dello schema</h3>
<table cellspacing="4">
<tr><td><b>&lt;nome&gt;</b></td><td>il nome attuale</td></tr>
<tr><td><b>&lt;num&gt;</b></td><td>il primo numero già presente nel nome, con le <i>Cifre</i> scelte
 (<code>naruto_12</code> → <code>012</code>). Tiene il numero vero: ideale per numerazioni sparse.</td></tr>
<tr><td><b>&lt;n&gt;</b></td><td>un numero progressivo, nell'ordine della tabella, da <i>Parti da</i>, con le <i>Cifre</i> scelte</td></tr>
<tr><td><b>&lt;parte1&gt;</b>, <b>&lt;parte2&gt;</b>…</td><td>i pezzi del nome separati da un trattino con spazi o <code>_</code> attorno
 (<code>Zagor - 45 - Il ritorno</code> → parte1 <code>Zagor</code>, parte2 <code>45</code>, parte3 <code>Il ritorno</code>).
 Il trattino dentro una parola (<code>Spider-Man</code>) non divide.</td></tr>
</table>
<p>Tutto il resto dello schema è testo fisso. Esempi:<br>
<code>Naruto - #&lt;num&gt;</code> → <code>Naruto - #012</code><br>
<code>&lt;parte1&gt; - #&lt;num&gt; - &lt;parte3&gt;</code> → <code>Zagor - #045 - Il ritorno</code><br>
<code>Dylan Dog &lt;n&gt;</code> → <code>Dylan Dog 001</code>, <code>Dylan Dog 002</code>…</p>

<h3>Tasti</h3>
<ul>
<li><b>_ → spazio</b>: sostituisce i trattini bassi con spazi (e toglie gli spazi doppi).</li>
<li><b>Iniziali Maiuscole</b>: maiuscola la prima lettera di ogni parola, senza abbassare le altre
 (<code>DC</code> resta <code>DC</code>, <code>l'alba</code> diventa <code>L'alba</code>).</li>
<li><b>Cerca / Sostituisci con</b>: sostituisce un pezzo di testo uguale in tutti i nomi.</li>
</ul>

<h3>Righe rosse</h3>
<p>Non vengono rinominate: <i>numero non trovato</i>, <i>parte mancante</i>, <i>nome vuoto</i>,
<i>esiste già</i> (un altro file ha già quel nome), <i>nome ripetuto</i> (due righe con lo stesso nome).
Correggile a mano nella cella.</p>

<h3>Sicurezza</h3>
<p>Si cambia solo il nome: il contenuto del fumetto non viene toccato e l'estensione resta la stessa.
Un file esistente non viene mai sovrascritto. I caratteri <code>\\ / : * ? " &lt; &gt; |</code> diventano <code>_</code>.</p>
<p><b>Come aprire la rinomina:</b> doppio click sul nome nella card, tasto <b>F2</b> o pulsante
<b>Rinomina selezionati</b>. In questa finestra, <b>F1</b> apre questo aiuto.</p>
"""

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")

    def wheelEvent(self, e):
        e.ignore()
