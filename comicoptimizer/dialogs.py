"""Finestre di dialogo e widget generici (log, interruzione, unione)."""

import os

from PyQt6.QtCore import QEvent, QSettings, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
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
    QTextBrowser,
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
    wildcard_replace,
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
    Rinomina uno o più fumetti. La colonna "Nuovo nome" è ricalcolata a ogni modifica:
    schema → Cerca/Sostituisci → "_ → spazio" → "Iniziali Maiuscole", sulle righe
    selezionate (o su tutte se non ce ne sono): le altre restano invariate. Le celle
    corrette a mano restano fisse; svuotandole torna il nome automatico.
    Le righe con un problema (rosse) non vengono rinominate.
    """
    SETTINGS = ("Shuren", "ComicOptimizer")
    RECENT_MAX = 10
    PRESETS = ["<parte1> #<parte2>",                               # serie
               "<parte1> #<parte2> - <parte3>",                    # una storia per numero
               "<parte1> #<parte2> - <parte3> (Vol. <parte4:1>)"]  # contenitore, storie a volumi

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rinomina")
        fit_dialog_to_screen(self, 920, 600, min_w=580, min_h=380)
        self.paths = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        self._schema_err = [None] * len(self.paths)
        self._manual = {}            # riga → nome scritto a mano (fisso)
        self._single_row = None      # riga selezionata da sola: lo Schema mostra il suo nome
        self._multi_schema = ""      # lo schema messo da parte nel frattempo
        self._targets = []
        l = QVBoxLayout(self)

        row = QHBoxLayout()
        single = len(self.paths) == 1
        self.schema = QComboBox()
        self.schema.setEditable(True)
        self.schema.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        recent = self._recent()
        self.schema.addItems(recent + [x for x in self.PRESETS if x not in recent])
        self.schema.setEditText(split_name(self.paths[0])[0] if single else "<nome>")
        self.schema.setToolTip("Nel menu a tendina: gli schemi usati di recente e tre schemi pronti")
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
        row = QHBoxLayout()
        hint = QLabel("Segnaposto: <nome> nome attuale · <num> numero già nel nome · "
                      "<n> progressivo · <parte1>, <parte2>… pezzi del nome")
        hint.setStyleSheet("color: #aaa; font-size: 11px;")
        hint.setTextFormat(Qt.TextFormat.PlainText)   # altrimenti "<nome>" sembra un tag HTML
        hint.setWordWrap(True)
        self.split_numbers = QCheckBox("Dividi anche ai numeri")
        self.split_numbers.setChecked(True)
        self.split_numbers.setToolTip("Le parti si dividono ai \" - \" e ai numeri staccati\n"
                                      "(\"titolo 43 sottotitolo\" → titolo · 43 · sottotitolo).\n"
                                      "Togli la spunta per nomi come \"Fantastici 4\".")
        row.addWidget(hint, 1)
        row.addWidget(self.split_numbers)
        l.addLayout(row)

        row = QHBoxLayout()
        self.b_us = QPushButton("_ → spazio")
        self.b_cap = QPushButton("Iniziali Maiuscole")
        for b in (self.b_us, self.b_cap):
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setToolTip("Acceso/spento: vale per le righe selezionate (o per tutte)")
        self.find = QLineEdit()
        self.find.setPlaceholderText("Cerca  (? = un carattere, * = qualsiasi testo)")
        self.repl = QLineEdit()
        self.repl.setPlaceholderText("Sostituisci con  (* ? = testo trovato)")
        self.case = QCheckBox("Maiuscole/minuscole")
        self.case.setToolTip("Se spuntato, \"naruto\" non trova \"NARUTO\"")
        row.addWidget(self.b_us)
        row.addWidget(self.b_cap)
        row.addSpacing(12)
        row.addWidget(self.find, 1)
        row.addWidget(self.repl, 1)
        row.addWidget(self.case)
        l.addLayout(row)

        row = QHBoxLayout()
        sel_lbl = QLabel("Con righe selezionate si rinominano solo quelle (con una sola, lo Schema mostra il suo "
                         "nome) · click: solo quella riga (di nuovo: deseleziona) · trascina o Shift+click: "
                         "intervallo · Ctrl+click o Ctrl+trascina: aggiunge/toglie")
        sel_lbl.setWordWrap(True)
        sel_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        b_all = QPushButton("Tutte")
        b_none = QPushButton("Nessuna")
        for b in (b_all, b_none):
            b.setProperty("sz", "small")
            set_variant(b, "muted")
            b.setAutoDefault(False)
        row.addWidget(sel_lbl, 1)
        row.addWidget(b_all)
        row.addWidget(b_none)
        l.addLayout(row)

        self.table = QTableWidget(len(self.paths), 3)
        self.table.setHorizontalHeaderLabels(["Nome attuale", "Nuovo nome", "Estensione / problema"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        # click = solo quella riga; trascina/Shift = intervallo; Ctrl = aggiunge/toglie
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
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
        b_all.clicked.connect(self.table.selectAll)
        b_none.clicked.connect(self.table.clearSelection)

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

        self.schema.editTextChanged.connect(self._fill)
        self.schema.lineEdit().returnPressed.connect(
            lambda: self.b_ok.isEnabled() and self.accept())
        for sig in (self.digits.valueChanged, self.start.valueChanged, self.split_numbers.toggled,
                    self.b_us.toggled, self.b_cap.toggled, self.find.textChanged,
                    self.repl.textChanged, self.case.toggled):
            sig.connect(self._fill)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.itemChanged.connect(self._edited)
        self.table.viewport().installEventFilter(self)
        self._fill()
        self.schema.lineEdit().selectAll()
        self.schema.setFocus()

    def _post(self, s):
        """Cerca/Sostituisci e tasti, nell'ordine; alla fine spazi doppi tolti."""
        s = wildcard_replace(s, self.find.text(), self.repl.text(), self.case.isChecked())
        if self.b_us.isChecked():
            s = underscores_to_spaces(s)
        if self.b_cap.isChecked():
            s = capitalize_words(s)
        return " ".join(s.split())

    def _fill(self):
        """Ricalcola tutta la colonna "Nuovo nome"."""
        # con righe selezionate si rinominano solo quelle; <n> conta solo loro
        scope = {i.row() for i in self.table.selectedIndexes()} or set(range(len(self.paths)))
        post = bool(self.find.text() or self.b_us.isChecked() or self.b_cap.isChecked())
        k = 0
        self.table.blockSignals(True)
        for i, p in enumerate(self.paths):
            err = None
            stem = split_name(p)[0]
            if i in self._manual:
                new = self._manual[i]
            elif i not in scope:
                new = stem                                  # non selezionata: invariata
            else:
                try:
                    new = apply_schema(stem, self.schema.currentText(), self.start.value() + k,
                                       self.digits.value(), self.split_numbers.isChecked())
                    if post:
                        new = self._post(new)
                except ValueError as e:
                    new, err = stem, str(e)
                k += 1
            item = self.table.item(i, 1)
            item.setText(new)
            f = item.font()
            f.setItalic(i in self._manual)
            item.setFont(f)
            self._schema_err[i] = err
        self.table.blockSignals(False)
        self._check()

    def eventFilter(self, obj, ev):
        # click (senza tasti) sull'unica riga selezionata: la deseleziona
        if obj is self.table.viewport() and ev.type() == QEvent.Type.MouseButtonPress \
                and ev.button() == Qt.MouseButton.LeftButton and not ev.modifiers():
            row = self.table.rowAt(int(ev.position().y()))
            if row >= 0 and {i.row() for i in self.table.selectedIndexes()} == {row}:
                self.table.clearSelection()
                return True
        return super().eventFilter(obj, ev)

    def _on_selection(self):
        """Una sola riga selezionata: lo Schema mostra il suo nome, da riscrivere direttamente.
        Cambiando selezione, il nome scritto resta come correzione a mano e torna lo schema di prima."""
        rows = {i.row() for i in self.table.selectedIndexes()}
        one = rows.pop() if len(rows) == 1 else None
        if self._single_row is not None and one != self._single_row:
            r, text = self._single_row, self.schema.currentText()
            if text.strip() and text != split_name(self.paths[r])[0]:
                self._manual[r] = text
            self._single_row = None
            self.schema.setEditText(self._multi_schema)
        if one is not None and self._single_row is None:
            self._multi_schema = self.schema.currentText()
            self._single_row = one
            self.schema.setEditText(self._manual.pop(one, split_name(self.paths[one])[0]))
            self.schema.lineEdit().selectAll()
        self._fill()

    def _edited(self, item):
        """Correzione a mano: resta fissa; svuotando la cella torna il nome automatico."""
        if item.column() == 1:
            if item.text().strip():
                self._manual[item.row()] = item.text()
            else:
                self._manual.pop(item.row(), None)
            self._fill()

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
            note = f"⚠ {problem}" if problem else (ext or "cartella") + ("" if changed else " · invariato")
            self.table.item(i, 2).setText(note + ("  ✎ a mano" if i in self._manual else ""))
        self.table.blockSignals(False)
        n = len(self._targets)
        self.b_ok.setText(f"Rinomina {n} di {len(self.paths)}" if len(self.paths) > 1 else "Rinomina")
        self.b_ok.setEnabled(n > 0)

    def renames(self):
        """[(vecchio percorso, nuovo percorso)] delle sole righe valide e cambiate."""
        return list(self._targets)

    # --- schemi recenti (salvati tra un avvio e l'altro) ---

    def _recent(self):
        return QSettings(*self.SETTINGS).value("rinomina/schemi_recenti", [], type=list)

    def accept(self):
        schema = self.schema.currentText()
        if "<" in schema:   # solo schemi veri, non un nome scritto per un singolo fumetto
            recent = [schema] + [x for x in self._recent() if x != schema]
            QSettings(*self.SETTINGS).setValue("rinomina/schemi_recenti", recent[:self.RECENT_MAX])
        super().accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F1:
            self.show_help()
        else:
            super().keyPressEvent(e)

    def show_help(self):
        self.help_dialog().exec()

    def help_dialog(self):
        """Aiuto in un'area che scorre: il testo è lungo."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Rinomina: aiuto")
        fit_dialog_to_screen(dlg, 760, 680, min_w=420, min_h=320)
        v = QVBoxLayout(dlg)
        dlg.text = QTextBrowser()
        dlg.text.setHtml(RENAME_HELP)
        v.addWidget(dlg.text, 1)
        b = QPushButton("Chiudi")
        set_variant(b, "info")
        b.clicked.connect(dlg.accept)
        v.addWidget(b, alignment=Qt.AlignmentFlag.AlignRight)
        return dlg

RENAME_HELP = """
<h3>Come si rinomina</h3>
<ol>
<li><b>Schema</b>: scrivi il formato del nuovo nome (nel menu a tendina: gli schemi usati di recente e tre schemi pronti).</li>
<li><b>Cerca / Sostituisci</b> e i tasti <b>_ → spazio</b>, <b>Iniziali Maiuscole</b>: sistemano i nomi.</li>
<li><b>A mano</b>: doppio click su una cella di <i>Nuovo nome</i> per correggere un caso particolare.</li>
<li><b>Rinomina</b>: cambia il nome dei soli file validi. Le righe rosse e quelle invariate non vengono toccate.</li>
</ol>
<p>La colonna <i>Nuovo nome</i> è sempre aggiornata, mentre scrivi: mostra esattamente il nome finale.
Si calcola in quest'ordine: schema → Cerca/Sostituisci → <i>_ → spazio</i> → <i>Iniziali Maiuscole</i>
(gli spazi doppi vengono tolti).</p>

