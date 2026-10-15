# Changelog

## [3.0.0] — 2026-10-14

### Rinomina
- **Nuovo:** si possono rinominare i fumetti direttamente dall'app: doppio click sul nome nella card, tasto **F2** o pulsante "Rinomina selezionati" (compare con almeno un fumetto selezionato).
- **Nuovo:** finestra "Rinomina" con anteprima: una riga per fumetto (ordine naturale), con il nome attuale e il nuovo nome, modificabile a mano cella per cella.
- **Nuovo:** schema del nome libero, con i segnaposto `<nome>` (nome attuale), `<num>` (il numero già presente nel nome, uniformato nelle cifre: ideale per numerazioni sparse), `<n>` (numero progressivo) e `<parte1>`, `<parte2>`… (i pezzi del nome separati da " - ", per i nomi con più titoli e numeri). Esempio: `<parte1> - #<num> - <parte3>`.
- **Nuovo:** tasti "_ → spazio", "Iniziali Maiuscole" (senza abbassare le sigle come DC) e Cerca/Sostituisci, sulle righe selezionate o su tutte.
- **Nuovo:** pulsante "Aiuto" (o tasto F1) con la spiegazione di schema, segnaposto, tasti e righe rosse.
- **Sicurezza:** si cambia solo il nome sul disco (contenuto ed estensione restano uguali); un file esistente non viene mai sovrascritto. Le righe con un problema (nome già esistente, ripetuto, vuoto, numero o parte mancante) sono rosse e non vengono rinominate. La rinomina non è disponibile durante un lavoro in corso.

### Selezione
- **Nuovo:** selezione trascinando il mouse: premi sulla griglia (anche sopra una card) e trascina; le card toccate dal riquadro si aggiungono alla selezione. Con **Ctrl** premuto vengono invece tolte. Vicino al bordo superiore o inferiore la griglia scorre da sola, così si possono selezionare anche le card fuori vista.
- **Nuovo:** pulsante "Seleziona tutto" (diventa "Deseleziona tutto" quando sono tutti selezionati), **Ctrl+A** per selezionare tutto ed **Esc** per togliere la selezione.
- **Invariato:** il click su una card la seleziona o deseleziona, Shift+click seleziona un intervallo, il doppio click apre l'editor (o la rinomina, sul nome).
- **Cambiato:** la riga con il suggerimento e la frase ironica (e, durante il lavoro, la barra di avanzamento con STOP) ora sta sotto i pulsanti, su una riga tutta sua: non sparisce più quando compaiono molti pulsanti.
- **Nuovo:** dodici nuove frasi ironiche all'avvio.
- **Corretto:** su schermi stretti la griglia mostrava fino a 7 colonne anche se non ci stavano: le ultime card restavano fuori dalla finestra e non si potevano raggiungere. Ora le colonne si adattano alla larghezza dello schermo (sugli schermi larghi non cambia nulla).

### Interfaccia
- **Nuovo:** banner in stile cyberpunk al posto della scritta "ComicOptimizer, by Shuren" (fumetti in PDF, ZIP e RAR che diventano un CBZ ottimizzato). Si adatta alla larghezza della finestra; si rigenera con `tools/make_banner.py`. Incluso negli eseguibili per Windows e Linux.
- **Cambiato:** rimosso il riquadro "Trascina qui i file", che occupava molto spazio. Quando la lista è vuota la scritta compare al centro dello spazio delle card, senza riquadri, e sparisce appena si importano fumetti. I file si possono rilasciare in un punto qualsiasi della finestra; mentre li trascini la scritta e il bordo della griglia si illuminano.
- **Cambiato:** con la lista vuota la schermata è pulita: spariscono i pulsanti in alto, dietro la scritta "Trascina qui i file" compare un disegno al neon fatto solo di contorni (si rigenera con `tools/make_drop_art.py`) e il suggerimento azzurro diventa una frase d'invito ironica. Appena ci sono fumetti tutto torna come prima.
- **Nuovo:** a fine lavoro, chiuso il riepilogo, la lista si pulisce da sola se tutti i fumetti sono "CONVERTITO" (sistemati e in WebP). Se anche uno solo è in un altro stato, la lista resta.

