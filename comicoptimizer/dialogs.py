"""Finestre di dialogo e widget generici (log, interruzione, unione)."""

import os

from PyQt6.QtCore import QEvent, QSettings, Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from .logsetup import _qt_log_handler, log
from .style import set_variant
from .online import AuthorSearchWorker, clean_title, result_label
from .utils import (
    _WORD,
    FIELD_TAGS,
    FREE_FIELDS,
    ROLE_TAGS,
    apply_schema,
    capitalize_words,
    clean_filename,
    get_natural_sort_key,
    merge_name_hint,
    name_spans,
    new_rule,
    rename_problem,
    rule_units,
    schema_roles,
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

_SEARCHES = set()   # ricerche online in corso (il thread deve vivere fino alla fine)

_U = QTextCharFormat.UnderlineStyle
# ruolo marcabile → (nome, colore, sottolineatura): colori Okabe-Ito, distinguibili anche dai
# daltonici; la sottolineatura diversa è il secondo segno
MARK_ROLES = {"titolo": ("Titolo", "#E69F00", _U.SingleUnderline),
              "num": ("Numero", "#56B4E9", _U.DashUnderline),
              "anno": ("Anno", "#009E73", _U.DashDotLine),
              "autore": ("Autore", "#F0E442", _U.WaveUnderline),
              "editore": ("Editore", "#CC79A7", _U.DashDotDotLine),
              "edizione": ("Edizione", "#D55E00", _U.SingleUnderline),   # + corsivo
              "lingua": ("Lingua", "#3D9BE0", _U.SingleUnderline)}       # + grassetto
_P_COLORS = ("#e8e8e8", "#b8dcff", "#c8f0c8", "#ffd8b0", "#e8c8ff")


def _role_style(role):
    """(nome, colore, sottolineatura) di un ruolo; p1, p2… hanno tinte chiare e puntini."""
    if role in MARK_ROLES:
        return MARK_ROLES[role]
    n = int(role[1:])
    return f"P{n}", _P_COLORS[(n - 1) % len(_P_COLORS)], _U.DotLine


def _role_order(role):
    return (0, list(MARK_ROLES).index(role)) if role in MARK_ROLES else (1, int(role[1:]))


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
    # l'autore dove è uno solo per tutta la serie; non per Bonelli e contenitori (cambia a ogni numero)
    PRESETS = [("<p1> (<aut>) Vol. <p2:2>", "Manga a volumi"),
               ("<p1> (<aut>) Ch. <p2>", "Manga a capitoli"),
               ("<p1> (<aut>) (<pub>) Vol. <p2:2> [<lang>]",
                "Manga, edizione completa (editore e lingua)"),
               ("<p1> (<anno>) (<aut>) #<p2>", "Comics americani"),
               ("<p1> (<anno>) (<aut>) #<p2> - <p3>", "Comics americani con sottotitolo"),
               ("<p1> #<p2> - <p3>", "Una storia per numero (Bonelli…)"),
               ("<p1> #<p2> - <p3> (Vol. <p4:1>)", "Contenitore con storie a volumi")]

    def __init__(self, paths, parent=None, on_rename=None):
        super().__init__(parent)
        self.setWindowTitle("Rinomina")
        # on_rename(coppie) rinomina sul disco e restituisce le coppie riuscite: la finestra
        # resta aperta per altri passaggi. Senza, "Rinomina" chiude e restituisce le coppie.
        self.on_rename = on_rename
        self.done_pairs = []         # tutte le rinomine fatte da questa finestra (per annullarle)
        self._search = None
        fit_dialog_to_screen(self, 920, 680, min_w=580, min_h=440)
        self.paths = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        self._schema_err = [None] * len(self.paths)
        self._manual = {}            # riga → nome scritto a mano (fisso)
        self._single_row = None      # riga selezionata da sola: lo Schema mostra il suo nome
        self._multi_schema = ""      # lo schema messo da parte nel frattempo
        self._targets = []
        self._rule = None            # marcatura manuale dei pezzi (utils.new_rule); None = automatico
        self._shown_stem, self._shown_units = "", []
        l = QVBoxLayout(self)

        # nome della riga corrente: col tasto destro si dice il ruolo dei pezzi, per tutto il gruppo
        self.name_box = QTextEdit()
        self.name_box.setReadOnly(True)
        self.name_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                              | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.name_box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.name_box.customContextMenuRequested.connect(self._name_menu)
        self.name_box.setFixedHeight(self.name_box.fontMetrics().lineSpacing() * 2 + 14)
        # fondo scuro fisso: i colori dei ruoli (anche il giallo e le tinte chiare dei P) restano leggibili
        self.name_box.setStyleSheet("QTextEdit { background: #1b1b1f; border: 1px solid #444; "
                                    "border-radius: 6px; font-size: 14px; padding: 2px 4px; }")
        self.name_box.setToolTip("Seleziona un pezzo del nome e premi il tasto destro per dirne il ruolo\n"
                                 "(Titolo, Numero, Anno, P1…): la regola vale per tutti i file della finestra")
        l.addWidget(self.name_box)
        row = QHBoxLayout()
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("color: #aaa; font-size: 11px;")
        self.b_reset = QPushButton("Azzera marcature")
        self.b_reset.setProperty("sz", "small")
        set_variant(self.b_reset, "muted")
        self.b_reset.setAutoDefault(False)
        self.b_reset.setToolTip("Torna alla divisione automatica dei pezzi")
        self.b_reset.clicked.connect(self.reset_marks)
        row.addWidget(self.legend, 1)
        row.addWidget(self.b_reset)
        l.addLayout(row)

        row = QHBoxLayout()
        single = len(self.paths) == 1
        self.schema = QComboBox()
        self.schema.setEditable(True)
        self.schema.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        recent = self._recent()
        self.schema.addItems(recent)
        presets = [(s, d) for s, d in self.PRESETS if s not in recent]
        if recent and presets:
            self.schema.insertSeparator(len(recent))
        for s, d in presets:   # nel menu: tipo di fumetto · schema; nel campo entra solo lo schema
            self.schema.addItem(f"{d}  ·  {s}", s)
        self.schema.activated.connect(
            lambda i: self.schema.setEditText(self.schema.itemData(i) or self.schema.itemText(i)))
        self.schema.setEditText(split_name(self.paths[0])[0] if single else "<nome>")
        self.schema.setToolTip("Nel menu a tendina: gli schemi usati di recente e sette schemi pronti\n"
                               "(manga a volumi e a capitoli, comics americani, storie, contenitori)")
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
        hint = QLabel("Segnaposto: <nome> nome attuale · <tit> titolo · <num> numero già nel nome · "
                      "<n> progressivo · <anno> anno nel nome · <p1>, <p2>… pezzi del nome · "
                      "<aut> <pub> <edz> <lang> dalle caselle qui sotto")
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

        # campi che non si ricavano dal nome: si usano con <aut>, <pub>, <edz>, <lang>
        row = QHBoxLayout()
        self.fields = {}
        examples = {"autore": "Kentaro Miura", "editore": "Panini", "edizione": "Ultimate", "lingua": "ITA"}
        for key in FREE_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(f"es. {examples[key]}")
            edit.setToolTip(f"Si inserisce nello Schema con <{FIELD_TAGS[key]}>")
            if key == "lingua":
                edit.setMaximumWidth(90)
            row.addWidget(QLabel(key.capitalize() + ":"))
            row.addWidget(edit, 0 if key == "lingua" else 1)
            self.fields[key] = edit
            if key == "autore":
                self.b_search = QPushButton("🔍 Cerca")
                self.b_search.setProperty("sz", "small")
                set_variant(self.b_search, "info")
                self.b_search.setAutoDefault(False)
                self.b_search.setToolTip("Cerca l'autore online (Wikidata, AniList) dal titolo del fumetto.\n"
                                         "Viene inviato solo il titolo, mai i file.")
                self.b_search.clicked.connect(self.search_author)
                row.addWidget(self.b_search)
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
        b_can = QPushButton("Chiudi" if on_rename else "Annulla")
        set_variant(b_can, "danger")
        b_can.setAutoDefault(False)
        b_can.clicked.connect(self.reject)
        self.status = QLabel()
        self.status.setStyleSheet("color: #00e5ff; font-weight: bold;")
        b_help = QPushButton("? Aiuto")
        set_variant(b_help, "info")
        b_help.setToolTip("Come si rinomina (F1)")
        b_help.setAutoDefault(False)
        b_help.clicked.connect(self.show_help)
        self.b_ok = QPushButton("Rinomina")
        set_variant(self.b_ok, "success")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self._rename)
        btns.addWidget(b_can)
        btns.addWidget(b_help)
        btns.addSpacing(12)
        btns.addWidget(self.status, 1)
        btns.addWidget(self.b_ok)
        l.addLayout(btns)

        self.schema.editTextChanged.connect(self._fill)
        self.schema.lineEdit().returnPressed.connect(self._rename)
        self.split_numbers.toggled.connect(self._split_changed)       # prima di _fill
        for sig in (self.digits.valueChanged, self.start.valueChanged, self.split_numbers.toggled,
                    self.b_us.toggled, self.b_cap.toggled, self.find.textChanged,
                    self.repl.textChanged, self.case.toggled,
                    *(e.textChanged for e in self.fields.values())):
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
                                       self.digits.value(), self.split_numbers.isChecked(),
                                       {key: e.text() for key, e in self.fields.items()}, self._rule)
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
        self._show_name()

    # --- marcatura manuale dei pezzi del nome ---

    def _shown_row(self):
        """La riga mostrata nel riquadro: l'unica selezionata, o l'ultima cliccata."""
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) == 1:
            return rows.pop()
        return max(self.table.currentRow(), 0)

    def _show_name(self):
        """Il nome nel riquadro: grigio scuro i separatori, grigio i pezzi, a colori i marcati."""
        stem = split_name(self.paths[self._shown_row()])[0]
        if self._rule:
            units = rule_units(stem, self._rule)
        else:
            units = [((i, 0), a, b) for i, (a, b) in
                     enumerate(name_spans(stem, self.split_numbers.isChecked()))]
        self._shown_stem, self._shown_units = stem, units
        # shortcut: posizioni Python = posizioni Qt finché il nome non ha emoji (fuori dal BMP)
        self.name_box.setPlainText(stem)
        cur = QTextCursor(self.name_box.document())

        def paint(a, b, color, ul=None, role=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if ul is not None:
                fmt.setUnderlineStyle(ul)
                fmt.setUnderlineColor(QColor(color))
                fmt.setFontItalic(role == "edizione")
                if role == "lingua":
                    fmt.setFontWeight(QFont.Weight.Bold)
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
            cur.setCharFormat(fmt)

        paint(0, len(stem), "#666")
        marks = self._rule["marks"] if self._rule else {}
        for j, (key, a, b) in enumerate(units or []):
            joined = self._rule and key in self._rule["joins"] and j + 1 < len(units)
            paint(a, units[j + 1][2] if joined else b, "#bbb")
        pos = {key: (a, b) for key, a, b in units or []}
        for role, (k1, k2) in marks.items() if units else ():
            _, color, ul = _role_style(role)
            paint(pos[k1][0], pos[k2][1], color, ul, role)
        legend = "  ".join(f'<span style="color:{_role_style(r)[1]}">■ {_role_style(r)[0]}</span> '
                           f'&lt;{ROLE_TAGS.get(r, r)}&gt;' for r in sorted(marks, key=_role_order))
        if not legend:
            legend = ("Seleziona un pezzo del nome qui sopra e premi il tasto destro per dirne il ruolo "
                      "(Titolo, Numero, P1…): la regola vale per tutti i file della finestra")
        if units is None:
            legend = ('<span style="color:#ff6b6b">⚠ questo nome ha una struttura diversa dal nome '
                      "d'esempio: qui non si marca</span> · " + legend)
        self.legend.setText(legend)
        self.b_reset.setEnabled(self._rule is not None)

    def _selection(self):
        c = self.name_box.textCursor()
        return c.selectionStart(), c.selectionEnd()

    def _picked(self):
        """Le unità intere toccate dalla selezione nel riquadro, comprese quelle unite."""
        s, e = self._selection()
        units = self._shown_units or []
        hit = [j for j, (_, a, b) in enumerate(units) if a < e and b > s]
        if s == e or not hit:
            return []
        lo, hi = hit[0], hit[-1]
        joins = self._rule["joins"] if self._rule else set()
        while lo > 0 and units[lo - 1][0] in joins:
            lo -= 1
        while hi < len(units) - 1 and units[hi][0] in joins:
            hi += 1
        return units[lo:hi + 1]

    def _cut_info(self, picked):
        """(pezzo, lato, k) se la selezione prende le prime o le ultime parole di un pezzo non ancora
        diviso (non tutte): Dividi ne fa un'unità a sé. Altrimenti None."""
        if len(picked) != 1 or (self._rule and picked[0][0][0] in self._rule["cuts"]):
            return None
        (i, _), a, b = picked[0]
        s, e = self._selection()
        words = [(a + m.start(), a + m.end()) for m in _WORD.finditer(self._shown_stem[a:b])]
        hit = [j for j, (x, y) in enumerate(words) if x < e and y > s]
        if not hit or len(hit) == len(words):
            return None
        if hit[0] == 0:
            return i, "start", len(hit)
        if hit[-1] == len(words) - 1:
            return i, "end", len(hit)
        return None

    def _next_p(self):
        used = {int(r[1:]) for r in (self._rule["marks"] if self._rule else {}) if r not in MARK_ROLES}
        n = 1
        while n in used:
            n += 1
        return n

    def _name_menu(self, pos):
        menu = QMenu(self)

        def add(text, fn=None, enabled=True):
            act = menu.addAction(text)
            act.setEnabled(enabled and fn is not None)
            if fn:
                act.triggered.connect(lambda _=False: fn())

        picked = self._picked()
        if picked:
            k1, k2 = picked[0][0], picked[-1][0]
            for role, (label, _, _) in MARK_ROLES.items():
                add(f"{label}   <{ROLE_TAGS[role]}>", lambda r=role: self.mark(r, k1, k2))
            n = self._next_p()
            add(f"P{n}   <p{n}>   (il successivo libero)", lambda: self.mark(f"p{n}", k1, k2))
            add("P…   (scegli il numero)", lambda: self._ask_p(k1, k2))
            menu.addSeparator()
            marks = self._rule["marks"] if self._rule else {}
            add("Ignora (togli il ruolo)", lambda: self.unmark(k1, k2),
                any(a <= k2 and k1 <= b for a, b in marks.values()))
            add("Unisci in un solo pezzo", lambda: self.join(picked), len(picked) > 1)
            cut = self._cut_info(picked)
            add("Dividi: queste parole diventano un pezzo a sé", lambda: self.cut(*cut), cut is not None)
        elif self._shown_units is None:
            add("Struttura diversa dal nome d'esempio: qui non si marca")
        else:
            add("Seleziona prima un pezzo del nome")
        menu.addSeparator()
        add("Azzera marcature", self.reset_marks, self._rule is not None)
        menu.exec(self.name_box.mapToGlobal(pos))

    def _ask_p(self, k1, k2):
        n, ok = QInputDialog.getInt(self, "Pezzo", "Numero del pezzo (P1, P2…):", self._next_p(), 1, 99)
        if ok:
            self.mark(f"p{n}", k1, k2)

    def _ensure_rule(self):
        if self._rule is None:
            self._rule = new_rule(self._shown_stem, self.split_numbers.isChecked())
        return self._rule

    def mark(self, role, k1, k2):
        """Dà il ruolo alle unità k1…k2 (un ruolo, un pezzo) e mette il segnaposto nello Schema."""
        marks = self._ensure_rule()["marks"]
        for r, (a, b) in list(marks.items()):
            if r == role or (a <= k2 and k1 <= b):
                del marks[r]
        marks[role] = (k1, k2)
        le = self.schema.lineEdit()
        if role not in schema_roles(le.text()):
            tag = f"<{ROLE_TAGS.get(role, role)}>"
            if le.text().strip() == "<nome>":
                le.setText(tag)
            else:
                le.deselect()
                le.insert(tag)                        # alla posizione del cursore
        self._fill()

    def unmark(self, k1, k2):
        marks = self._rule["marks"]
        for r, (a, b) in list(marks.items()):
            if a <= k2 and k1 <= b:
                del marks[r]
        self._fill()

    def join(self, units):
        self._ensure_rule()["joins"].update(key for key, _, _ in units[:-1])
        self._fill()

    def cut(self, i, side, k):
        """Dividi il pezzo i: le prime/ultime k parole diventano un'unità; via le marcature su quel pezzo."""
        rule = self._ensure_rule()
        rule["cuts"][i] = (side, k)
        rule["marks"] = {r: (a, b) for r, (a, b) in rule["marks"].items() if not a[0] <= i <= b[0]}
        rule["joins"] = {key for key in rule["joins"] if key[0] != i}
        self._fill()

    def reset_marks(self):
        self._rule = None
        self._fill()

    def _split_changed(self):
        if self._rule:
            self._rule = None
            self.status.setText("Marcature azzerate: con \"Dividi anche ai numeri\" cambiano i pezzi")

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
                # con dei segnaposto (<tit>…) resta il nome già calcolato, non lo schema
                self._manual[r] = self.table.item(r, 1).text() if "<" in text else text
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

    def _save_recent(self):
        schema = self.schema.currentText()
        if "<" in schema:   # solo schemi veri, non un nome scritto per un singolo fumetto
            recent = [schema] + [x for x in self._recent() if x != schema]
            QSettings(*self.SETTINGS).setValue("rinomina/schemi_recenti", recent[:self.RECENT_MAX])

    def accept(self):
        self._save_recent()
        super().accept()

    def _rename(self):
        """Rinomina. Con on_rename la finestra resta aperta e riparte dai nomi nuovi."""
        pairs = self.renames()
        if not pairs:
            return
        if self.on_rename is None:
            self.accept()
            return
        self._save_recent()
        done = self.on_rename(pairs)
        self.done_pairs += done
        new_of = dict(done)
        self.table.clearSelection()                   # esce anche dal "nome singolo"
        for i, p in enumerate(self.paths):
            if p in new_of:
                self.paths[i] = new_of[p]
                self.table.item(i, 0).setText(os.path.basename(new_of[p]))
                self._manual.pop(i, None)
        # si riparte dai nomi nuovi: tutto "invariato"; le caselle Autore/Editore/… restano
        for w in (self.find, self.repl):
            w.blockSignals(True)
            w.clear()
            w.blockSignals(False)
        for b in (self.b_us, self.b_cap):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._rule = None                             # i nomi sono cambiati: si rimarca da capo
        self.schema.setEditText("<nome>")
        self._fill()
        miss = len(pairs) - len(done)
        self.status.setText(f"✓ {len(done)} rinominati" + (f" · {miss} non riusciti" if miss else ""))

    # --- ricerca dell'autore online ---

    def search_author(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or [0]
        title, ok = QInputDialog.getText(
            self, "Cerca autore", "Titolo da cercare (viene inviato solo questo testo a Wikidata e AniList):",
            text=clean_title(self.paths[rows[0]]))
        if not ok or not title.strip():
            return
        self.b_search.setEnabled(False)
        self.b_search.setText("Ricerca…")
        self._search = AuthorSearchWorker(title.strip())
        self._search.found.connect(self._author_found)
        self._search.failed.connect(self._author_failed)
        _SEARCHES.add(self._search)                   # vive fino alla fine, anche se la finestra si chiude
        self._search.finished.connect(lambda w=self._search: _SEARCHES.discard(w))
        self._search.start()

    def _search_done(self):
        self.b_search.setEnabled(True)
        self.b_search.setText("🔍 Cerca")

    def _author_failed(self, err):
        self._search_done()
        QMessageBox.warning(self, "Cerca autore", f"Ricerca non riuscita (connessione?):\n{err}")

    def _author_found(self, results):
        self._search_done()
        if not results:
            QMessageBox.information(self, "Cerca autore", "Nessun risultato: prova con il titolo originale "
                                    "o in inglese, oppure scrivi l'autore a mano.")
            return
        if len(results) == 1:
            pick = results[0]
        else:
            labels = [result_label(r) for r in results]
            text, ok = QInputDialog.getItem(self, "Cerca autore", "Scegli il fumetto giusto:", labels, 0, False)
            if not ok:
                return
            pick = results[labels.index(text)]
        self.fields["autore"].setText(", ".join(pick["authors"]))

    def done(self, r):
        # finestra chiusa con una ricerca in corso: il risultato non deve più arrivare qui
        if self._search and self._search.isRunning():
            self._search.found.disconnect()
            self._search.failed.disconnect()
        super().done(r)

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
<li><b>Schema</b>: scrivi il formato del nuovo nome (nel menu a tendina: gli schemi usati di recente e sette schemi pronti).</li>
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
<tr><td><b>&lt;tit&gt;</b></td><td>il titolo: il pezzo marcato come <i>Titolo</i> (vedi sotto) o, senza marcature,
 il primo pezzo del nome (come &lt;p1&gt;)</td></tr>
<tr><td><b>&lt;num&gt;</b></td><td>il primo numero già presente nel nome, con le <i>Cifre</i> scelte
 (<code>naruto_12</code> → <code>012</code>). Tiene il numero vero: ideale per numerazioni sparse.</td></tr>
<tr><td><b>&lt;anno&gt;</b></td><td>l'anno a 4 cifre presente nel nome, preferito quello tra parentesi
 (<code>Absolute Batman 024 (2024) (Digital)</code> → <code>2024</code>)</td></tr>
<tr><td><b>&lt;aut&gt;</b>, <b>&lt;pub&gt;</b>,<br><b>&lt;edz&gt;</b>, <b>&lt;lang&gt;</b></td>
 <td>il testo scritto nelle caselle <i>Autore</i>, <i>Editore</i>, <i>Edizione</i>, <i>Lingua</i> (uguale per tutti i fumetti
 della finestra). Se la casella è vuota la riga diventa rossa.</td></tr>
<tr><td><b>&lt;n&gt;</b></td><td>un numero progressivo, nell'ordine della tabella, da <i>Parti da</i>, con le <i>Cifre</i> scelte</td></tr>
<tr><td><b>&lt;p1&gt;</b>, <b>&lt;p2&gt;</b>…</td><td>i pezzi del nome. Si dividono ai trattini con spazi o <code>_</code>
 attorno e, con <i>Dividi anche ai numeri</i>, ai numeri staccati (anche con <code>#</code> davanti o tra quadre):
 <code>Titolo 43 Sottotitolo</code> o <code>Titolo [43] Sottotitolo</code> → p1 <code>Titolo</code>, p2 <code>43</code>,
 p3 <code>Sottotitolo</code>. I numeri tra parentesi tonde, come <code>(2016)</code>, non dividono (sono anni o etichette).
 Una parte fatta solo di cifre prende le <i>Cifre</i> scelte (<code>43</code> → <code>043</code>).
 Non dividono il trattino dentro una parola (<code>Spider-Man</code>) e il numero attaccato (<code>X-Men2</code>).
 Per nomi come <i>Fantastici 4</i> togli la spunta a <i>Dividi anche ai numeri</i>.</td></tr>
<tr><td colspan="2"><i>Valgono anche i nomi lunghi: &lt;titolo&gt;, &lt;parte1&gt;, &lt;autore&gt;, &lt;editore&gt;,
 &lt;edizione&gt;, &lt;lingua&gt;.</i></td></tr>
<tr><td><b>&lt;…:cifre&gt;</b></td><td>cifre solo per quel segnaposto, al posto del campo <i>Cifre</i>:
 <code>&lt;num:4&gt;</code> → <code>0045</code>, <code>&lt;p4:1&gt;</code> → <code>2</code> (<code>:1</code> = numero così com'è)</td></tr>
</table>
<p>Tutto il resto dello schema è testo fisso. Esempi:<br>
<code>Naruto - #&lt;num&gt;</code> → <code>Naruto - #012</code><br>
<code>&lt;p1&gt; #&lt;p2&gt; - &lt;p3&gt;</code> → <code>Titolo #043 - Sottotitolo</code><br>
<code>Dylan Dog &lt;n&gt;</code> → <code>Dylan Dog 001</code>, <code>Dylan Dog 002</code>…</p>

<h3>Marcare i pezzi del nome col mouse</h3>
<p>Quando la divisione automatica non va bene, dici tu quali pezzi sono quali. Nel riquadro in alto c'è il nome
del fumetto selezionato (o dell'ultimo cliccato): <b>selezionalo col mouse</b> e premi il <b>tasto destro</b>.
La selezione prende sempre pezzi interi. Nel menu:</p>
<ul>
<li><b>Titolo</b> &lt;tit&gt;, <b>Numero</b> &lt;num&gt;, <b>Anno</b> &lt;anno&gt;, <b>Autore</b> &lt;aut&gt;,
 <b>Editore</b> &lt;pub&gt;, <b>Edizione</b> &lt;edz&gt;, <b>Lingua</b> &lt;lang&gt;, oppure <b>P1, P2…</b>
 (&lt;p1&gt;, &lt;p2&gt;…: il successivo libero, o il numero che scegli);</li>
<li><b>Ignora</b>: toglie il ruolo; <b>Unisci</b>: più pezzi diventano uno solo;
 <b>Dividi</b>: le prime o le ultime parole selezionate di un pezzo diventano un pezzo a sé;</li>
<li><b>Azzera marcature</b> (anche col pulsante): si torna alla divisione automatica.</li>
</ul>
<p>Il segnaposto entra nello <b>Schema</b> dove c'è il cursore (al posto di <code>&lt;nome&gt;</code> se lo schema è
solo quello): poi lo sposti o lo cancelli come vuoi. Ogni ruolo ha il suo colore e la sua sottolineatura;
la legenda sotto il riquadro li ricorda. Il testo grigio è ignorato.</p>
<p>La marcatura è una <b>regola per tutto il gruppo</b>: vale per la posizione del pezzo ("il terzo pezzo"), non per
le lettere, quindi funziona anche con titoli di lunghezza diversa. Esempio:</p>
<ol>
<li>nome: <code>Dylan Dog 001 - L'alba dei morti viventi (1986)</code>;</li>
<li>selezioni <code>Dylan Dog</code> → <i>Titolo</i>; <code>001</code> → <i>Numero</i>;</li>
<li>selezioni <code>(1986)</code> → <i>Dividi</i>, poi di nuovo → <i>Anno</i>; <code>L'alba…</code> → <i>P3</i>;</li>
<li>schema <code>&lt;tit&gt; #&lt;num&gt; - &lt;p3&gt; (&lt;anno&gt;)</code>: anche
 <code>Dylan Dog 012 - Il ritorno del mostro (1987)</code> diventa <code>Dylan Dog #012 - Il ritorno del mostro (1987)</code>.</li>
</ol>
<p>Un file con una <b>struttura diversa</b> (pezzi in più o in meno, numeri dove nell'esempio c'è testo), come
<code>Dylan Dog Speciale 4 - Mostri - 2 (1990)</code>, resta rosso con "⚠ schema non applicabile" e non viene
rinominato. Per Autore, Editore, Edizione e Lingua: se il pezzo marcato c'è vince il nome del file, altrimenti
si usa la casella sotto (se è compilata). Le parentesi attorno al pezzo si tolgono: <code>(1986)</code> → <code>1986</code>.</p>
<p>Senza marcature tutto funziona come prima; con delle marcature, i segnaposto dei ruoli non marcati restano
automatici. Cambiando righe selezionate le marcature restano; cambiando <i>Dividi anche ai numeri</i>
(i pezzi cambiano) e dopo <i>Rinomina</i> si azzerano.</p>

<h3>Come conviene chiamare i file</h3>
<p>Nomi che i lettori di fumetti (Komga, Kavita, YACReader) e i programmi di catalogazione
(ComicTagger, Mylar) riconoscono da soli, e che si ordinano bene ovunque:</p>
<table cellspacing="4">
<tr><td>Manga a volumi</td><td><code>Berserk (Kentaro Miura) Vol. 03.cbz</code> · schema <code>&lt;p1&gt; (&lt;aut&gt;) Vol. &lt;p2:2&gt;</code><br>
 completo: <code>Berserk (Kentaro Miura) (Panini) Vol. 03 [ITA]</code> · <code>&lt;p1&gt; (&lt;aut&gt;) (&lt;pub&gt;) Vol. &lt;p2:2&gt; [&lt;lang&gt;]</code><br>
 niente <code>#</code> con i volumi: per i lettori <code>#</code> è il numero dell'albo o del capitolo</td></tr>
<tr><td>Manga a capitoli</td><td><code>Juujika no Rokunin (Shiryuu Nakatake) Ch. 012.cbz</code> · schema <code>&lt;p1&gt; (&lt;aut&gt;) Ch. &lt;p2&gt;</code></td></tr>
<tr><td>Comics americani</td><td><code>Batman (2016) #050 - The Wedding.cbz</code><br>
 schema <code>&lt;p1&gt; (&lt;anno&gt;) (&lt;aut&gt;) #&lt;p2&gt;</code> (<code>Batman (2016) (Tom King) #050</code>),
 con sottotitolo <code>… - &lt;p3&gt;</code><br>
 l'anno è quello di <b>inizio della serie</b> (distingue Batman 1940, 2016, 2025); il sottotitolo va dopo " - ",
 senza parentesi (le parentesi sono lette come dati, tipo anno o "Digital")</td></tr>
<tr><td>Una storia per numero</td><td><code>Zagor #045 - Il ritorno.cbz</code> · schema <code>&lt;p1&gt; #&lt;p2&gt; - &lt;p3&gt;</code><br>
 storia che continua: <code>(2)</code>, <code>(3)</code> in fondo; più storie nello stesso numero: <code>La grande rapina + Il ponte</code></td></tr>
<tr><td>Contenitori, storie a volumi</td><td><code>Romanzi a Fumetti #008 - Il Corvo (Vol. 2).cbz</code><br>
 schema <code>&lt;p1&gt; #&lt;p2&gt; - &lt;p3&gt; (Vol. &lt;p4:1&gt;)</code></td></tr>
</table>
<p>Regole comuni: la <b>testata per prima</b>, scritta sempre uguale; numeri con gli zeri davanti
(<code>#007</code>, <code>Vol. 03</code>); <b>niente etichette</b> come <code>(Digital)</code> o <code>(Pyrate-…)</code>.
I sette schemi sono pronti nel menu a tendina dello Schema; quelli con <code>&lt;aut&gt;</code> usano la casella
Autore (riempibile con 🔍 Cerca). Per Bonelli e contenitori l'autore non c'è, perché cambia da un numero all'altro.</p>
<p><b>Una cartella per serie</b>, con lo stesso nome della serie, è il miglioramento più grande:
<code>Comics/Absolute Batman (2024)/Absolute Batman (2024) #001.cbz</code>,
<code>Manga/Jujika no Rokunin/Jujika no Rokunin Vol. 01.cbz</code>. Komga e Kavita usano la cartella come serie
(copertina, ordine, "prossimo da leggere"); il nome del file ripete la serie, così si capisce anche fuori dalla cartella.</p>
<p><b>Autore, editore, edizione</b> tra parentesi dopo il titolo, la <b>lingua</b> tra quadre in fondo:
<code>Berserk (Kentaro Miura) (Panini) Vol. 03 [ITA]</code> con lo schema
<code>&lt;p1&gt; (&lt;aut&gt;) (&lt;pub&gt;) Vol. &lt;p2:2&gt; [&lt;lang&gt;]</code>.
I lettori leggono parentesi e quadre come dati e non come titolo, così la serie resta "Berserk".
Usa solo quello che distingue davvero (l'editore se hai la stessa serie da due editori, la lingua se hai più lingue).
Nella cartella della serie va bene lo stesso: <code>Manga/Berserk (Kentaro Miura)/</code>.</p>
<p>I lettori si fidano ancora di più dei dati dentro il CBZ (<b>ComicInfo.xml</b>: serie, numero, anno, titolo),
che ComicOptimizer conserva sempre.</p>

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

<h3>Cerca l'autore online</h3>
<p>Il pulsante <b>🔍 Cerca</b> accanto ad <i>Autore</i> propone il titolo ricavato dal nome del fumetto selezionato
(o del primo): senza numeri, Vol./Ch., parentesi e trattini bassi. Puoi correggerlo prima di cercare.
La ricerca usa <b>Wikidata</b> (titoli in italiano, inglese e originali: "L'attacco dei giganti", "Attack on Titan"…;
manga, comics, fumetti italiani) e <b>AniList</b> (manga). Scegli il risultato giusto e la casella si riempie.<br>
<b>Privacy:</b> viene inviato solo il titolo che confermi, mai i file né il percorso; senza premere il pulsante
l'app non usa Internet. Se non trova nulla, prova con il titolo originale o in inglese, o scrivi l'autore a mano.</p>

<h3>Più passaggi</h3>
<p>Dopo <b>Rinomina</b> la finestra resta aperta: la colonna <i>Nome attuale</i> mostra i nomi nuovi, lo Schema torna
<code>&lt;nome&gt;</code> e Cerca/Sostituisci e gli interruttori si azzerano, così continui dai nomi nuovi
(le caselle Autore, Editore, Edizione, Lingua restano). <b>Chiudi</b> o Esc per finire. <b>Annulla rinomina</b>,
nella finestra principale, annulla tutti i passaggi fatti in questa finestra.</p>

<h3>Righe rosse</h3>
<p>Non vengono rinominate: <i>numero non trovato</i>, <i>parte mancante</i>, <i>schema non applicabile</i>
(struttura diversa dalle marcature), <i>nome vuoto</i>,
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
