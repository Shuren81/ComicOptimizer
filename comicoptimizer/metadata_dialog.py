"""Finestra unica per metadati (ComicInfo.xml), ricerca online e rinomina."""

import concurrent.futures
import html
import os
import threading
import time

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .cbz import INFO_FIELDS, file_status, read_comicinfo
from .comicinfo import (
    CAMPI,
    estrai_dal_nome,
    formatta_testo_intelligente,
    nome_da_schema,
    normalizza_lingua,
    pulisci_numero,
    scrivi_cbz,
    togli_maiuscole,
    togli_tag_schema,
)
from .dialogs import fit_dialog_to_screen
from .logsetup import log
from .ricerca import (
    FONTE_PREDEFINITA,
    FONTI_RICERCA,
    ErroreRicerca,
    ordina_per_parole,
    passa_filtro,
    richiesta_bytes,
    titolo_da_nome,
)
from .style import set_variant
from .utils import cbz_target, get_natural_sort_key, split_name
from .workers import ThumbWorker

SETTINGS = ("Shuren", "ComicOptimizer")
SCHEMA_PREDEFINITO = "<Series> - <Number> - <Title>"
SCHEMI_MAX = 10
MANGA_SI = "YesAndRightToLeft"                 # i manga si leggono da destra a sinistra
COLORE_DIVERSI = "background: #6b4e00;"
ORDINE_ANTEPRIMA = ("Series", "Number", "Title", "Year", "Count", "Publisher", "Writer", "Penciller",
                    "Characters", "Teams")
CAMPI_TESTO = tuple(c for c in CAMPI if c != "Manga")
RUOLI = {tag: ruolo for ruolo, tag in INFO_FIELDS}
LIMITE_PIXEL_ZOOM = 40_000_000                 # oltre, lo zoom scende: la memoria non basterebbe


class _Segnale(QObject):
    fine = pyqtSignal(object, object)


def in_background(padre, lavoro, al_termine):
    """lavoro() in un thread, poi al_termine(esito, errore) nell'interfaccia.
    Thread daemon: una ricerca lenta non blocca la chiusura del programma."""
    segnale = _Segnale(padre)
    segnale.fine.connect(al_termine)

    def corpo():
        esito, errore = None, None
        try:
            esito = lavoro()
        except Exception as e:
            errore = e
        try:
            segnale.fine.emit(esito, errore)
        except RuntimeError:                          # finestra già distrutta
            pass

    threading.Thread(target=corpo, daemon=True).start()


def _settings():
    return QSettings(*SETTINGS)


def salva_chiave(nome, valore):
    """Le chiavi API restano leggibili solo dal tuo utente."""
    impostazioni = _settings()
    impostazioni.setValue(f"ricerca/{nome}", valore)
    impostazioni.sync()
    try:
        os.chmod(impostazioni.fileName(), 0o600)
    except OSError as e:
        log.warning(f"Permessi delle impostazioni non cambiati: {e}")


def leggi_dati(percorso):
    """{campo: valore} dal ComicInfo.xml. Per CBR e PDF è tutto vuoto: si parte dal nome."""
    presenti = read_comicinfo(percorso)
    dati = {tag: presenti.get(ruolo, "") for ruolo, tag in INFO_FIELDS}
    dati["Number"] = pulisci_numero(dati["Number"])
    dati["Manga"] = MANGA_SI if presenti.get("manga") else ""
    return dati


def info_per_conversione(valori):
    """Le info nel formato di build_comicinfo, per i file che la catena converte in CBZ."""
    info = {RUOLI[c]: v for c, v in valori.items() if c in RUOLI}
    info["manga"] = bool(valori.get("Manga"))
    return info


def leggi_copertina(percorso):
    """La prima pagina a piena risoluzione, in ogni formato: la lettura è quella delle miniature."""
    dati = []
    lettore = ThumbWorker(percorso)
    lettore.done.connect(lambda _percorso, byte: dati.append(byte))
    lettore.run()                                  # gira già in un thread di in_background
    return dati[0] if dati else None