### Compilazione
- **Nuovo:** script per compilare in locale, senza GitHub Actions: `tools/build_appimage.sh` (AppImage, su Linux) e `tools/build_windows.ps1` (exe, su Windows), con le stesse opzioni della compilazione su GitHub.
- **Nuovo:** versione per macOS: `tools/build_macos.sh` crea `ComicOptimizer.app` e un DMG, con 7-Zip incluso (legge anche i RAR). Va lanciato su un Mac; l'app funziona sui Mac con lo stesso processore (Apple Silicon o Intel) e non è firmata (la prima volta: tasto destro → Apri).
- **Corretto:** su macOS l'avviso "Dipendenze mancanti" chiedeva `unrar` e suggeriva `apt`: ora, come su Windows, basta 7-Zip. 7-Zip viene cercato anche con il nome `7zz` e nelle cartelle di Homebrew; il log dell'app per Mac va in `~/Library/Logs/ComicOptimizer`.

### Test
- **Nuovo:** cartella `tests/` con i test automatici della rinomina e della selezione (`venv/bin/python tests/test_rename.py`, `tests/test_selection.py`, `tests/test_layout.py`, `tests/test_platform.py`).

## [2.9.0] — 2026-10-13

### Editor delle pagine
- **Nuovo:** doppio click su una pagina per vederla in grande. Le frecce ← → (da tastiera o con i pulsanti ◀ ▶ accanto al nome del file) passano alla pagina precedente o successiva (nell'ordine attuale dell'editor); Esc o un click fuori chiudono l'anteprima. In basso compaiono la posizione (es. "12 / 163") e il nome del file. La finestra si adatta agli schermi piccoli.

### Cartelle di immagini
- **Nuovo:** una cartella trascinata nell'app che contiene solo immagini (anche dentro sottocartelle) diventa un unico fumetto, con la sua card. "Fix" crea il CBZ con il nome della cartella, accanto ad essa, anche in WebP.
- **Nuovo:** le pagine seguono l'ordine naturale, in profondità: prima le immagini della cartella, poi ogni sottocartella in ordine naturale, e così via; vengono rinumerate di seguito (0001, 0002…). Il log riporta l'elenco delle sottocartelle nell'ordine usato.
- **Nuovo:** se la cartella ha sia immagini sciolte sia sottocartelle, l'app chiede se le immagini sciolte vanno prima o dopo le sottocartelle.
- **Nuovo:** il ComicInfo.xml della cartella principale viene conservato (con `<PageCount>` aggiornato); quelli nelle sottocartelle vengono ignorati.
- **Nuovo:** la cartella originale va nel cestino solo dopo la verifica del nuovo CBZ. Se il cestino non è disponibile la cartella resta al suo posto (mai cancellata definitivamente).
- **Invariato:** le cartelle miste (immagini più PDF, CBZ o altro) si importano come prima: solo i file dentro, le immagini sciolte vengono ignorate. Le cartelle vuote o con sola spazzatura vengono scartate.
- **Cambiato:** anche `Thumbs.db`, `ehthumbs.db` e `desktop.ini` sono considerati spazzatura.

### Unione di fumetti
- **Nuovo:** con almeno due fumetti selezionati compare il pulsante "Unisci selezionati". I fumetti (anche di formati diversi: CBZ, CBR, ZIP, RAR, PDF, cartelle di immagini) vengono uniti in ordine naturale del nome in un unico CBZ, con le pagine rinumerate di seguito.
- **Nuovo:** nella finestra di unione si sceglie il nome (suggerito: la parte comune dei nomi senza il numero del capitolo) e la destinazione (di default la cartella del primo fumetto), poi "Unisci" oppure "Unisci e converti" (WebP).
- **Nuovo:** il nuovo CBZ viene verificato prima di toccare gli originali, che poi vanno nel cestino. Se anche un solo fumetto non si legge, l'unione viene annullata e gli originali restano intatti.
- **Nuovo:** si conserva il ComicInfo.xml del primo fumetto: `<PageCount>` diventa il totale, `<Title>` il nome scelto, `<Pages>` e `<Number>` vengono rimossi.
- **Corretto:** con "Sovrascrivi" su un file già presente nella griglia rimaneva una card in più; ora la griglia mostra una sola card per il file finale.

### Linux
- **Corretto:** nell'AppImage il log veniva creato in una cartella `~/ComicOptimizer`, che restava vuota alla chiusura. Ora va in `~/.local/state/ComicOptimizer` (o in `$XDG_STATE_HOME/ComicOptimizer`). La vecchia cartella vuota si può cancellare a mano.

