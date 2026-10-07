# Changelog

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