class VistaCopertina(QScrollArea):
    """Copertina adattata allo spazio, oppure ingrandita e da spostare trascinandola col mouse."""

    def __init__(self):
        super().__init__()
        self.originale = None
        self.fattore = 1
        self.presa = None
        self.etichetta = QLabel()
        self.etichetta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.etichetta)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def imposta(self, immagine, testo=""):
        self.originale = immagine
        self.etichetta.setText(testo)
        self._disegna()

    def zoom(self, fattore):
        self.fattore = fattore
        self._disegna()

    def _disegna(self):
        if self.originale is None:
            self.etichetta.resize(self.viewport().size())
            return
        if self.fattore == 1:
            immagine = self.originale.scaled(
                self.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        else:
            larghezza, altezza = self.originale.width(), self.originale.height()
            fattore = self.fattore
            while fattore > 1 and larghezza * altezza * fattore * fattore > LIMITE_PIXEL_ZOOM:
                fattore -= 1
            immagine = self.originale.scaled(
                larghezza * fattore, altezza * fattore, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self.etichetta.setPixmap(immagine)
        self.etichetta.resize(immagine.size())

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        if self.fattore == 1 or self.originale is None:
            self._disegna()

    def mousePressEvent(self, evento):
        self.presa = evento.position().toPoint()

    def mouseMoveEvent(self, evento):
        if self.presa is not None:
            punto = evento.position().toPoint()
            spostamento = punto - self.presa
            self.presa = punto
            orizzontale, verticale = self.horizontalScrollBar(), self.verticalScrollBar()
            orizzontale.setValue(orizzontale.value() - spostamento.x())
            verticale.setValue(verticale.value() - spostamento.y())

    def mouseReleaseEvent(self, evento):
        self.presa = None


class SearchDialog(QDialog):
    """Ricerca online. Con "Applica", `scelti` contiene i campi del risultato."""

    def __init__(self, nome_file, valori, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ricerca online")
        fit_dialog_to_screen(self, 980, 720, min_w=640, min_h=460)
        self.scelti = None
        self.nome_file = nome_file
        self.serie = valori.get("Series", "")
        self.numero = valori.get("Number", "")
        self.serie_iniziale = self.serie or " ".join(
            nome_file.replace("#", " ").replace("_", " ").replace("-", " ").replace(".", " ").split())
        self.testo_file = " ".join((nome_file, self.serie, self.numero, valori.get("Title", "")))
        self.risultati, self.visibili = [], []
        self.copertine = {}
        self.in_download = set()
        self.copertina_corrente = None
        self.id_ricerca = 0
        self.inizio = 0
        self.nome_ricerca = ""

        principale = QHBoxLayout(self)
        sinistra, destra = QVBoxLayout(), QVBoxLayout()
        principale.addLayout(sinistra, 3)
        principale.addLayout(destra, 2)

        griglia = QGridLayout()
        self.combo_fonte = QComboBox()
        self.combo_fonte.addItems(FONTI_RICERCA)
        fonte = _settings().value("ricerca/fonte", FONTE_PREDEFINITA)
        self.combo_fonte.setCurrentText(fonte if fonte in FONTI_RICERCA else FONTE_PREDEFINITA)
        griglia.addWidget(QLabel("Fonte:"), 0, 0)
        griglia.addWidget(self.combo_fonte, 0, 1)
        self.etichetta_chiave = QLabel()
        self.chiave = QLineEdit()
        self.chiave.setEchoMode(QLineEdit.EchoMode.Password)
        griglia.addWidget(self.etichetta_chiave, 1, 0)
        griglia.addWidget(self.chiave, 1, 1)
        self.aiuto = QLabel()
        self.aiuto.setTextFormat(Qt.TextFormat.PlainText)
        self.b_aiuto = QPushButton("Apri il sito")
        self.b_aiuto.setProperty("sz", "small")
        self.b_aiuto.setAutoDefault(False)
        self.b_aiuto.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.fonte()["url_aiuto"])))
        griglia.addWidget(self.aiuto, 2, 1)
        griglia.addWidget(self.b_aiuto, 2, 2)
        self.query = QLineEdit()
        self.b_cerca = QPushButton("Cerca")
        self.b_cerca.setAutoDefault(False)
        griglia.addWidget(QLabel("Cerca serie o albo:"), 3, 0)
        griglia.addWidget(self.query, 3, 1)
        griglia.addWidget(self.b_cerca, 3, 2)
        griglia.setColumnStretch(1, 1)
        sinistra.addLayout(griglia)

        self.stato = QLabel()
        self.stato.setWordWrap(True)
        self.stato.setStyleSheet("color: #00e5ff; font-weight: bold;")
        sinistra.addWidget(self.stato)
        sinistra.addWidget(QLabel("Filtra i risultati:"))
        self.filtro = QLineEdit()
        sinistra.addWidget(self.filtro)
        self.lista = QListWidget()
        sinistra.addWidget(self.lista, 1)
        self.b_applica = QPushButton("Applica ai campi")
        set_variant(self.b_applica, "success")
        self.b_applica.setAutoDefault(False)
        sinistra.addWidget(self.b_applica)

        self.copertina = QLabel("Nessuna copertina")
        self.copertina.setFixedSize(180, 230)
        self.copertina.setAlignment(Qt.AlignmentFlag.AlignCenter)
        destra.addWidget(self.copertina, 0, Qt.AlignmentFlag.AlignHCenter)
        destra.addWidget(QLabel("Campi da importare:"))
        self.anteprima = QTextEdit()
        self.anteprima.setReadOnly(True)
        self.anteprima.setAcceptRichText(False)
        destra.addWidget(self.anteprima, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._aggiorna_timer)
        self.combo_fonte.currentTextChanged.connect(self._cambio_fonte)
        self.filtro.textChanged.connect(self._filtra)
        self.lista.currentRowChanged.connect(self._seleziona)
        self.b_cerca.clicked.connect(self.cerca)
        self.query.returnPressed.connect(self.cerca)
        self.chiave.returnPressed.connect(self.cerca)
        self.b_applica.clicked.connect(self.applica)
        self.lista.itemDoubleClicked.connect(lambda _item: self.applica())
        self._prepara_fonte()
        self.query.setFocus()

    def fonte(self):
        return FONTI_RICERCA[self.combo_fonte.currentText()]

    def _cambio_fonte(self):
        _settings().setValue("ricerca/fonte", self.combo_fonte.currentText())
        self._prepara_fonte()

    def _prepara_fonte(self):
        f = self.fonte()
        self.etichetta_chiave.setText(f["etichetta_chiave"])
        self.aiuto.setText(f["aiuto"])
        self.chiave.setEnabled(bool(f["chiave_config"]))
        self.chiave.setText(_settings().value(f"ricerca/{f['chiave_config']}", "") if f["chiave_config"] else "")
        if f.get("memoria") is not None and not self.serie:
            self.query.setText(titolo_da_nome(self.nome_file))
        else:
            self.query.setText(f["query_iniziale"](self.serie_iniziale, self.numero))
        self.id_ricerca += 1                          # una ricerca ancora in corso non conta più
        self.timer.stop()
        self.b_cerca.setEnabled(True)
        self._svuota()
        self.stato.setText("")
        if f.get("memoria"):
            for r in f["memoria"].values():
                if r.get("dettagli_stato") != "ok":
                    r["dettagli_stato"] = None        # scheda rimasta a metà: si riprova
            self.risultati.extend(ordina_per_parole(f["memoria"].values(), self.testo_file))
            self._filtra()
            self.stato.setText(f"{len(self.risultati)} risultati già trovati, i più simili in cima. "
                               "Se manca, premi Cerca.")

    def _svuota(self):
        self.risultati.clear()
        self.filtro.clear()
        self._filtra()
        self.anteprima.clear()
        self._scrivi_copertina("Nessuna copertina")

    def _filtra(self):
        testo = self.filtro.text()
        self.visibili = [r for r in self.risultati if passa_filtro(testo, r["etichetta"])]
        self.lista.blockSignals(True)
        self.lista.clear()
        self.lista.addItems(r["etichetta"] for r in self.visibili)
        self.lista.blockSignals(False)

    def _selezionato(self):
        riga = self.lista.currentRow()
        return self.visibili[riga] if 0 <= riga < len(self.visibili) else None

    def _testo_anteprima(self, r):
        righe = [f"{c}: {r['campi'][c]}" for c in ORDINE_ANTEPRIMA if r["campi"].get(c)]
        righe += r.get("note") or []
        if r.get("dettagli_stato") == "in corso":
            righe.append("\n(carico autori, trama e altri dettagli...)")
        elif r.get("dettagli_stato") == "errore":
            righe.append(f"\n(dettagli non disponibili: {r.get('dettagli_errore', '')})")
        if r["campi"].get("Summary"):
            righe.append(f"\nSummary:\n{r['campi']['Summary']}")
        return "\n".join(righe)

    def _seleziona(self):
        r = self._selezionato()
        if r is None:
            return
        self.anteprima.setPlainText(self._testo_anteprima(r))
        self._mostra_copertina(r.get("copertina"))
        f = self.fonte()
        if f["dettagli"] and not r.get("dettagli_stato"):
            r["dettagli_stato"] = "in corso"
            self.anteprima.setPlainText(self._testo_anteprima(r))
            chiave = self.chiave.text().strip()

            def fine(esito, errore):
                if errore:
                    r["dettagli_stato"] = "errore"
                    r["dettagli_errore"] = str(errore).splitlines()[0] if str(errore) else "errore"
                else:
                    r["campi"].update({k: v for k, v in (esito or {}).items() if v})
                    r["dettagli_stato"] = "ok"
                if self._selezionato() is r:
                    self.anteprima.setPlainText(self._testo_anteprima(r))
                    self._mostra_copertina(r.get("copertina"))

            def avvia():
                if self._selezionato() is r:
                    in_background(self, lambda: f["dettagli"](chiave, r), fine)
                else:
                    r["dettagli_stato"] = None        # di passaggio con le frecce: niente richieste inutili

            QTimer.singleShot(400, avvia)

    def _scrivi_copertina(self, testo):
        self.copertina.setPixmap(QPixmap())
        self.copertina.setText(testo)

    def _mostra_copertina(self, url):
        self.copertina_corrente = url
        if not url:
            self._scrivi_copertina("Nessuna copertina")
        elif url in self.copertine:
            immagine = QPixmap()
            if self.copertine[url] and immagine.loadFromData(self.copertine[url]):
                self.copertina.setPixmap(immagine.scaled(
                    self.copertina.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            else:
                self._scrivi_copertina("Copertina non disponibile")
        else:
            self._scrivi_copertina("Caricamento copertina...")
            if url not in self.in_download:
                self.in_download.add(url)

                def fine(esito, errore):
                    self.copertine[url] = None if errore else esito
                    self.in_download.discard(url)
                    if self.copertina_corrente == url:
                        self._mostra_copertina(url)

                in_background(self, lambda: richiesta_bytes(url, timeout=15), fine)

    def _aggiorna_timer(self):
        trascorso = int(time.monotonic() - self.inizio)
        lento = " (il server è lento, attendi...)" if trascorso > 20 else ""
        self.stato.setText(f"Ricerca su {self.nome_ricerca} in corso... {trascorso}s{lento}")

    def cerca(self):
        if not self.b_cerca.isEnabled():
            return
        nome, f = self.combo_fonte.currentText(), self.fonte()
        chiave, query = self.chiave.text().strip(), self.query.text().strip()
        if f["chiave_config"] and not chiave:
            QMessageBox.warning(self, "Ricerca", f"Inserisci la chiave: {f['etichetta_chiave'].rstrip(':')}.")
            return
        if not query:
            QMessageBox.warning(self, "Ricerca", "Inserisci un termine di ricerca.")
            return
        _settings().setValue("ricerca/fonte", nome)
        self._svuota()
        self.id_ricerca += 1
        mio_id = self.id_ricerca
        self.inizio, self.nome_ricerca = time.monotonic(), nome
        self.b_cerca.setEnabled(False)
        self._aggiorna_timer()
        self.timer.start()

        def fine(esito, errore):
            if mio_id != self.id_ricerca:
                return                                # nel frattempo hai cambiato fonte
            self.timer.stop()
            self.b_cerca.setEnabled(True)
            self.stato.setText("")
            if errore:
                testo = str(errore) if isinstance(errore, ErroreRicerca) else f"Errore imprevisto: {errore}"
                QMessageBox.warning(self, f"Errore {nome}", testo)
                return
            if f["chiave_config"]:
                salva_chiave(f["chiave_config"], chiave)   # la chiave funziona: la ricordo
            if not esito:
                QMessageBox.information(self, "Risultati", f"Nessun risultato su {nome} per questa ricerca.")
                return
            # prima chi ha più parole in comune con la ricerca; a parità resta l'ordine della fonte
            if f.get("memoria") is not None:
                esito = ordina_per_parole(
                    [f["memoria"].setdefault(r["grezzo"]["url"], r) for r in esito], self.testo_file)
            else:
                esito = ordina_per_parole(esito, query)
            self.risultati.extend(esito)
            self._filtra()

        in_background(self, lambda: f["cerca"](chiave, query), fine)

    def applica(self):
        r = self._selezionato()
        if r is None:
            QMessageBox.information(self, "Ricerca", "Seleziona un elemento dalla lista.")
            return
        if r.get("dettagli_stato") == "in corso":
            QMessageBox.information(self, "Ricerca", "Sto ancora caricando i dettagli: attendi un istante e riprova.")
            return
        self.scelti = {}
        for campo, valore in r["campi"].items():
            if valore:
                valore = str(valore)
                if self.fonte()["formatta_titoli"] and campo in ("Series", "Title"):
                    valore = formatta_testo_intelligente(valore)
                self.scelti[campo] = valore
        self.accept()


class ConfermaRinomina(QDialog):
    """Elenco completo: nome attuale in grigio, nome nuovo in grassetto."""

    def __init__(self, piano, parent=None, finestra="Conferma rinomina", domanda=None, azione="Rinomina"):
        super().__init__(parent)
        self.setWindowTitle(finestra)
        fit_dialog_to_screen(self, 760, min(240 + 58 * len(piano), 620), min_w=460, min_h=240)
        l = QVBoxLayout(self)
        titolo = QLabel(domanda or f"Rinominare {len(piano)} file?")
        titolo.setStyleSheet("font-size: 15px; font-weight: bold;")
        l.addWidget(titolo)
        self.elenco = QTextEdit()
        self.elenco.setReadOnly(True)
        # spostamenti (stesso nome, cartella diversa): si mostra il percorso intero
        nome = lambda v, n, p: p if os.path.dirname(v) != os.path.dirname(n) else os.path.basename(p)
        self.elenco.setHtml("".join(
            f'<p style="margin-bottom:10px"><span style="color:#9e9e9e">{html.escape(nome(v, n, v))}</span><br>'
            f'<b>→ {html.escape(nome(v, n, n))}</b></p>' for v, n in piano))
        l.addWidget(self.elenco, 1)
        pulsanti = QHBoxLayout()
        pulsanti.addStretch()
        self.b_si = QPushButton(azione)
        set_variant(self.b_si, "success")
        self.b_si.setDefault(True)
        self.b_si.clicked.connect(self.accept)
        self.b_no = QPushButton("Annulla")
        self.b_no.setAutoDefault(False)
        self.b_no.clicked.connect(self.reject)
        pulsanti.addWidget(self.b_si)
        pulsanti.addWidget(self.b_no)
        pulsanti.addStretch()
        l.addLayout(pulsanti)


class MetadataDialog(QDialog):
    """
    Info e nome dei fumetti, una finestra sola. I valori modificati restano in `pending`, file per
    file, finché non si salva. Con più file selezionati i campi vuoti e diversi non si toccano.
    on_rename(coppie) rinomina sul disco e restituisce le coppie riuscite.
    Dopo la chiusura, `conversioni` = {percorso: (info, CBZ)} dei file da convertire per scrivere le info.
    """

    def __init__(self, paths, parent=None, on_rename=None):
        super().__init__(parent)
        self.setWindowTitle("Info e rinomina")
        fit_dialog_to_screen(self, 1560, 860, min_w=1200, min_h=500)
        self.on_rename = on_rename
        self.paths = sorted(paths, key=lambda p: get_natural_sort_key(os.path.basename(p)))
        self.disco = {}
        self.pending = {}
        self.conversioni = {}
        self.toccati = set()         # campi cambiati da te nella selezione corrente
        self.automatici = set()      # riempiti dal programma: contano solo quando salvi
        self.diversi = set()
        self.vista = {}              # i valori caricati nella selezione corrente
        self.selezione = []
        self.salvataggio_in_corso = False
        self._caricamento = False
        self.percorso_copertina = None
        self.lettura_copertina = False
        self.ultima_lingua = normalizza_lingua(_settings().value("metadati/ultima_lingua", "") or "") or ""

        principale = QHBoxLayout(self)
        sinistra = QVBoxLayout()
        principale.addLayout(sinistra, 1)
        self._costruisci_sinistra(sinistra)
        # Scorrono solo i campi: Salva e Rinomina restano sempre in vista
        campi = QWidget()
        colonna = QVBoxLayout(campi)
        destra = QVBoxLayout()
        scorri = QScrollArea()
        scorri.setWidgetResizable(True)
        scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scorri.setWidget(campi)
        destra.addWidget(scorri, 1)
        self._costruisci_campi(colonna, destra)
        self._costruisci_rinomina(destra)
        principale.addLayout(destra, 3)
        self._costruisci_copertina(principale)

        for nome in self.paths:
            self.lista.addItem(os.path.basename(nome))
        self.lista.selectAll()
        self._nuova_selezione()
        self.lista.itemSelectionChanged.connect(self._nuova_selezione)

    # --- costruzione ---

    def _costruisci_copertina(self, principale):
        gruppo = QGroupBox("Copertina")
        v = QVBoxLayout(gruppo)
        riga = QHBoxLayout()
        riga.addWidget(QLabel("Zoom:"))
        self.combo_zoom = QComboBox()
        self.combo_zoom.addItem("x1 (Adatta)", 1)
        self.combo_zoom.addItem("x2", 2)
        self.combo_zoom.addItem("x3", 3)
        self.combo_zoom.currentIndexChanged.connect(lambda: self.vista_copertina.zoom(self.combo_zoom.currentData()))
        riga.addWidget(self.combo_zoom)
        riga.addStretch()
        v.addLayout(riga)
        self.vista_copertina = VistaCopertina()
        v.addWidget(self.vista_copertina, 1)
        principale.addWidget(gruppo, 3)

    def _costruisci_sinistra(self, l):
        l.addWidget(QLabel("Fumetti (Ctrl o Maiusc per selezionarne più di uno):"))
        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        l.addWidget(self.lista, 1)

        gruppo = QGroupBox("Estrazione dal nome")
        griglia = QGridLayout(gruppo)
        self.regole = []
        for i, campo in enumerate(("Series", "Title")):
            attiva = QCheckBox(f"Copia ({i + 1}) in")
            combo = QComboBox()
            combo.addItems(CAMPI_TESTO)
            combo.setCurrentText(campo)
            dopo, fino = QLineEdit(), QLineEdit()
            dopo.setPlaceholderText("dopo")
            fino.setPlaceholderText("fino a")
            griglia.addWidget(attiva, i, 0)
            griglia.addWidget(combo, i, 1)
            griglia.addWidget(dopo, i, 2)
            griglia.addWidget(fino, i, 3)
            attiva.toggled.connect(self._regole_cambiate)
            combo.currentTextChanged.connect(self._regole_cambiate)
            dopo.textEdited.connect(self._regole_cambiate)
            fino.textEdited.connect(self._regole_cambiate)
            self.regole.append((attiva, combo, dopo, fino))
        self.anteprima_regole = QTextEdit()
        self.anteprima_regole.setReadOnly(True)
        self.anteprima_regole.setAcceptRichText(False)
        self.anteprima_regole.setFixedHeight(70)
        griglia.addWidget(self.anteprima_regole, 2, 0, 1, 4)
        self.b_invia = QPushButton("Invia ai campi dei file selezionati")
        self.b_invia.setAutoDefault(False)
        self.b_invia.clicked.connect(self.invia_estrazione)
        griglia.addWidget(self.b_invia, 3, 0, 1, 4)
        l.addWidget(gruppo)

    def _costruisci_campi(self, l, sotto):
        griglia = QGridLayout()
        self.caselle, self.svuota, self.etichette = {}, {}, {}
        for riga, campo in enumerate(CAMPI_TESTO):
            etichetta = QLabel(campo)
            griglia.addWidget(etichetta, riga, 0, Qt.AlignmentFlag.AlignTop)
            self.etichette[campo] = etichetta
            if campo == "Summary":
                casella = QTextEdit()
                casella.setAcceptRichText(False)
                casella.setTabChangesFocus(True)
                casella.setFixedHeight(90)
                casella.textChanged.connect(lambda c=campo: self._toccato(c))
            else:
                casella = QLineEdit()
                casella.textEdited.connect(lambda _t, c=campo: self._toccato(c))
                casella.returnPressed.connect(lambda c=campo: self._prossimo_file(c))
            griglia.addWidget(casella, riga, 1)
            self.caselle[campo] = casella
            svuota = QCheckBox("Svuota")
            svuota.toggled.connect(lambda on, c=campo: self._svuota_cambiato(c, on))
            griglia.addWidget(svuota, riga, 2, Qt.AlignmentFlag.AlignTop)
            self.svuota[campo] = svuota
        griglia.setColumnStretch(1, 1)
        l.addLayout(griglia)
        self.caselle["LanguageISO"].editingFinished.connect(self._ricorda_lingua)

        self.legenda = QLabel("≠  valori diversi tra i file selezionati (vuoto = non toccarli)")
        self.legenda.setStyleSheet(COLORE_DIVERSI + " padding: 3px;")
        self.legenda.hide()
        sotto.addWidget(self.legenda)

        riga = QHBoxLayout()
        self.manga = QCheckBox("Manga (destra → sinistra)")
        self.manga.clicked.connect(lambda: (self.manga.setTristate(False), self._toccato("Manga")))
        riga.addWidget(self.manga)
        self.numera = QCheckBox("Numera in automatico, partendo da")
        self.numera.toggled.connect(self._aggiorna_anteprime)
        self.inizio = QSpinBox()
        self.inizio.setRange(0, 999999)
        self.inizio.setValue(1)
        self.inizio.valueChanged.connect(self._aggiorna_anteprime)
        riga.addWidget(self.numera)
        riga.addWidget(self.inizio)
        riga.addStretch()
        self.b_cerca = QPushButton("🔍 Cerca online")
        set_variant(self.b_cerca, "info")
        self.b_cerca.setAutoDefault(False)
        self.b_cerca.clicked.connect(self.apri_ricerca)
        riga.addWidget(self.b_cerca)
        self.b_salva = QPushButton("Salva metadati")
        set_variant(self.b_salva, "success")
        self.b_salva.setAutoDefault(False)
        self.b_salva.clicked.connect(self.salva)
        riga.addWidget(self.b_salva)
        sotto.addLayout(riga)
        self.stato = QLabel()
        self.stato.setWordWrap(True)
        sotto.addWidget(self.stato)

    def _costruisci_rinomina(self, l):
        gruppo = QGroupBox("Rinomina dai metadati")
        v = QVBoxLayout(gruppo)
        riga = QHBoxLayout()
        riga.addWidget(QLabel("Schema:"))
        self.schema = QComboBox()
        self.schema.setEditable(True)
        self.schema.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        recenti = _settings().value("metadati/schemi_recenti", [], type=list)
        self.schema.addItems(recenti or [SCHEMA_PREDEFINITO])
        self.schema.lineEdit().setCursorPosition(len(self.schema.currentText()))
        self.schema.currentTextChanged.connect(self._aggiorna_anteprime)
        riga.addWidget(self.schema, 1)
        riga.addWidget(QLabel("Cifre:"))
        self.cifre = QSpinBox()
        self.cifre.setRange(1, 5)
        self.cifre.setValue(3)
        self.cifre.valueChanged.connect(self._aggiorna_anteprime)
        riga.addWidget(self.cifre)
        v.addLayout(riga)

        griglia = QGridLayout()
        self.bottoni_tag = {}
        for posizione, campo in enumerate(c for c in CAMPI_TESTO if c != "Summary"):
            b = QPushButton(f"+{campo}")
            b.setProperty("sz", "small")
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # il cursore resta nello schema
            b.clicked.connect(lambda _on, c=campo: self.inverti_tag(c))
            griglia.addWidget(b, posizione // 5, posizione % 5)
            self.bottoni_tag[campo] = b
        v.addLayout(griglia)

        self.anteprima_nome = QLineEdit()
        self.anteprima_nome.setReadOnly(True)
        v.addWidget(self.anteprima_nome)
        self.b_rinomina = QPushButton("Rinomina selezionati")
        set_variant(self.b_rinomina, "primary")
        self.b_rinomina.setAutoDefault(False)
        self.b_rinomina.clicked.connect(self.rinomina)
        v.addWidget(self.b_rinomina)
        l.addWidget(gruppo)

    # --- valori ---

    def _dati(self, percorso):
        if percorso not in self.disco:
            self.disco[percorso] = leggi_dati(percorso)
        return self.disco[percorso]

    def _leggi(self, campo):
        if campo == "Manga":
            return MANGA_SI if self.manga.checkState() == Qt.CheckState.Checked else ""
        casella = self.caselle[campo]
        testo = (casella.toPlainText() if campo == "Summary" else casella.text()).strip()
        return pulisci_numero(testo) if campo == "Number" else testo

    def _scrivi(self, campo, testo):
        testo = togli_maiuscole(campo, testo)
        casella = self.caselle[campo]
        if campo == "Summary":
            casella.setPlainText(testo)
        else:
            casella.setText(pulisci_numero(testo) if campo == "Number" else testo)

    def _toccato(self, campo):
        if self._caricamento:
            return
        self.toccati.add(campo)
        self.automatici.discard(campo)
        self._aggiorna_anteprime()

    def _svuota_cambiato(self, campo, attivo):
        if self._caricamento:
            return
        self._caricamento = True
        self._scrivi(campo, "" if attivo else self.vista.get(campo, ""))
        self._caricamento = False
        self.caselle[campo].setEnabled(not attivo)
        if attivo:
            self._toccato(campo)
        else:
            self.toccati.discard(campo)
            self._aggiorna_anteprime()

    def _ricorda_lingua(self):
        # Solo la lingua scritta da te: quella letta da un file non cambia la tua scelta
        codice = normalizza_lingua(self.caselle["LanguageISO"].text())
        if "LanguageISO" in self.toccati and codice and codice != self.ultima_lingua:
            self.ultima_lingua = codice
            _settings().setValue("metadati/ultima_lingua", codice)

    def _conserva(self):
        """Porta tra le modifiche del file quello che hai cambiato a video."""
        for campo in self.toccati:
            valore = self._leggi(campo)
            for p in self.selezione:
                voce = self.pending.setdefault(p, {})
                if valore == self._dati(p).get(campo, ""):
                    voce.pop(campo, None)
                else:
                    voce[campo] = valore
                if not voce:
                    del self.pending[p]

    def _nuova_selezione(self):
        self._conserva()
        self._carica()

    def _selezionati(self):
        return [self.paths[self.lista.row(i)] for i in self.lista.selectedItems()]

    def _estrazioni(self, percorso):
        risultati = {}
        for attiva, combo, dopo, fino in self.regole:
            if attiva.isChecked():
                testo = estrai_dal_nome(split_name(percorso)[0], dopo.text(), fino.text())
                if testo:
                    risultati[combo.currentText()] = pulisci_numero(testo) if combo.currentText() == "Number" else testo
        return risultati

    def _valori_file(self, percorso):
        return {**self._dati(percorso), **self.pending.get(percorso, {})}

    def _carica(self):
        self._caricamento = True
        self.selezione = sorted(self._selezionati(), key=self.paths.index)
        self.toccati.clear()
        self.automatici.clear()
        self.diversi.clear()
        self.vista = {}
        for campo in CAMPI_TESTO:
            self.svuota[campo].setChecked(False)
            self.caselle[campo].setEnabled(True)
            self._scrivi(campo, "")
        self.manga.setTristate(False)
        self.manga.setChecked(False)

        if len(self.selezione) == 1:
            percorso = self.selezione[0]
            self.vista = self._valori_file(percorso)
            for campo, testo in self._estrazioni(percorso).items():
                if not self.vista.get(campo):
                    self.vista[campo] = testo
                    self.automatici.add(campo)
        elif self.selezione:
            valori = [self._valori_file(p) for p in self.selezione]
            for campo in CAMPI:
                insieme = {v.get(campo, "") for v in valori}
                if len(insieme) == 1:
                    self.vista[campo] = next(iter(insieme))
                else:
                    self.vista[campo] = ""
                    self.diversi.add(campo)
        if self.selezione and not self.vista.get("LanguageISO") and "LanguageISO" not in self.diversi \
                and self.ultima_lingua:
            voce_vuota = all("LanguageISO" not in self.pending.get(p, {}) for p in self.selezione)
            if voce_vuota:
                self.vista["LanguageISO"] = self.ultima_lingua
                self.automatici.add("LanguageISO")
        for campo in CAMPI_TESTO:
            self._scrivi(campo, self.vista.get(campo, ""))
            diverso = campo in self.diversi
            self.caselle[campo].setStyleSheet(COLORE_DIVERSI if diverso else "")
            self.etichette[campo].setText(campo + (" ≠" if diverso else ""))
        if "Manga" in self.diversi:
            self.manga.setTristate(True)
            self.manga.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.manga.setChecked(bool(self.vista.get("Manga")))
        self.legenda.setVisible(bool(self.diversi))
        self.b_cerca.setEnabled(len(self.selezione) == 1)
        self._caricamento = False
        self._mostra_copertina()
        self._aggiorna_anteprime()

    def _mostra_copertina(self):
        percorso = self.selezione[0] if self.selezione else None
        if percorso == self.percorso_copertina:
            return
        self.percorso_copertina = percorso
        self.vista_copertina.imposta(None, "Caricamento copertina..." if percorso else "Nessuna copertina")
        if percorso and not self.lettura_copertina:
            self._leggi_copertina(percorso)

    def _leggi_copertina(self, percorso):
        # Una lettura alla volta: scorrendo la lista in fretta non parte un processo per ogni CBR
        self.lettura_copertina = True

        def fine(dati, _errore):
            self.lettura_copertina = False
            if percorso != self.percorso_copertina:
                if self.percorso_copertina:
                    self._leggi_copertina(self.percorso_copertina)
                return
            immagine = QPixmap()
            if dati and immagine.loadFromData(dati):
                self.vista_copertina.imposta(immagine)
            else:
                self.vista_copertina.imposta(None, "Nessuna copertina")

        in_background(self, lambda: leggi_copertina(percorso), fine)

    # --- estrazione ---

    def _regole_cambiate(self):
        if len(self.selezione) == 1:
            self._caricamento = True
            for campo, testo in self._estrazioni(self.selezione[0]).items():
                if campo not in self.toccati and not self.svuota[campo].isChecked():
                    self._scrivi(campo, testo)
                    self.automatici.add(campo)
            self._caricamento = False
        self._aggiorna_anteprime()

    def invia_estrazione(self):
        if not any(r[0].isChecked() for r in self.regole):
            QMessageBox.information(self, "Estrazione", "Spunta almeno una regola «Copia» prima di inviare.")
            return
        if not self.selezione:
            QMessageBox.information(self, "Estrazione", "Seleziona almeno un fumetto.")
            return
        self._conserva()
        copiati, mancanti, campi = 0, 0, []
        for p in self.selezione:
            estrazioni = self._estrazioni(p)
            if not estrazioni:
                mancanti += 1
                continue
            voce = self.pending.setdefault(p, {})
            for campo, testo in estrazioni.items():
                if testo == self._dati(p).get(campo, ""):
                    voce.pop(campo, None)
                else:
                    voce[campo] = testo
                if campo not in campi:
                    campi.append(campo)
            if not voce:
                del self.pending[p]
            copiati += 1
        self._carica()
        testo = f"Inviato a {copiati} file"
        if campi:
            testo += " (" + ", ".join(campi) + ")"
        if mancanti:
            testo += f" · {mancanti} senza corrispondenza"
        self.stato.setText(testo + ". Ricorda di salvare.")

    # --- anteprime e tag ---

    def _aggiorna_colori_tag(self):
        schema = self.schema.currentText()
        for campo, bottone in self.bottoni_tag.items():
            attivo = f"<{campo}>" in schema
            if bool(bottone.property("variant")) != attivo:
                set_variant(bottone, "success" if attivo else "")

    def inverti_tag(self, campo):
        schema = self.schema.currentText()
        if f"<{campo}>" in schema:
            self.schema.setEditText(togli_tag_schema(schema, campo))
        else:
            self.schema.lineEdit().insert(f"<{campo}>")

    def _valori_nome(self, percorso):
        """I valori per il nome: quelli del file più quelli ancora solo a video."""
        valori = self._valori_file(percorso)
        if percorso in self.selezione:
            valori.update({c: self._leggi(c) for c in self.toccati | self.automatici})
            if self.numera.isChecked() and len(self.selezione) > 1:
                valori["Number"] = str(self.inizio.value() + self.selezione.index(percorso))
        return valori

    def _aggiorna_anteprime(self):
        if self._caricamento:
            return
        self._aggiorna_colori_tag()
        if self.selezione:
            nome = nome_da_schema(self.schema.currentText(), self._valori_nome(self.selezione[0]), self.cifre.value())
            self.anteprima_nome.setText(nome + split_name(self.selezione[0])[1] if nome else "")
        else:
            self.anteprima_nome.setText("(nessun file selezionato)")
        righe = []
        if not any(r[0].isChecked() for r in self.regole):
            righe.append("(nessuna regola attiva)")
        else:
            for p in self.selezione[:100]:
                parti = []
                for attiva, combo, dopo, fino in self.regole:
                    if attiva.isChecked():
                        testo = estrai_dal_nome(split_name(p)[0], dopo.text(), fino.text())
                        if testo is None:
                            testo = "(non trovato)"
                        parti.append(f"{combo.currentText()}: {testo or '(vuoto)'}")
                righe.append("  |  ".join(parti))
            if len(self.selezione) > 100:
                righe.append(f"... e altri {len(self.selezione) - 100} file")
        self.anteprima_regole.setPlainText("\n".join(righe))

    # --- ricerca ---

    def apri_ricerca(self):
        if len(self.selezione) != 1:
            return
        percorso = self.selezione[0]
        finestra = SearchDialog(split_name(percorso)[0], {c: self._leggi(c) for c in CAMPI_TESTO}, self)
        if finestra.exec() and finestra.scelti:
            for campo, valore in finestra.scelti.items():
                if campo in self.caselle:
                    self.svuota[campo].setChecked(False)
                    self._caricamento = True
                    self._scrivi(campo, valore)
                    self._caricamento = False
                    self._toccato(campo)

    # --- salvataggio ---

    def _scritture(self):
        """(cbz, conversioni, campi coinvolti, errori lingua) di ciò che va scritto, senza toccare `pending`."""
        self._conserva()
        modifiche = {p: dict(v) for p, v in self.pending.items()}
        for p in self.selezione:
            voce = modifiche.setdefault(p, {})
            voce.update({c: self._leggi(c) for c in self.automatici})
            if self.numera.isChecked() and len(self.selezione) > 1:
                voce["Number"] = str(self.inizio.value() + self.selezione.index(p))
        cbz, conversioni, coinvolti, errori = {}, {}, set(), []
        for p, valori in modifiche.items():
            valori = dict(valori)
            lingua = valori.get("LanguageISO", "")
            if lingua:
                codice = normalizza_lingua(lingua)
                if codice is None:
                    errori.append(f"{os.path.basename(p)}: «{lingua}»")
                    continue
                valori["LanguageISO"] = codice
            base = self._dati(p)
            # Anche i campi non toccati: un file salvato non deve restare con campi tutti maiuscoli
            completi = {c: togli_maiuscole(c, v) for c, v in {**base, **valori}.items()}
            differenze = {c: v for c, v in completi.items() if v != base.get(c, "")}
            if not differenze:
                continue
            coinvolti.update(differenze)
            if file_status(p) in (1, 3):
                cbz[p] = differenze
            else:
                conversioni[p] = (info_per_conversione(completi), cbz_target(p))
        return cbz, conversioni, coinvolti, errori

    def _occupato(self, occupato):
        self.salvataggio_in_corso = occupato
        for w in (self.b_salva, self.b_rinomina, self.b_cerca, self.b_invia, self.lista):
            w.setEnabled(not occupato)

    def salva(self):
        cbz, conversioni, coinvolti, errori = self._scritture()
        if errori:
            QMessageBox.warning(self, "Lingua non riconosciuta", "\n".join(errori) + "\n\nScrivi il nome "
                                "(es. Italiano) o il codice (es. it). Nessun file è stato scritto.")
            return
        if not cbz and not conversioni:
            self.stato.setText("Nessuna modifica da salvare.")
            return
        totale = len(cbz) + len(conversioni)
        if totale > 1 or conversioni:
            testo = (f"Scrivere le modifiche su {totale} file?\n\nCampi coinvolti: "
                     + ", ".join(sorted(coinvolti, key=CAMPI.index)))
            if conversioni:
                testo += (f"\n\n{len(conversioni)} non sono CBZ: per scrivere le info verranno convertiti in "
                          "CBZ e gli originali andranno nel cestino. Questa finestra si chiuderà.")
            if QMessageBox.question(self, "Salva metadati", testo) != QMessageBox.StandardButton.Yes:
                return
        self._occupato(True)
        self.stato.setText(f"Salvataggio di {len(cbz)} file...")

        def lavoro():
            problemi = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as esecutore:
                futuri = {esecutore.submit(scrivi_cbz, p, v): p for p, v in cbz.items()}
                for futuro in concurrent.futures.as_completed(futuri):
                    if futuro.exception():
                        problemi[futuri[futuro]] = str(futuro.exception())
            return problemi

        in_background(self, lavoro, lambda esito, errore: self._salvato(cbz, conversioni, esito, errore))

    def _salvato(self, cbz, conversioni, problemi, errore):
        problemi = problemi or {}
        if errore:
            problemi = {p: str(errore) for p in cbz}
        self._occupato(False)
        for p in cbz:
            if p not in problemi:
                log.info(f"Info salvate: '{os.path.basename(p)}'")
                self.disco.pop(p, None)
                self.pending.pop(p, None)
        if problemi:
            log.error(f"Info non salvate: {problemi}")
            QMessageBox.warning(self, "Salva metadati", f"Salvati {len(cbz) - len(problemi)} file.\n\n" + "\n".join(
                f"{os.path.basename(p)}: {e}" for p, e in problemi.items()))
        self.stato.setText(f"Salvati {len(cbz) - len(problemi)} file.")
        if conversioni:
            self.conversioni = conversioni
            for p in conversioni:
                self.pending.pop(p, None)
            self.toccati.clear()
            self.automatici.clear()
            self.accept()
            return
        self._carica()

    # --- rinomina ---

    def _ricorda_schema(self, schema):
        recenti = [self.schema.itemText(i) for i in range(self.schema.count()) if self.schema.itemText(i) != schema]
        recenti = ([schema] + recenti)[:SCHEMI_MAX]
        self.schema.blockSignals(True)
        self.schema.clear()
        self.schema.addItems(recenti)
        self.schema.blockSignals(False)
        _settings().setValue("metadati/schemi_recenti", recenti)

    def _piano(self, schema):
        """([(vecchio, nuovo)], errori). Un nome già usato prende un suffisso: mai sovrascrivere."""
        piano, errori, riservati = [], [], set()
        for p in self.selezione:
            nome = nome_da_schema(schema, self._valori_nome(p), self.cifre.value())
            if not nome:
                errori.append(f"{os.path.basename(p)}: il nome risultante è vuoto.")
                continue
            cartella = os.path.dirname(p)
            estensione = split_name(p)[1]
            nuovo = os.path.join(cartella, nome + estensione)
            if nuovo == p:
                continue
            candidato, i = nuovo, 1
            while (os.path.exists(candidato) and not os.path.samefile(p, candidato)) \
                    or os.path.normcase(candidato) in riservati:
                candidato = os.path.join(cartella, f"{nome}_{i}{estensione}")
                i += 1
            riservati.add(os.path.normcase(candidato))
            piano.append((p, candidato))
        return piano, errori

    def rinomina(self):
        if not self.selezione:
            QMessageBox.information(self, "Rinomina", "Seleziona almeno un fumetto.")
            return
        schema = self.schema.currentText().strip()
        if not schema:
            QMessageBox.warning(self, "Rinomina", "Inserisci uno schema di rinomina.")
            return
        self._ricorda_schema(schema)
        self.schema.setEditText(schema)
        self._conserva()
        piano, errori = self._piano(schema)
        if not piano:
            if errori:
                QMessageBox.warning(self, "Rinomina", "\n".join(errori))
            else:
                self.stato.setText("I nomi sono già quelli richiesti.")
            return
        if len(piano) > 1 and not ConfermaRinomina(piano, self).exec():
            return
        fatti = self.on_rename(piano) if self.on_rename else []
        for vecchio, nuovo in fatti:
            riga = self.paths.index(vecchio)
            self.paths[riga] = nuovo
            self.lista.item(riga).setText(os.path.basename(nuovo))
            if vecchio in self.pending:
                self.pending[nuovo] = self.pending.pop(vecchio)
            if vecchio in self.disco:
                self.disco[nuovo] = self.disco.pop(vecchio)
        self.selezione = [dict(fatti).get(p, p) for p in self.selezione]
        self.stato.setText(f"Rinominati {len(fatti)} file.")
        if errori:
            QMessageBox.warning(self, "Rinomina", "\n".join(errori))
        self._aggiorna_anteprime()

    # --- chiusura ---

    def reject(self):
        if self.salvataggio_in_corso:
            return
        self._conserva()
        if self.pending and QMessageBox.question(
                self, "Info e rinomina",
                f"Ci sono modifiche non salvate su {len(self.pending)} file.\nChiudere comunque?"
        ) != QMessageBox.StandardButton.Yes:
            return
        super().reject()

    def _prossimo_file(self, campo):
        righe = [self.lista.row(i) for i in self.lista.selectedItems()]
        prossima = min(righe) + 1 if righe else 0
        if prossima < self.lista.count():
            self.lista.setCurrentRow(prossima)        # sostituisce la selezione e salva a video
            casella = self.caselle[campo]
            casella.setFocus()
            casella.selectAll()