## [2.8.0] — 2026-10-12

### Struttura del codice
- **Cambiato:** `main.py` (quasi 3000 righe) è stato diviso nel pacchetto `comicoptimizer/`, con un modulo per ogni compito: `config`, `logsetup`, `utils`, `pdf`, `archives`, `images`, `cbz`, `workers`, `style`, `dialogs`, `card`, `editor`, `main_window`, `app`.
- **Invariato:** il comportamento del programma. Il codice è stato solo spostato; i fumetti di prova (CBZ, ZIP, PDF) producono file identici a quelli della 2.7.1, sia in "Solo Ripara" sia in "Converti WebP", anche nell'eseguibile compilato.
- **Invariato:** `main.py` resta il punto di avvio (`python3 main.py`) e il comando di compilazione con PyInstaller non cambia.
- **Cambiato:** l'icona e la cartella `bin` (7-Zip su Windows) si cercano ora nella cartella del progetto, sopra il pacchetto.
- **Nuovo:** la versione si cambia in un solo punto, `comicoptimizer/config.py` (`APP_VERSION`).

## [2.7.1] — 2026-10-08

### Interfaccia
- **Rimosso:** il pulsante "Analizza" dalla barra in alto. L'analisi parte già da sola all'aggiunta dei file, quindi il pulsante era superfluo; si guadagna spazio per gli altri pulsanti.
- **Cambiato:** nella finestra del log il pulsante "Salva su file" ora si chiama "Salva".
- **Nuovo:** una riga in più nei Credits.

## [2.7.0] — 2026-10-08

### Sicurezza dei file
- **Corretto:** le pagine sotto i 5 KB (pagine bianche, crediti, pagine WebP semplici) venivano scartate in silenzio durante la riparazione/conversione, e l'originale veniva poi cancellato. Ora si controlla che siano state estratte *tutte* le pagine previste; se ne manca anche una il file viene saltato e l'originale resta intatto.
- **Corretto:** l'originale veniva cancellato definitivamente *prima* di spostare il nuovo CBZ, senza verificarlo. Ora il nuovo archivio viene verificato (integrità + numero di pagine) e solo dopo l'originale viene spostato nel **cestino**.
- **Corretto:** "Sistema tutto → Converti WebP" riconvertiva anche i fumetti già convertiti, perdendo qualità ad ogni passaggio. Ora sono esclusi, e le singole pagine già in WebP vengono copiate senza ricompressione.
- **Corretto:** ComicInfo.xml veniva perso. Ora viene conservato; `<PageCount>` viene aggiornato e `<Pages>` rimosso se le pagine sono cambiate o sono state riordinate nell'editor.
- **Corretto:** interrompendo il lavoro ("Annulla subito" / "Termina in corso") le cartelle temporanee dei file non ancora elaborati restavano sul disco. Ora vengono sempre eliminate; all'avvio vengono ripulite anche quelle rimaste da sessioni chiuse male.
- **Corretto:** se send2trash non riusciva a cestinare un file (es. dischi di rete) l'app poteva andare in crash. Ora ripiega sul metodo di sistema.