<h3>Segnaposto dello schema</h3>
<table cellspacing="4">
<tr><td><b>&lt;nome&gt;</b></td><td>il nome attuale</td></tr>
<tr><td><b>&lt;num&gt;</b></td><td>il primo numero già presente nel nome, con le <i>Cifre</i> scelte
 (<code>naruto_12</code> → <code>012</code>). Tiene il numero vero: ideale per numerazioni sparse.</td></tr>
<tr><td><b>&lt;n&gt;</b></td><td>un numero progressivo, nell'ordine della tabella, da <i>Parti da</i>, con le <i>Cifre</i> scelte</td></tr>
<tr><td><b>&lt;parte1&gt;</b>, <b>&lt;parte2&gt;</b>…</td><td>i pezzi del nome. Si dividono ai trattini con spazi o <code>_</code>
 attorno e, con <i>Dividi anche ai numeri</i>, ai numeri staccati (anche con <code>#</code> davanti):
 <code>Titolo 43 Sottotitolo</code> → parte1 <code>Titolo</code>, parte2 <code>43</code>, parte3 <code>Sottotitolo</code>.
 Una parte fatta solo di cifre prende le <i>Cifre</i> scelte (<code>43</code> → <code>043</code>).
 Non dividono il trattino dentro una parola (<code>Spider-Man</code>) e il numero attaccato (<code>X-Men2</code>).
 Per nomi come <i>Fantastici 4</i> togli la spunta a <i>Dividi anche ai numeri</i>.</td></tr>
<tr><td><b>&lt;…:cifre&gt;</b></td><td>cifre solo per quel segnaposto, al posto del campo <i>Cifre</i>:
 <code>&lt;num:4&gt;</code> → <code>0045</code>, <code>&lt;parte4:1&gt;</code> → <code>2</code> (<code>:1</code> = numero così com'è)</td></tr>
</table>
<p>Tutto il resto dello schema è testo fisso. Esempi:<br>
<code>Naruto - #&lt;num&gt;</code> → <code>Naruto - #012</code><br>
<code>&lt;parte1&gt; #&lt;parte2&gt; - &lt;parte3&gt;</code> → <code>Titolo #043 - Sottotitolo</code><br>
<code>Dylan Dog &lt;n&gt;</code> → <code>Dylan Dog 001</code>, <code>Dylan Dog 002</code>…</p>

<h3>Come conviene chiamare i file</h3>
<ol>
<li>La <b>testata per prima</b>, scritta sempre uguale: i numeri della stessa serie restano vicini.</li>
<li>Il <b>numero con # e sempre 3 cifre</b> (<code>#007</code>, <code>#045</code>): si legge subito, si ordina bene
 ovunque e Komga, Kavita e YACReader lo riconoscono da soli.</li>
<li>Il <b>titolo della storia dopo " - "</b>, solo per le testate che lo hanno.</li>
<li>L'<b>anno tra parentesi in fondo</b>, solo se serve distinguere serie con lo stesso nome.</li>
<li><b>Niente etichette</b> come <code>(Digital)</code> o <code>(Pyrate-…)</code>.</li>
</ol>
<table cellspacing="4">
<tr><td>Serie</td><td><code>Absolute Batman #024.cbz</code><br>
 schema <code>&lt;parte1&gt; #&lt;parte2&gt;</code></td></tr>
<tr><td>Una storia per numero</td><td><code>Dylan Dog #045 - L'alba dei morti viventi.cbz</code><br>
 schema <code>&lt;parte1&gt; #&lt;parte2&gt; - &lt;parte3&gt;</code>; storia che continua: <code>(2)</code>, <code>(3)</code> in fondo;
 più storie nello stesso numero: <code>La grande rapina + Il ponte</code></td></tr>
<tr><td>Contenitore, storie a volumi</td><td><code>Romanzi a Fumetti #003 - Il Corvo (Vol. 1).cbz</code><br>
 <code>Romanzi a Fumetti #008 - Il Corvo (Vol. 2).cbz</code><br>
 schema <code>&lt;parte1&gt; #&lt;parte2&gt; - &lt;parte3&gt; (Vol. &lt;parte4:1&gt;)</code>: i file restano in ordine di uscita
 e cercando il titolo della storia trovi tutti i volumi.</td></tr>
</table>
<p>I tre schemi sono già pronti nel menu a tendina dello Schema.</p>

<h3>Cerca / Sostituisci</h3>
<p>Il risultato si vede subito nella colonna. Jolly in <i>Cerca</i>:
<b>?</b> = un carattere qualsiasi, <b>*</b> = qualsiasi testo. Esempi:<br>
<code>(*)</code> con <i>Sostituisci</i> vuoto → toglie ogni gruppo tra parentesi
 (<code>Titolo (2019) (Digital)</code> → <code>Titolo</code>)<br>
<code>Vol*</code> → sostituisce da "Vol" fino alla fine del nome<br>
<code>Cap ??</code> → trova "Cap 12", "Cap 07"…<br>
Senza <i>Maiuscole/minuscole</i> spuntato, "naruto" trova anche "NARUTO".</p>
<p>In <i>Sostituisci con</i>, <b>*</b> e <b>?</b> rimettono il testo trovato dai jolly di <i>Cerca</i>,
nello stesso ordine (il 1° con il 1°, il 2° con il 2°…):<br>
<code>[*]</code> → <code>*</code> : <code>Titolo [ testo ] 2</code> → <code>Titolo testo 2</code> (toglie solo le parentesi)<br>
<code>(*)</code> → <code>- *</code> : <code>Zagor (Il ritorno)</code> → <code>Zagor - Il ritorno</code><br>
<code>Cap ??</code> → <code>Capitolo ??</code> : <code>Cap 07</code> → <code>Capitolo 07</code><br>
<code>* - *</code> → <code>* (*)</code> : <code>Tex - Speciale</code> → <code>Tex (Speciale)</code></p>

<h3>Tasti e righe selezionate</h3>
<ul>
<li><b>_ → spazio</b> e <b>Iniziali Maiuscole</b> sono interruttori: acceso/spento. <i>Iniziali Maiuscole</i>
 non abbassa le altre lettere (<code>DC</code> resta <code>DC</code>, <code>l'alba</code> diventa <code>L'alba</code>).</li>
<li>Se selezioni delle righe, si rinominano <b>solo quelle</b> (schema, Cerca/Sostituisci e tasti);
 le altre restano invariate e il progressivo &lt;n&gt; conta solo le selezionate. Senza selezione si lavora su tutte.</li>
<li>Con <b>una sola riga selezionata</b>, lo Schema mostra il suo nome: scrivi direttamente quello nuovo.
 Selezionando altro, il nome scritto resta su quella riga ("✎ a mano") e torna lo schema di prima.</li>
<li>Selezione: <b>click</b> seleziona solo quella riga (un altro click sulla stessa la deseleziona);
 <b>trascinando</b> o con <b>Shift+click</b> selezioni un intervallo; <b>Ctrl+click</b> aggiunge o toglie una riga,
 <b>Ctrl+trascina</b> aggiunge o toglie un intervallo (partendo da una riga selezionata, le toglie).
 <i>Tutte</i> / <i>Nessuna</i>, o Ctrl+A.</li>
<li>Le <b>correzioni a mano</b> (in corsivo, "✎ a mano") restano fisse anche se cambi schema o tasti.
 Svuota la cella per tornare al nome automatico.</li>
</ul>

<h3>Righe rosse</h3>
<p>Non vengono rinominate: <i>numero non trovato</i>, <i>parte mancante</i>, <i>nome vuoto</i>,
<i>esiste già</i> (un altro file ha già quel nome), <i>nome ripetuto</i> (due righe con lo stesso nome).
Correggile a mano nella cella.</p>

<h3>Sicurezza</h3>
<p>Si cambia solo il nome: il contenuto del fumetto non viene toccato e l'estensione resta la stessa.
Un file esistente non viene mai sovrascritto. I caratteri <code>\\ / : * ? " &lt; &gt; |</code> diventano <code>_</code>.
Dopo una rinomina, il pulsante <b>Annulla rinomina</b> nella finestra principale rimette i nomi di prima.</p>
<p><b>Come aprire la rinomina:</b> doppio click sul nome nella card, tasto <b>F2</b> o pulsante
<b>Rinomina</b>. In questa finestra, <b>F1</b> apre questo aiuto.</p>
"""

class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")

    def wheelEvent(self, e):
        e.ignore()
