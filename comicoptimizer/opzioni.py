"""Finestra Opzioni: librerie, conversione in WebP, Info e rinomina."""
import os

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .comicinfo import togli_tag_schema
from .config import MINIATURE, WEBP_LATI, WEBP_LIVELLI, WEBP_QUALITY, opzione
from .library import (CAMPI_CARTELLE, MAX_LIBRERIE, SCHEMA_PREDEFINITO, info_libreria, librerie,
                      salva_info)
from .metadata_dialog import CAMPI_TESTO, SETTINGS
from .style import set_variant


class Opzioni(QDialog):
    """Le Opzioni del programma: libreria, conversione, rinomina."""

    def __init__(self, view):
        super().__init__(view)
        self.setWindowTitle("Opzioni")
        self.setMinimumWidth(680)
        l = QVBoxLayout(self)
        self.bottoni = {}                             # (campo di schema) → tasto: verde se c'è

        f = self._gruppo(l, "Librerie")
        cartelle = librerie()
        self.quante = QSpinBox()
        self.quante.setRange(1, MAX_LIBRERIE)
        self.quante.setValue(max(1, len(cartelle)))
        self.quante.setFixedWidth(70)                 # una cifra: non serve tutta la riga
        self.quante.setToolTip("Es. una per i fumetti italiani, una per i manga, una per gli americani")
        f.addRow("Quante:", self.quante)
        self.righe = []                               # (riga, nome, cartella, schema) di ogni libreria
        for i in range(MAX_LIBRERIE):
            cartella = cartelle[i] if i < len(cartelle) else ""
            info = info_libreria(cartella) if cartella else {"nome": "", "schema": SCHEMA_PREDEFINITO}
            riga = QWidget()
            g = QGridLayout(riga)
            g.setContentsMargins(0, 4, 0, 4)
            nome = QLineEdit(info["nome"])
            nome.setPlaceholderText(f"Nome (es. {('Manga', 'Fumetti italiani', 'Comics USA')[i % 3]})")
            dove = QLineEdit(cartella)
            dove.setPlaceholderText("Cartella dove sono i fumetti")
            b = QPushButton("Scegli…")
            b.setProperty("sz", "small")              # alto come i campi accanto, se no il testo si taglia
            set_variant(b, "")
            b.clicked.connect(lambda _on, d=dove, n=nome: self._scegli(d, n))
            schema = QLineEdit(info["schema"])
            schema.setToolTip("Cartelle per Ordina in cartelle e lo spostamento automatico: campi del "
                              "ComicInfo.xml tra < >, sottocartelle separate da /.\n"
                              "I campi vuoti spariscono; un fumetto senza nessuno di quei campi resta dov'è.")
            schema.cursorPositionChanged.connect(lambda *_a, e=schema: self._attiva(e))
            g.addWidget(QLabel(f"{i + 1}."), 0, 0)
            g.addWidget(nome, 0, 1)
            g.addWidget(dove, 0, 2)
            g.addWidget(b, 0, 3)
            g.addWidget(QLabel("Cartelle:"), 1, 1, Qt.AlignmentFlag.AlignRight)
            g.addWidget(schema, 1, 2, 1, 2)
            g.setColumnStretch(2, 1)
            f.addRow(riga)
            self.righe.append((riga, nome, dove, schema))
        self._schema_attivo = self.righe[0][3]
        f.addRow("", self._tasti(lambda: self._schema_attivo, CAMPI_CARTELLE, sottocartella=True))
        self.quante.valueChanged.connect(self._mostra_righe)
        self._mostra_righe()
        self.auto = self._casella(f, "Sposta i fumetti sistemati nella lista di lavoro nella libreria aperta",
                                  "libreria/auto")
        self.avvio = self._casella(f, "Controlla la libreria all'avvio (solo i file cambiati)",
                                   "libreria/controllo_avvio", True)
        self.controllo = None                         # None, o il controllo da avviare chiudendo (completo?)
        riga = QHBoxLayout()
        for testo, completo, aiuto in (
                ("Controlla ora", False, "Controllo rapido di tutte le librerie: file interi, doppioni, WebP,\n"
                                         "ComicInfo (non legge le pagine; rilegge solo i file cambiati)"),
                ("Controllo completo…", True, "Legge ogni pagina di ogni fumetto (trova anche le pagine rovinate).\n"
                                              "Lento: con migliaia di fumetti, ore. Si ferma e riprende.")):
            b = QPushButton(testo)
            b.setToolTip(aiuto)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _on, c=completo: self._controlla(c))
            riga.addWidget(b)
        riga.addStretch()
        f.addRow("Controllo:", riga)
        self.miniature = self._scelta(f, "Miniature:", MINIATURE, "libreria/miniature", 140)

        f = self._gruppo(l, "Conversione in WebP")
        self.qualita = self._scelta(f, "Qualità:", [(f"{t} — qualità {q}", q) for t, q in WEBP_LIVELLI],
                                    "webp/qualita", WEBP_QUALITY)
        self.lato = self._scelta(f, "Leggi su:", WEBP_LATI, "webp/lato", 0)
        aiuto = QLabel("Le pagine più grandi dello schermo su cui leggi vengono rimpicciolite (proporzioni "
                       "intatte): stessa nitidezza a schermo intero, file molto più leggeri. Scegli il "
                       "dispositivo più grande che usi; se ingrandisci spesso le pagine, quello sopra. "
                       "Per un iPad del 2018 (9,7″, 2048×1536): 2048 px.")
        aiuto.setWordWrap(True)
        aiuto.setStyleSheet("color: #aaa; font-size: 11px")
        f.addRow("", aiuto)
        self.ricomprimi = self._casella(f, "Ricomprimi anche le pagine già in WebP", "webp/ricomprimi")
        self.cancella = self._casella(f, "Cancella gli originali invece di spostarli nel cestino "
                                         "(definitivo, dopo la verifica del CBZ)", "lavoro/cancella_originali")
        self.processi = QSpinBox()
        self.processi.setRange(0, os.cpu_count() or 1)
        self.processi.setSpecialValueText("Tutti meno uno")
        self.processi.setValue(opzione("lavoro/processi", 0))
        self.processi.setToolTip("Meno processi: conversione più lenta, ma il PC resta più usabile")
        f.addRow("Processi:", self.processi)

        f = self._gruppo(l, "Info e rinomina")
        self.rinomina = QLineEdit(opzione("metadati/schema_predefinito", ""))
        self.rinomina.setPlaceholderText("Vuoto: l'ultimo usato")
        self.rinomina.setToolTip("Lo schema proposto aprendo Info e rinomina")
        f.addRow("Schema:", self.rinomina)
        f.addRow("", self._tasti(lambda: self.rinomina, [c for c in CAMPI_TESTO if c != "Summary"]))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def _gruppo(self, l, titolo):
        g = QGroupBox(titolo)
        l.addWidget(g)
        return QFormLayout(g)

    def _casella(self, f, testo, chiave, predefinito=False):
        c = QCheckBox(testo)
        c.setChecked(opzione(chiave, predefinito))
        c.setProperty("chiave", chiave)
        f.addRow(c)
        return c

    def _scelta(self, f, etichetta, voci, chiave, predefinito):
        c = QComboBox()
        for testo, valore in voci:
            c.addItem(testo, valore)
        c.setCurrentIndex(max(0, c.findData(opzione(chiave, predefinito))))
        c.setProperty("chiave", chiave)
        f.addRow(etichetta, c)
        return c

    def showEvent(self, e):
        super().showEvent(e)
        self._mostra_righe()                          # misura giusta solo ora, col tema applicato

    def _controlla(self, completo):
        """Salva le opzioni e chiude: il controllo parte dalla Libreria (vedi LibraryView.options)."""
        self.controllo = completo
        self.accept()
        if self.isVisible():                          # opzioni non valide: niente controllo
            self.controllo = None

    def _mostra_righe(self):
        for i, (riga, *_r) in enumerate(self.righe):
            riga.setVisible(i < self.quante.value())
        if self.isVisible():                          # all'apertura la misura Qt, col tema già applicato
            self.layout().activate()                  # la finestra cresce (o cala) con le righe
            self.resize(self.width(), self.sizeHint().height())

    def _attiva(self, schema):
        """I tasti dei campi delle cartelle valgono per lo schema dove si è cliccato per ultimo."""
        self._schema_attivo = schema
        self._colori()

    def _tasti(self, edit, campi, sottocartella=False):
        """Tasti +Campo che aggiungono o tolgono il campo dallo schema `edit()` (verdi se c'è)."""
        g = QGridLayout()
        tasti = [(f"+{c}", c) for c in campi] + ([("+ /", None)] if sottocartella else [])
        for n, (testo, campo) in enumerate(tasti):
            b = QPushButton(testo)
            b.setProperty("sz", "small")
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # il cursore resta nello schema
            if campo:
                b.clicked.connect(lambda _on, c=campo: self.inverti(c, edit()))
                self.bottoni[(edit, campo)] = b
            else:
                b.setToolTip("Sottocartella")
                b.clicked.connect(lambda: edit().insert("/"))
            g.addWidget(b, n // 7, n % 7)
        for e in self.findChildren(QLineEdit):
            e.textChanged.connect(self._colori)
        self._colori()
        return g

    def _scegli(self, dove, nome):
        folder = QFileDialog.getExistingDirectory(self, "Cartella della libreria", dove.text())
        if folder:
            dove.setText(folder)
            if not nome.text().strip():
                nome.setText(info_libreria(folder)["nome"])

    def inverti(self, campo, edit):
        schema = edit.text()
        if f"<{campo}>" in schema:
            edit.setText(togli_tag_schema(schema, campo).strip("/ "))
        else:
            edit.insert(f"<{campo}>")

    def _colori(self):
        for (edit, campo), b in self.bottoni.items():
            set_variant(b, "success" if f"<{campo}>" in edit().text() else "")

    def accept(self):
        scelte = [(n.text().strip(), d.text().strip(), s.text().strip() or SCHEMA_PREDEFINITO)
                  for _r, n, d, s in self.righe[:self.quante.value()] if d.text().strip()]
        manca = [d for _n, d, _s in scelte if not os.path.isdir(d)]
        if manca:
            QMessageBox.warning(self, "Opzioni", "Queste cartelle non esistono:\n" + "\n".join(manca))
            return
        try:
            for nome, cartella, schema in scelte:     # nome e schema viaggiano con la cartella
                salva_info(cartella, nome=nome or os.path.basename(os.path.normpath(cartella)), schema=schema)
        except OSError as e:
            QMessageBox.warning(self, "Opzioni", f"Non riesco a scrivere nella cartella della libreria:\n{e}")
            return
        cfg = QSettings(*SETTINGS)
        cfg.setValue("librerie", [d for _n, d, _s in scelte])
        cfg.setValue("metadati/schema_predefinito", self.rinomina.text().strip())
        cfg.setValue("lavoro/processi", self.processi.value())
        for c in self.findChildren(QCheckBox):
            cfg.setValue(c.property("chiave"), c.isChecked())
        for c in self.findChildren(QComboBox):
            cfg.setValue(c.property("chiave"), c.currentData())
        super().accept()