### Conversione immagini
- **Corretto:** le immagini CMYK, a 16 bit o con trasparenza facevano fallire l'intero fumetto. Ora vengono convertite correttamente (trasparenza su sfondo bianco).
- **Corretto:** le pagine più alte/larghe di 16383 px (limite del WebP) facevano fallire il fumetto. Ora restano nel formato originale.
- **Nuovo:** se il WebP pesa più dell'immagine originale, la pagina resta nel formato originale.
- **Nuovo:** una pagina problematica non fa più fallire l'intero fumetto: viene lasciata com'è e segnalata nel log.
- **Nuovo:** conversione WebP **su più core** in parallelo (tutti i core meno uno, per lasciare fluida l'interfaccia).
- **Nuovo:** i CBZ creati riportano un marcatore nel commento dell'archivio, così lo stato "CONVERTITO" è riconosciuto anche se alcune pagine sono rimaste nel formato originale.

### PDF
- **Nuovo:** le pagine-scansione (una sola immagine a tutta pagina, senza testo o disegni vettoriali sopra) vengono estratte nella **qualità originale**.
- **Migliorato:** le altre pagine vengono renderizzate in JPEG invece che in PNG (file molto più leggeri).
- **Migliorato:** uso di `import pymupdf` (il vecchio nome `fitz` è deprecato), con compatibilità per le versioni precedenti.
- **Corretto:** l'estrazione delle pagine-scansione dei PDF con immagini Flate/PNG poteva richiedere circa 2,7 secondi a pagina (16 minuti per 353 pagine). Ora le immagini vengono decodificate direttamente alla risoluzione originale (JPEG qualità 95; le pagine già JPEG sono copiate senza ricodifica; le scansioni a 1 bit restano PNG) e l'estrazione è circa 40 volte più veloce.
- **Migliorato:** il controllo "pagina-scansione o pagina con testo/vettori" usa `get_bboxlog()` (circa 0,1 ms a pagina invece di circa 100 ms).
- **Nuovo:** l'estrazione dei PDF con almeno 16 pagine usa più core in parallelo.
- **Nuovo:** durante la preparazione di un PDF compare l'avanzamento pagina per pagina (es. "Estrazione: nome.pdf (120/353 pagine)") con la barra di progresso.

### Duplicati e coerenza
- **Nuovo:** i duplicati vengono riconosciuti anche per contenuto (stesso numero di pagine e stesse dimensioni delle immagini), non solo per nome. Viene tenuto il .cbz valido con il nome più corto.
- **Corretto:** le estensioni delle pagine erano gestite in due liste diverse (GIF, BMP e TIFF venivano impacchettate ma non contate). Ora la lista è unica.

### Windows
- **Nuovo:** eseguibile per Windows, compilato automaticamente da GitHub Actions ad ogni Release (zip con 7-Zip incluso, nessuna installazione necessaria).
- **Nuovo:** 7z e unrar vengono cercati prima nel pacchetto, poi nel PATH, poi nelle cartelle di installazione standard di Windows. Su Windows basta 7-Zip, che legge anche RAR e RAR5.
- **Corretto:** su Windows ogni estrazione avrebbe aperto per un attimo una finestra di console: ora i programmi esterni partono nascosti.
- **Corretto:** nomi di file con lettere accentate negli archivi letti da 7-Zip su Windows.
- **Corretto:** il log veniva scritto nella cartella corrente (su Windows potenzialmente non scrivibile). Su Windows e nell'eseguibile ora va in `%LOCALAPPDATA%\ComicOptimizer`.
- **Corretto:** percorsi normalizzati all'importazione (evita doppioni nella griglia con i percorsi misti `/` e `\` di Windows).
- **Migliorato:** avviso delle dipendenze mancanti specifico per Windows; errore critico mostrato in una finestra (nell'exe non c'è console).

### Interfaccia
- **Nuovo:** a fine lavoro compare un riepilogo con fumetti elaborati, saltati, errori, spazio risparmiato e tempo impiegato.
- **Nuovo:** notifica di sistema con suono a fine lavoro (disattivabile con la casella "🔔 Avvisi" in basso).
- **Nuovo:** restyle grafico: pulsanti arrotondati con effetto al passaggio del mouse, barre di scorrimento sottili, caselle e barra di avanzamento nello stesso stile. Lo stile è ora in un unico foglio (`STYLESHEET`) invece che scritto pulsante per pulsante.
- **Corretto:** con un solo fumetto i pulsanti della barra in alto venivano tagliati. Ora hanno la larghezza del testo e la finestra si adatta quando compaiono "Sistema selezionati", "Cestina selezionati" e "Pulisci duplicati".
- **Corretto:** versione allineata a 2.7.0 in titolo, popup Novità, README e requirements.
- **Corretto:** errore del sistema di log alla chiusura del programma.
- **Corretto:** il log (terminale e finestra Log) si riempiva di messaggi di debug di Pillow (es. "failed to import FpxImagePlugin: No module named 'olefile'"). Ora le librerie esterne registrano solo avvisi ed errori.
- **Corretto:** su monitor piccoli o a bassa risoluzione, l'editor delle pagine e la finestra del log potevano aprirsi più grandi dello schermo, lasciando i pulsanti in basso (es. "SALVA") fuori dalla parte visibile. Ora si adattano allo schermo disponibile.
- **Corretto:** su schermi molto stretti, alcuni pulsanti della barra in alto o di quella in basso potevano finire fuori dalla finestra. Ora, se non c'è spazio a sufficienza, compare una barra di scorrimento orizzontale per raggiungerli comunque.
