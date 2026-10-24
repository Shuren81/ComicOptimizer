"""Finestre di dialogo e widget generici (log, interruzione, unione)."""

import os

from PyQt6.QtCore import QEvent, QSettings, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHeaderView,
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
from . import history
from .cbz import file_status, read_comicinfo
from .online import AuthorSearchWorker, clean_title, result_label
from .utils import (
    FIELD_TAGS,
    FREE_FIELDS,
    ROLE_TAGS,
    apply_schema,
    capitalize_words,
    cbz_target,
    clean_filename,
    get_natural_sort_key,
    merge_name_hint,
    name_info,
    mark_spans,
    new_rule,
    piece_words,
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
              "sottotitolo": ("Sottotitolo", "#2EC4B6", _U.DotLine),     # + corsivo
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


class _SchemaMixin:
    """Campo Schema condiviso da Rinomina e Info: schemi recenti (salvati) e schemi pronti."""
    SETTINGS = ("Shuren", "ComicOptimizer")
    RECENT_MAX = 10
    PRESETS = [("<aut> - <tit> - Cap #<num>", "Manga"),
               ("<aut> - <tit> (<anno>) (<lang>)", "Graphic novel"),
               ("<tit> (<anno>) - #<num> - <sott> (<lang>)", "Serie americane")]

    def _make_schema(self, text):
        """Campo Schema (con i recenti e gli schemi pronti nel menu) e il pulsante 🧹."""
        self.schema = QComboBox()
        self.schema.setEditable(True)
        self.schema.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._fill_presets()
        self.schema.activated.connect(
            lambda i: self.schema.setEditText(self.schema.itemData(i) or self.schema.itemText(i)))
        self.schema.setEditText(text)
        self.schema.setToolTip("Nel menu a tendina: gli schemi usati di recente e tre schemi pronti\n"
                               "(manga, graphic novel, serie americane)")
        self.b_clear = QPushButton("🧹")
        self.b_clear.setProperty("sz", "small")
        set_variant(self.b_clear, "muted")
        self.b_clear.setAutoDefault(False)
        self.b_clear.setToolTip("Svuota gli schemi recenti: nel menu restano solo i predefiniti")
        self.b_clear.clicked.connect(self.clear_recent)
        self.b_clear.setEnabled(bool(self._recent()))

    def _recent(self):
        return QSettings(*self.SETTINGS).value("rinomina/schemi_recenti", [], type=list)

    def _fill_presets(self):
        """Menu dello Schema: i recenti, poi gli schemi pronti (tipo di fumetto · schema)."""
        text = self.schema.currentText()
        self.schema.blockSignals(True)
        self.schema.clear()
        recent = self._recent()
        self.schema.addItems(recent)
        presets = [(s, d) for s, d in self.PRESETS if s not in recent]
        if recent and presets:
            self.schema.insertSeparator(len(recent))
        for s, d in presets:   # nel campo entra solo lo schema
            self.schema.addItem(f"{d}  ·  {s}", s)
        self.schema.setEditText(text)
        self.schema.blockSignals(False)

    def clear_recent(self):
        if QMessageBox.question(self, "Schemi recenti", "Svuotare gli schemi recenti?\n"
                                "Nel menu restano solo gli schemi predefiniti.") != QMessageBox.StandardButton.Yes:
            return
        QSettings(*self.SETTINGS).remove("rinomina/schemi_recenti")
        self._fill_presets()
        self.b_clear.setEnabled(False)

    def _save_recent(self):
        schema = self.schema.currentText()
        if "<" in schema:   # solo schemi veri, non un nome scritto per un singolo fumetto
            recent = [schema] + [x for x in self._recent() if x != schema]
            QSettings(*self.SETTINGS).setValue("rinomina/schemi_recenti", recent[:self.RECENT_MAX])
            if hasattr(self, "b_clear"):
                self.b_clear.setEnabled(True)


class _AuthorSearchMixin:
    """🔍 Cerca autore online. La finestra dà self.b_search, _search_title() e _set_author(testo)."""
    _search = None

    def search_author(self):
        title, ok = QInputDialog.getText(
            self, "Cerca autore", "Titolo da cercare (viene inviato solo questo testo a Wikidata e AniList):",
            text=self._search_title())
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
        self._set_author(", ".join(pick["authors"]))

    def done(self, r):
        # finestra chiusa con una ricerca in corso: il risultato non deve più arrivare qui
        if self._search and self._search.isRunning():
            self._search.found.disconnect()
            self._search.failed.disconnect()
        super().done(r)


def _help_dialog(parent, title, html):
    """Aiuto in un'area che scorre: il testo è lungo."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    fit_dialog_to_screen(dlg, 760, 680, min_w=420, min_h=320)
    v = QVBoxLayout(dlg)
    dlg.text = QTextBrowser()
    dlg.text.setHtml(html)
    v.addWidget(dlg.text, 1)
    b = QPushButton("Chiudi")
    set_variant(b, "info")
    b.clicked.connect(dlg.accept)
    v.addWidget(b, alignment=Qt.AlignmentFlag.AlignRight)
    return dlg


class RenameDialog(_SchemaMixin, _AuthorSearchMixin, QDialog):
    """
    Rinomina uno o più fumetti. La colonna "Nuovo nome" è ricalcolata a ogni modifica:
    schema → Cerca/Sostituisci → "_ → spazio" → "Iniziali Maiuscole", sulle righe
    selezionate (o su tutte se non ce ne sono): le altre restano invariate. Le celle
    corrette a mano restano fisse; svuotandole torna il nome automatico.
    Le righe con un problema (rosse) non vengono rinominate.
    """
    def __init__(self, paths, parent=None, on_rename=None):
        super().__init__(parent)
        self.setWindowTitle("Rinomina")
        # on_rename(coppie) rinomina sul disco e restituisce le coppie riuscite: la finestra
        # resta aperta per altri passaggi. Senza, "Rinomina" chiude e restituisce le coppie.
        self.on_rename = on_rename
        self.done_pairs = []         # tutte le rinomine fatte da questa finestra (per annullarle)
        self.info_request = None     # "Info…": (percorsi, marcature, caselle, dividi ai numeri)
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
        f = self.name_box.font()
        f.setPixelSize(19)
        self.name_box.setFont(f)
        self.name_box.setFixedHeight(QFontMetrics(f).lineSpacing() * 2 + 18)
        # fondo scuro fisso: i colori dei ruoli (anche il giallo e le tinte chiare dei P) restano leggibili
        self.name_box.setStyleSheet("QTextEdit { background: #1b1b1f; border: 1px solid #444; "
                                    "border-radius: 6px; font-size: 19px; padding: 2px 4px; }")
        self.name_box.setToolTip("Seleziona un pezzo del nome e premi il tasto destro per dirne il ruolo\n"
                                 "(Titolo, Numero, Anno, P1…): la regola vale per tutti i file della finestra")
        l.addWidget(self.name_box)
        row = QHBoxLayout()
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("color: #bbb; font-size: 13px;")
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
        self._make_schema(split_name(self.paths[0])[0] if single else "<nome>")
        self.digits = QSpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(3)
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        row.addWidget(QLabel("Schema:"))
        row.addWidget(self.schema, 1)
        row.addWidget(self.b_clear)
        row.addWidget(QLabel("Cifre:"))
        row.addWidget(self.digits)
        row.addWidget(QLabel("Parti da:"))
        row.addWidget(self.start)
        l.addLayout(row)
        row = QHBoxLayout()
        hint = QLabel("Segnaposto: <nome> nome attuale · <tit> titolo · <num> numero già nel nome · "
                      "<sott> sottotitolo · "
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
        b_info = QPushButton("📝 Salva info nel fumetto…")
        set_variant(b_info, "info")
        b_info.setAutoDefault(False)
        b_info.setToolTip("Scrivi le info nel fumetto (ComicInfo.xml), ricavate dal nome con le marcature\n"
                          "fatte qui: si apre la finestra Info con le righe selezionate (o tutte)")
        b_info.clicked.connect(self.to_info)
        self.b_ok = QPushButton("Rinomina")
        set_variant(self.b_ok, "success")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self._rename)
        btns.addWidget(b_can)
        btns.addWidget(b_help)
        btns.addWidget(b_info)
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
                     enumerate(mark_spans(stem, self.split_numbers.isChecked()))]
        self._shown_stem, self._shown_units = stem, units
        # shortcut: posizioni Python = posizioni Qt finché il nome non ha emoji (fuori dal BMP)
        self.name_box.setPlainText(stem)
        cur = QTextCursor(self.name_box.document())

        def paint(a, b, color, ul=None, role=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if color != "#666":
                fmt.setBackground(QColor("#2e2e38"))
            if ul is not None:
                fmt.setUnderlineStyle(ul)
                fmt.setUnderlineColor(QColor(color))
                fmt.setFontItalic(role in ("edizione", "sottotitolo"))
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

    @staticmethod
    def _covered(spans, s, e):
        """Indici degli intervalli presi dalla selezione s…e: per più di metà, così sconfinare di
        qualche lettera nel pezzo accanto non lo prende; se nessuno, quello toccato di più."""
        over = [min(b, e) - max(a, s) for a, b in spans]
        hit = [j for j, (o, (a, b)) in enumerate(zip(over, spans)) if o > 0 and 2 * o > b - a]
        if not hit and s < e and max(over, default=0) > 0:
            hit = [over.index(max(over))]
        return hit

    def _sel_range(self):
        """(inizio, fine) di ciò che si marca: le parole prese dalla selezione (per più di metà).
        Se sono pezzi interi, comprende anche quelli uniti con Unisci. None se non c'è selezione."""
        s, e = self._selection()
        units = self._shown_units or []
        words = [w for _, a, b in units for w in piece_words(self._shown_stem, a, b)]
        hit = self._covered(words, s, e)
        if not hit:
            return None
        start, end = words[hit[0]][0], words[hit[-1]][1]
        starts, ends = [a for _, a, _ in units], [b for _, _, b in units]
        if start in starts and end in ends:
            lo, hi = starts.index(start), ends.index(end)
            joins = self._rule["joins"] if self._rule else set()
            while lo > 0 and units[lo - 1][0] in joins:
                lo -= 1
            while hi < len(units) - 1 and units[hi][0] in joins:
                hi += 1
            start, end = units[lo][1], units[hi][2]
        return start, end

    def _whole_units(self, rng):
        """Le unità che coprono esattamente rng, o None se rng taglia un pezzo."""
        units = self._shown_units or []
        inside = [u for u in units if rng[0] <= u[1] and u[2] <= rng[1]]
        if inside and inside[0][1] == rng[0] and inside[-1][2] == rng[1]:
            return inside
        return None

    def _mark_ranges(self):
        """{ruolo: (inizio, fine)} dei pezzi marcati nel nome mostrato."""
        if not (self._rule and self._shown_units):
            return {}
        pos = {k: (a, b) for k, a, b in self._shown_units}
        return {r: (pos[k1][0], pos[k2][1]) for r, (k1, k2) in self._rule["marks"].items()}

    def _keys(self, start, end):
        """(prima, ultima unità) esattamente da start a end: se la selezione prende solo una parte
        di un pezzo, il pezzo si divide lì (dopo le prime k parole o prima delle ultime k)."""
        rule, stem = self._ensure_rule(), self._shown_stem
        for c, side in ((start, 1), (end, 2)):
            if any(u[side] == c for u in rule_units(stem, rule)):
                continue
            i, (a, b) = next((i, sp) for i, sp in enumerate(mark_spans(stem, rule["split"]))
                             if sp[0] < c < sp[1])
            words = piece_words(stem, a, b)
            p, n = sum(1 for _, y in words if y <= c), len(words)
            self._add_cut(i, ("start", p) if p <= n - p else ("end", n - p), n)
        units = rule_units(stem, rule)
        return next(k for k, a, _ in units if a == start), next(k for k, _, b in units if b == end)

    def _add_cut(self, i, spec, n):
        """Aggiunge una divisione al pezzo i, tenendo le marcature dove sono."""
        rule, stem = self._rule, self._shown_stem
        old = {k: (a, b) for k, a, b in rule_units(stem, rule)}
        marks = {r: (old[k1][0], old[k2][1]) for r, (k1, k2) in rule["marks"].items()}
        joins = {old[k][0] for k in rule["joins"] if k[0] != i}
        cuts = rule["cuts"].setdefault(i, [])
        cuts.append(spec)
        cuts.sort(key=lambda c: c[1] if c[0] == "start" else n - c[1])
        new = rule_units(stem, rule)
        by_a, by_b = {a: k for k, a, _ in new}, {b: k for k, _, b in new}
        rule["marks"] = {r: (by_a[a], by_b[b]) for r, (a, b) in marks.items()}
        rule["joins"] = {by_a[a] for a in joins}

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

        rng = self._sel_range()
        if rng:
            text = self._shown_stem[rng[0]:rng[1]]
            add(f"«{text if len(text) <= 40 else text[:39] + '…'}» è:")      # cosa verrà marcato
            for role, (label, _, _) in MARK_ROLES.items():
                add(f"{label}   <{ROLE_TAGS[role]}>", lambda r=role: self.mark(r, rng))
            n = self._next_p()
            add(f"P{n}   <p{n}>   (il successivo libero)", lambda: self.mark(f"p{n}", rng))
            add("P…   (scegli il numero)", lambda: self._ask_p(rng))
            menu.addSeparator()
            whole = self._whole_units(rng)
            add("Ignora (togli il ruolo)", lambda: self.unmark(rng),
                any(a < rng[1] and b > rng[0] for a, b in self._mark_ranges().values()))
            add("Unisci in un solo pezzo", lambda: self.join(rng), bool(whole) and len(whole) > 1)
            add("Dividi: la selezione diventa un pezzo a sé", lambda: self.cut(rng), not whole)
        elif self._shown_units is None:
            add("Struttura diversa dal nome d'esempio: qui non si marca")
        else:
            add("Seleziona prima un pezzo del nome")
        menu.addSeparator()
        add("Azzera marcature", self.reset_marks, self._rule is not None)
        menu.exec(self.name_box.mapToGlobal(pos))

    def _ask_p(self, rng):
        n, ok = QInputDialog.getInt(self, "Pezzo", "Numero del pezzo (P1, P2…):", self._next_p(), 1, 99)
        if ok:
            self.mark(f"p{n}", rng)

    def _ensure_rule(self):
        if self._rule is None:
            self._rule = new_rule(self._shown_stem, self.split_numbers.isChecked())
        return self._rule

    def mark(self, role, rng=None):
        """Dà il ruolo al testo selezionato (un ruolo, un pezzo) e mette il segnaposto nello Schema.
        Se la selezione è solo una parte di un pezzo, il pezzo si divide lì."""
        rng = rng or self._sel_range()
        if not rng:
            return
        k1, k2 = self._keys(*rng)
        marks = self._rule["marks"]
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

    def unmark(self, rng=None):
        rng = rng or self._sel_range()
        for r, (a, b) in self._mark_ranges().items():
            if a < rng[1] and b > rng[0]:
                del self._rule["marks"][r]
        self._fill()

    def join(self, rng=None):
        units = self._whole_units(rng or self._sel_range())
        self._ensure_rule()["joins"].update(key for key, _, _ in units[:-1])
        self._fill()

    def cut(self, rng=None):
        """Dividi: la selezione diventa un pezzo a sé (senza ruolo)."""
        self._keys(*(rng or self._sel_range()))
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
        renamed = [i for i, p in enumerate(self.paths) if p in new_of]
        # prima i nomi nuovi, poi la selezione: togliere la selezione ricalcola la tabella,
        # che con i nomi vecchi cercherebbe file che non ci sono più
        for i in renamed:
            self.paths[i] = new_of[self.paths[i]]
            self.table.item(i, 0).setText(os.path.basename(self.paths[i]))
        self.table.clearSelection()                   # esce anche dal "nome singolo"
        for i in renamed:
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

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F1:
            self.show_help()
        else:
            super().keyPressEvent(e)

    def show_help(self):
        self.help_dialog().exec()

    def help_dialog(self):
        return _help_dialog(self, "Rinomina: aiuto", RENAME_HELP)

    def to_info(self):
        """Chiude e chiede alla finestra principale di aprire Info con queste righe e marcature."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or range(len(self.paths))
        self.info_request = ([self.paths[i] for i in rows], self._rule,
                             {key: e.text() for key, e in self.fields.items()},
                             self.split_numbers.isChecked())
        self.reject()

    def _search_title(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or [0]
        return clean_title(self.paths[rows[0]])

    def _set_author(self, text):
        self.fields["autore"].setText(text)

RENAME_HELP = """
<h3>Come si rinomina</h3>
<ol>
<li><b>Schema</b>: scrivi il formato del nuovo nome (nel menu a tendina: gli schemi usati di recente e tre schemi pronti; 🧹 svuota i recenti).</li>
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
<tr><td><b>&lt;sott&gt;</b></td><td>il sottotitolo: il pezzo marcato come <i>Sottotitolo</i> o, senza marcature,
 l'ultimo pezzo di testo dopo il titolo (<code>Batman 050 - The Wedding</code> → <code>The Wedding</code>)</td></tr>
<tr><td><b>&lt;tit&gt;</b></td><td>il titolo: il pezzo marcato come <i>Titolo</i> (vedi sotto) o, senza marcature,
 il primo pezzo di testo del nome, senza i gruppi tra parentesi (<code>Batman 050 (2016)</code> → <code>Batman</code>)</td></tr>
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
<tr><td colspan="2"><i>Valgono anche i nomi lunghi: &lt;titolo&gt;, &lt;sottotitolo&gt;, &lt;parte1&gt;, &lt;autore&gt;, &lt;editore&gt;,
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
Ogni pezzo ha uno sfondo più chiaro; i gruppi tra parentesi, come <code>(Shiryuu Nakatake)</code>, sono pezzi
a sé. Si marca esattamente ciò che selezioni, a parole intere (una parola presa per più di metà conta):
se selezioni solo una parte di un pezzo, il pezzo si divide lì da solo. In cima al menu compare il testo
che verrà marcato. Nel menu:</p>
<ul>
<li><b>Titolo</b> &lt;tit&gt;, <b>Numero</b> &lt;num&gt;, <b>Sottotitolo</b> &lt;sott&gt;, <b>Anno</b> &lt;anno&gt;, <b>Autore</b> &lt;aut&gt;,
 <b>Editore</b> &lt;pub&gt;, <b>Edizione</b> &lt;edz&gt;, <b>Lingua</b> &lt;lang&gt;, oppure <b>P1, P2…</b>
 (&lt;p1&gt;, &lt;p2&gt;…: il successivo libero, o il numero che scegli);</li>
<li><b>Ignora</b>: toglie il ruolo; <b>Unisci</b>: più pezzi diventano uno solo;
 <b>Dividi</b>: la selezione diventa un pezzo a sé, senza ruolo;</li>
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
<li>selezioni <code>(1986)</code> → <i>Anno</i>; <code>L'alba…</code> → <i>P3</i>;</li>
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
<tr><td>Manga</td><td><code>Kentaro Miura - Berserk - Cap #012.cbz</code><br>
 schema <code>&lt;aut&gt; - &lt;tit&gt; - Cap #&lt;num&gt;</code></td></tr>
<tr><td>Graphic novel</td><td><code>Zerocalcare - Kobane Calling (2016) (ITA).cbz</code><br>
 schema <code>&lt;aut&gt; - &lt;tit&gt; (&lt;anno&gt;) (&lt;lang&gt;)</code></td></tr>
<tr><td>Serie americane</td><td><code>Batman (2016) - #050 - The Wedding (ENG).cbz</code><br>
 schema <code>&lt;tit&gt; (&lt;anno&gt;) - #&lt;num&gt; - &lt;sott&gt; (&lt;lang&gt;)</code><br>
 l'anno è quello di <b>inizio della serie</b> (distingue Batman 1940, 2016, 2025)</td></tr>
</table>
<p>I tre schemi sono pronti nel menu a tendina dello Schema, dopo gli schemi usati di recente; il pulsante
<b>🧹</b> accanto svuota i recenti e lascia solo questi. <code>&lt;aut&gt;</code> e <code>&lt;lang&gt;</code>
vengono dal pezzo marcato nel nome o dalle caselle Autore e Lingua (l'autore si può cercare con 🔍 Cerca).
Regole comuni: la serie scritta sempre uguale, numeri con gli zeri davanti (<code>#007</code>),
<b>niente etichette</b> come <code>(Digital)</code> o <code>(Pyrate-…)</code>.</p>
<p><b>Una cartella per serie</b>, con lo stesso nome della serie, è il miglioramento più grande:
<code>Comics/Absolute Batman (2024)/Absolute Batman (2024) #001.cbz</code>,
<code>Manga/Jujika no Rokunin/Jujika no Rokunin Vol. 01.cbz</code>. Komga e Kavita usano la cartella come serie
(copertina, ordine, "prossimo da leggere"); il nome del file ripete la serie, così si capisce anche fuori dalla cartella.</p>
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
Dopo una rinomina, il pulsante <b>Annulla rinomina</b> nella finestra principale rimette i nomi di prima,
anche dopo aver chiuso e riaperto il programma. Le rinomine precedenti (le ultime 50) sono in <b>🕘 Rinomine</b>,
in basso nella finestra principale: ognuna si può annullare.</p>
<p><b>Come aprire la rinomina:</b> doppio click sul nome nella card, tasto <b>F2</b> o pulsante
<b>Rinomina</b>. In questa finestra, <b>F1</b> apre questo aiuto.</p>
"""

class InfoDialog(_SchemaMixin, _AuthorSearchMixin, QDialog):
    """
    Info del fumetto (ComicInfo.xml), una riga per fumetto, e nome nuovo costruito dalle info.
    Le celle si riempiono dal ComicInfo.xml già presente, altrimenti dal nome (regole e
    marcature della Rinomina). jobs() → {percorso: (info, CBZ di destinazione)} delle righe da salvare.
    """
    # stessi nomi della Rinomina; nel ComicInfo.xml Titolo → <Series>, Sottotitolo → <Title>
    FIELDS = [("titolo", "Titolo"), ("num", "Numero"), ("sottotitolo", "Sottotitolo"), ("anno", "Anno"),
              ("autore", "Autore"), ("editore", "Editore"), ("edizione", "Edizione"), ("lingua", "Lingua")]
    # colonne: nome attuale, nuovo nome, problema (sempre in vista), poi i campi e Manga
    C_NEW, C_NOTE, C_FIRST = 1, 2, 3
    C_MANGA = C_FIRST + len(FIELDS)

    def __init__(self, paths, parent=None, rule=None, fields=None, split_numbers=True):
        super().__init__(parent)
        self.setWindowTitle("Info del fumetto")
        fit_dialog_to_screen(self, 1180, 680, min_w=700, min_h=440)
        self.paths = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        self.split_numbers = split_numbers
        self.info, self.had_ci, self._orig = [], [], []
        for p in self.paths:
            have = read_comicinfo(p)                  # prima le info già nel fumetto, poi il nome
            guess = name_info(split_name(p)[0], split_numbers, fields, rule)
            row = {r: have.get(r) or guess.get(r, "") for r, _ in self.FIELDS}
            row["manga"] = have.get("manga", False)
            self.info.append(row)
            self.had_ci.append(bool(have))
            # quello che c'è davvero nel file: una riga uguale a questo non va riscritta
            self._orig.append({**{r: have.get(r, "") for r, _ in self.FIELDS}, "manga": row["manga"]})
        self._is_cbz = [file_status(p) in (1, 3) for p in self.paths]   # letto una volta sola
        self._jobs = {}
        l = QVBoxLayout(self)

        hint = QLabel("Le info vengono dal ComicInfo.xml già nel fumetto o, se non c'è, dal nome (con le "
                      "marcature della Rinomina). Doppio click su una cella per cambiarla. "
                      "\"Salva\" scrive le info nel fumetto (un CBR, un PDF o una cartella diventano CBZ) "
                      "e, con uno Schema, gli dà il nome nuovo.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 11px;")
        l.addWidget(hint)

        # caselle "per più righe": scrivendo, la colonna delle righe selezionate (o di tutte) si riempie
        many = QLabel("Per più righe insieme: quello che scrivi qui va subito nella colonna delle righe "
                      "selezionate (o di tutte); cancellandolo tornano i valori di prima.")
        many.setWordWrap(True)
        many.setStyleSheet("color: #00e5ff; font-size: 11px;")
        l.addWidget(many)
        self._bulk_before = {}                        # campo → {riga: valore prima della casella}
        grid = QGridLayout()
        self.bulk = {}
        for k, (role, label) in enumerate(self.FIELDS):
            edit = QLineEdit()
            edit.setPlaceholderText(label)
            grid.addWidget(QLabel(label + ":"), k // 4, (k % 4) * 2)
            if role == "autore":
                box = QHBoxLayout()
                box.addWidget(edit, 1)
                self.b_search = QPushButton("🔍 Cerca")
                self.b_search.setProperty("sz", "small")
                set_variant(self.b_search, "info")
                self.b_search.setAutoDefault(False)
                self.b_search.setToolTip("Cerca l'autore online (Wikidata, AniList) dal titolo del fumetto.\n"
                                         "Viene inviato solo il titolo, mai i file.")
                self.b_search.clicked.connect(self.search_author)
                box.addWidget(self.b_search)
                grid.addLayout(box, k // 4, (k % 4) * 2 + 1)
            else:
                grid.addWidget(edit, k // 4, (k % 4) * 2 + 1)
            self.bulk[role] = edit
            edit.textChanged.connect(lambda text, role=role: self._bulk_changed(role, text))
        self.bulk_manga = QComboBox()
        self.bulk_manga.addItems(["", "Sì", "No"])
        self.bulk_manga.setToolTip("Manga: lettura da destra a sinistra")
        grid.addWidget(QLabel("Manga:"), 2, 0)
        grid.addWidget(self.bulk_manga, 2, 1)
        self.bulk_manga.currentTextChanged.connect(lambda text: self._bulk_changed("manga", text))
        l.addLayout(grid)

        heads = ["Nome attuale", "Nuovo nome", "Cosa fa"] + [label for _, label in self.FIELDS] + ["Manga"]
        self.table = QTableWidget(len(self.paths), len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        fixed = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self.table.blockSignals(True)
        for i, p in enumerate(self.paths):
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(p)))
            self.table.item(i, 0).setFlags(fixed)
            for c, (role, _) in enumerate(self.FIELDS, self.C_FIRST):
                self.table.setItem(i, c, QTableWidgetItem(self.info[i][role]))
            manga = QTableWidgetItem()
            manga.setFlags(fixed | Qt.ItemFlag.ItemIsUserCheckable)
            manga.setCheckState(Qt.CheckState.Checked if self.info[i]["manga"] else Qt.CheckState.Unchecked)
            self.table.setItem(i, self.C_MANGA, manga)
            for c in (self.C_NEW, self.C_NOTE):
                self.table.setItem(i, c, QTableWidgetItem())
                self.table.item(i, c).setFlags(fixed)
        self.table.blockSignals(False)
        for c, w in enumerate((240, 240, 120, 150, 60, 150, 60, 130, 90, 80, 60, 55)):
            self.table.setColumnWidth(c, w)
        l.addWidget(self.table, 1)

        row = QHBoxLayout()
        self._make_schema("<nome>")
        self.digits = QSpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(3)
        row.addWidget(QLabel("Nome dalle info, Schema:"))
        row.addWidget(self.schema, 1)
        row.addWidget(self.b_clear)
        row.addWidget(QLabel("Cifre:"))
        row.addWidget(self.digits)
        l.addLayout(row)
        names = QLabel("Con <nome> il nome resta quello di adesso. <tit> Titolo · <num> Numero · <sott> Sottotitolo · "
                       "<anno> · <aut> · <pub> Editore · <edz> Edizione · <lang> Lingua · <n> progressivo")
        names.setTextFormat(Qt.TextFormat.PlainText)
        names.setWordWrap(True)
        names.setStyleSheet("color: #aaa; font-size: 11px;")
        l.addWidget(names)

        btns = QHBoxLayout()
        b_can = QPushButton("Annulla")
        set_variant(b_can, "danger")
        b_can.setAutoDefault(False)
        b_can.clicked.connect(self.reject)
        b_help = QPushButton("? Aiuto")
        set_variant(b_help, "info")
        b_help.setAutoDefault(False)
        b_help.clicked.connect(lambda: _help_dialog(self, "Info del fumetto: aiuto", INFO_HELP).exec())
        self.b_ok = QPushButton("Salva")
        set_variant(self.b_ok, "success")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self.accept)
        btns.addWidget(b_can)
        btns.addWidget(b_help)
        btns.addStretch(1)
        btns.addWidget(self.b_ok)
        l.addLayout(btns)

        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._new_selection)
        self.schema.editTextChanged.connect(self._refresh)
        self.digits.valueChanged.connect(self._refresh)
        self._refresh()

    def _edited(self, item):
        if self._store(item):
            self._refresh()

    def _store(self, item):
        """Cella di info cambiata: va nel dato della riga, in corsivo. False se non è una cella di info."""
        i, c = item.row(), item.column()
        if c == self.C_MANGA:
            self.info[i]["manga"] = item.checkState() == Qt.CheckState.Checked
        elif self.C_FIRST <= c < self.C_MANGA:
            self.info[i][self.FIELDS[c - self.C_FIRST][0]] = item.text().strip()
        else:
            return False
        was = self.table.blockSignals(True)
        f = item.font()
        f.setItalic(True)
        item.setFont(f)
        self.table.blockSignals(was)
        return True

    def _bulk_changed(self, role, text):
        """Casella per più righe: il valore va subito nella colonna delle righe selezionate (o di
        tutte, scelte al primo carattere); casella vuota → tornano i valori di prima."""
        if role not in self._bulk_before:
            rows = sorted({i.row() for i in self.table.selectedIndexes()}) or range(len(self.paths))
            self._bulk_before[role] = {i: self.info[i][role] for i in rows}
        before = self._bulk_before[role]
        value = text.strip()
        was = self.table.blockSignals(True)
        for i, old in before.items():
            if role == "manga":
                item = self.table.item(i, self.C_MANGA)
                on = old if not value else value == "Sì"
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            else:
                item = self.table.item(i, self.C_FIRST + [r for r, _ in self.FIELDS].index(role))
                item.setText(value or old)
            self._store(item)
        self.table.blockSignals(was)
        if not value:
            del self._bulk_before[role]
        self._refresh()

    def _new_selection(self):
        """Altre righe selezionate: le caselle ripartono vuote (quello già scritto resta nelle righe)."""
        self._bulk_before.clear()
        for edit in self.bulk.values():
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self.bulk_manga.blockSignals(True)
        self.bulk_manga.setCurrentIndex(0)
        self.bulk_manga.blockSignals(False)

    def _refresh(self):
        """Nuovo nome e problema di ogni riga; righe da salvare in self._jobs."""
        schema = self.schema.currentText().strip()
        self._jobs, taken = {}, set()
        self.table.blockSignals(True)
        for i, p in enumerate(self.paths):
            stem = split_name(p)[0]
            problem = None
            try:
                new = stem if schema in ("", "<nome>") else apply_schema(
                    stem, schema, i + 1, self.digits.value(), self.split_numbers, values=self.info[i])
            except ValueError as e:
                new, problem = stem, str(e)
            name = clean_filename(new)
            target = os.path.join(os.path.dirname(p), name + ".cbz") if name else ""
            anno = self.info[i]["anno"]
            if not problem and anno and not (anno.isdigit() and len(anno) == 4):
                problem = "anno non valido (4 cifre)"         # in ComicInfo <Year> è un numero
            if not problem:
                problem = ("nome vuoto" if not name
                           else None if target == p else rename_problem(p, target, taken))
            if target:
                taken.add(os.path.normcase(target))
            same = self.had_ci[i] and self.info[i] == self._orig[i] and target == p and self._is_cbz[i]
            if problem:
                note = f"⚠ {problem}"
            elif same:
                note = "invariato"
            else:
                note = "info" + (" + nome" if target != cbz_target(p) else "") + (
                    "" if self._is_cbz[i] else " · diventa CBZ")
                self._jobs[p] = (dict(self.info[i]), target)
            self.table.item(i, self.C_NEW).setText(os.path.basename(target) if target else "")
            self.table.item(i, self.C_NOTE).setText(note)
            bg = QColor("#5c1a1a") if problem else QColor(0, 0, 0, 0)
            for c in range(self.table.columnCount()):
                self.table.item(i, c).setBackground(bg)
        self.table.blockSignals(False)
        n = len(self._jobs)
        self.b_ok.setText(f"Salva {n} di {len(self.paths)}" if len(self.paths) > 1 else "Salva")
        self.b_ok.setEnabled(n > 0)

    def jobs(self):
        """{percorso: (info, CBZ di destinazione)} delle righe valide da salvare."""
        return dict(self._jobs)

    def accept(self):
        self._save_recent()
        super().accept()

    def _search_title(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or [0]
        return self.info[rows[0]]["titolo"] or clean_title(self.paths[rows[0]])

    def _set_author(self, text):
        self.bulk["autore"].setText(text)


INFO_HELP = """
<h3>Info del fumetto</h3>
<p>I lettori di fumetti (Komga, Kavita, YACReader) leggono serie, numero, titolo, autore e lingua dal file
<b>ComicInfo.xml</b> dentro il CBZ. Questa finestra lo scrive per te.</p>
<ul>
<li><b>Da dove vengono le info:</b> dal ComicInfo.xml già presente nel fumetto; se non c'è, dal nome del file,
 con le stesse regole della Rinomina (e con le marcature, se arrivi dalla Rinomina con <i>Info…</i>).</li>
<li><b>Una cella:</b> doppio click e scrivi. Le celle cambiate sono in corsivo.</li>
<li><b>Più righe insieme:</b> scrivi nelle caselle in alto (per esempio l'autore, anche con 🔍 Cerca): il valore
 va subito nella colonna delle righe selezionate, o di tutte se non ne selezioni. Cancellando il testo della casella
 tornano i valori di prima.</li>
<li><b>Titolo e Sottotitolo</b> sono gli stessi della Rinomina (<code>&lt;tit&gt;</code>, <code>&lt;sott&gt;</code>):
 nel ComicInfo.xml diventano la serie (<i>Series</i>) e il titolo della storia (<i>Title</i>).</li>
<li><b>Lingua:</b> puoi scrivere ITA, ENG, JPN… o Italiano, Inglese…: nel file diventa il codice standard
 (it, en, ja…).</li>
<li><b>Anno:</b> 4 cifre (2016); altrimenti la riga è rossa e non viene salvata.</li>
<li><b>Manga:</b> spunta per la lettura da destra a sinistra.</li>
</ul>
<h3>Il nome dalle info</h3>
<p>Con uno <b>Schema</b> il fumetto prende anche un nome nuovo, costruito dalle info della tabella:
<code>&lt;tit&gt;</code> Titolo, <code>&lt;num&gt;</code> Numero, <code>&lt;sott&gt;</code> Sottotitolo,
<code>&lt;anno&gt;</code>, <code>&lt;aut&gt;</code>, <code>&lt;pub&gt;</code>, <code>&lt;edz&gt;</code>,
<code>&lt;lang&gt;</code>, <code>&lt;n&gt;</code> progressivo. Per esempio
<code>&lt;tit&gt; (&lt;anno&gt;) - #&lt;num&gt; - &lt;sott&gt; (&lt;lang&gt;)</code>. Con <code>&lt;nome&gt;</code>
il nome resta quello di adesso. Una riga con un campo dello schema vuoto è rossa e non viene salvata.</p>
<h3>Salva</h3>
<p>Le info (e il nome) si scrivono con la stessa procedura sicura di <i>Sistema → Solo Ripara</i>: le pagine sono
copiate senza ricompressione, il nuovo CBZ viene verificato e solo dopo l'originale va nel cestino.
Un CBR, un PDF o una cartella di immagini diventano un CBZ. Gli altri campi già presenti nel ComicInfo.xml
(trama, disegnatore…) restano. Le righe "invariato" non vengono toccate.</p>
"""


class HistoryDialog(QDialog):
    """Cronologia delle rinomine (anche di sessioni precedenti): ognuna si può annullare."""

    def __init__(self, parent, on_undo):
        super().__init__(parent)
        self.setWindowTitle("Cronologia rinomine")
        fit_dialog_to_screen(self, 900, 520, min_w=560, min_h=320)
        self.on_undo = on_undo                        # on_undo(operazione) → quanti file annullati
        l = QVBoxLayout(self)
        hint = QLabel("Le ultime 50 rinomine, anche di quando il programma era stato chiuso. "
                      "\"Annulla\" rimette i nomi di prima, senza mai sovrascrivere; i file spostati "
                      "o convertiti nel frattempo vengono saltati.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 11px;")
        l.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Quando", "File", "Esempio", "Stato", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for c, w in enumerate((140, 45, 0, 150, 90)):
            self.table.setColumnWidth(c, w)
        # "Esempio" prende lo spazio libero: "Stato" e "Annulla" restano sempre in vista
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        l.addWidget(self.table, 1)
        b = QPushButton("Chiudi")
        set_variant(b, "info")
        b.clicked.connect(self.accept)
        l.addWidget(b, alignment=Qt.AlignmentFlag.AlignRight)
        self.load()

    def load(self):
        rows = history.batches()
        self.table.setRowCount(len(rows))
        for i, op in enumerate(rows):
            old, new = op["pairs"][0]
            alive = [p for p in op["pending"] if os.path.exists(p[1])]
            if not op["pending"]:
                state = "già annullata"
            elif alive:
                state = f"annullabile ({len(alive)})"
            else:
                state = "file non più presenti"
            more = f"  (+{len(op['pairs']) - 1})" if len(op["pairs"]) > 1 else ""
            for c, text in enumerate((op["time"], str(len(op["pairs"])),
                                      f"{os.path.basename(old)} → {os.path.basename(new)}{more}", state)):
                item = QTableWidgetItem(text)
                item.setToolTip("\n".join(f"{os.path.basename(o)} → {os.path.basename(n)}"
                                           for o, n in op["pairs"][:30]) if c == 2 else text)
                self.table.setItem(i, c, item)
            btn = QPushButton("Annulla")
            btn.setProperty("sz", "small")
            set_variant(btn, "danger")
            btn.setEnabled(bool(alive))
            btn.clicked.connect(lambda _=False, op=op: (self.on_undo(op), self.load()))
            self.table.setCellWidget(i, 4, btn)


class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QSpinBox { background: white; color: black; border: 2px solid #555; font-weight: bold; }")

    def wheelEvent(self, e):
        e.ignore()
