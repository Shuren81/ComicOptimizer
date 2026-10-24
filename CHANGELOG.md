# Changelog

## [3.2.0] — 2026-10-24

### Info del fumetto (ComicInfo.xml)
- **Nuovo:** pulsante **INFO** (compare con una selezione) e finestra "Info del fumetto": una riga per fumetto con Serie, Numero, Titolo, Anno, Autore, Editore, Edizione, Lingua e Manga, da scrivere nel file ComicInfo.xml che Komga, Kavita e YACReader leggono.
- **Nuovo:** le celle si riempiono da sole: dal ComicInfo.xml già presente nel fumetto (CBZ e cartelle) o, se non c'è, dal nome del file con le stesse regole della Rinomina. Doppio click per cambiare una cella; le caselle in alto (con 🔍 Cerca per l'autore) valgono per le righe selezionate o per tutte.
- **Nuovo:** il nome dalle info: con uno Schema (gli stessi schemi pronti e recenti della Rinomina) il fumetto prende anche il nome nuovo, costruito dai valori della tabella. Info e nome si salvano insieme.
- **Nuovo:** nella Rinomina, il pulsante **Info…** porta le righe selezionate (con le marcature e le caselle) nella finestra Info.
- **Cambiato:** `<tit>` e `<sott>` automatici non prendono più i pezzi che sono solo un'etichetta di numero (`Ch.`, `Cap.`, `Vol.`…; una lettera sola solo col punto, così "V" di *V for Vendetta* resta un titolo): in `Juujika no Rokunin (Shiryuu Nakatake) Ch. 015` il sottotitolo non è più "Ch.".
- **Nuovo:** l'Anno deve essere di 4 cifre (in ComicInfo è un numero), altrimenti la riga è rossa; la Lingua si può scrivere anche per esteso (Italiano, English, Giapponese…) e diventa il codice standard.
- **Nuovo:** "Applica alle selezionate" è istantaneo anche con centinaia di righe, e il riepilogo di fine lavoro dice "salvati con le info".
- **Nuovo:** "Salva" usa la procedura sicura di "Solo Ripara": pagine copiate senza ricompressione, nuovo CBZ verificato, originale nel cestino. CBR, PDF e cartelle diventano CBZ. Gli altri campi del ComicInfo.xml (trama, disegnatore…) restano; la lingua diventa il codice standard (ITA → it, ENG → en…). Le righe già uguali al file ("invariato") non vengono riscritte.

## [3.1.0] — 2026-10-21

### Sicurezza e stabilità
- **Corretto:** l'exe per Windows non partiva ("No such file or directory … pymupdf\layout\…") se compilato con PyMuPDF 2.0, uscita da poco: `requirements.txt` resta sotto la 2.0, e se PyMuPDF non funziona l'app parte lo stesso con i PDF disattivati.
- **Corretto:** su Windows, per i file su un disco di rete (NAS, unità mappata, `\\server\…`) "spostare nel cestino" li cancellava per sempre, in silenzio, perché lì il cestino non c'è. Ora quei file non vengono toccati: dopo una conversione l'originale resta dov'è, e "Cestina"/"Pulisci duplicati" li lasciano al loro posto.
- **Corretto:** un file senza permesso di lettura bloccava l'importazione su "Importazione…": ora viene saltato.
- **Corretto:** salvare dall'editor un fumetto senza pagine lo sostituiva con un CBZ vuoto: ora è un errore e l'originale resta com'è.
- **Corretto:** un errore imprevisto nella preparazione di un fumetto o nell'apertura dell'editor (disco pieno, `ComicInfo.xml` illeggibile…) lasciava l'app "occupata" per sempre: ora quel fumetto viene saltato o compare un messaggio.
- **Corretto:** nell'editor, due immagini aggiunte con lo stesso nome (o `01.png` e `01.jpg`) diventavano la stessa pagina e una andava persa.
- **Cambiato:** se il cestino non è disponibile per più file, un solo messaggio con l'elenco (prima una finestra per file, con un consiglio sbagliato su `send2trash`); i file restano al loro posto.
- **Cambiato:** la finestra "Novità" descrive le funzioni della 3.x.

### Rinomina: marcatura dei pezzi del nome
- **Nuovo:** riquadro col nome del fumetto (la riga selezionata o l'ultima cliccata) sopra lo Schema. Selezioni col mouse un pezzo del nome e col tasto destro dici cos'è: Titolo, Numero, Anno, Autore, Editore, Edizione, Lingua, oppure P1, P2… (il successivo libero o un numero a scelta). Si marca esattamente il testo selezionato, a parole intere (una parola presa per più di metà conta): se è solo una parte di un pezzo, il pezzo si divide lì da solo. I gruppi tra parentesi, come `(Shiryuu Nakatake)`, sono pezzi a sé. Ogni pezzo ha uno sfondo più chiaro e in cima al menu compare il testo che verrà marcato.
- **Nuovo:** la marcatura è una regola per tutti i file della finestra, basata sulla posizione del pezzo ("il terzo pezzo"), non sulle lettere: funziona anche con titoli di lunghezza diversa. I file con una struttura diversa (pezzi in più o in meno) diventano rossi con "⚠ schema non applicabile" e non vengono rinominati.
- **Nuovo:** marcando un pezzo, il suo segnaposto entra nello Schema dove c'è il cursore (al posto di `<nome>` se lo schema è solo quello); poi lo sposti o lo cancelli come sempre.
- **Nuovo:** segnaposto `<tit>` (anche `<titolo>`): il pezzo marcato come Titolo o, senza marcature, il primo pezzo di testo del nome (senza i gruppi tra parentesi: `Batman 050 (2016)` → `Batman`).
- **Nuovo:** nel menu anche "Ignora" (toglie il ruolo), "Unisci" (più pezzi diventano uno) e "Dividi" (la selezione diventa un pezzo a sé, senza ruolo), più "Azzera marcature", anche come pulsante.
- **Nuovo:** ogni ruolo ha un colore (palette leggibile anche dai daltonici) e una sottolineatura propria; il testo non marcato è grigio. La legenda sotto il riquadro mostra i ruoli marcati e il loro segnaposto.
- **Nuovo:** Autore, Editore, Edizione e Lingua: se il pezzo marcato c'è nel nome vince quello; se in un file non c'è, si usa la casella sotto (il valore scritto a mano o trovato con 🔍 non viene sovrascritto). Le parentesi attorno al pezzo si tolgono: `(1986)` → `1986`, `[ITA]` → `ITA`.
- **Cambiato:** senza marcature tutto funziona come prima (schemi recenti compresi); con delle marcature, i segnaposto dei ruoli non marcati restano automatici. Le marcature restano cambiando le righe selezionate; si azzerano cambiando "Dividi anche ai numeri" e dopo "Rinomina".
- **Corretto:** uscendo dal "nome singolo" (una sola riga selezionata) con dei segnaposto nello Schema, la riga teneva lo schema scritto (es. `<tit>`) invece del nome calcolato.
- **Nuovo:** l'Aiuto (F1) spiega la marcatura con un esempio passo per passo.
- **Cambiato:** gli schemi pronti nel menu a tendina diventano tre: Manga `<aut> - <tit> - Cap #<num>`, Graphic novel `<aut> - <tit> (<anno>) (<lang>)`, Serie americane `<tit> (<anno>) - #<num> - <sott> (<lang>)`. L'Aiuto ("Come conviene chiamare i file") usa questi tre.
- **Nuovo:** segnaposto `<sott>` (anche `<sottotitolo>`): il pezzo marcato come Sottotitolo o, senza marcature, l'ultimo pezzo di testo dopo il titolo (senza i gruppi tra parentesi); nel menu del tasto destro c'è il ruolo "Sottotitolo".
- **Corretto:** crash della finestra Rinomina dopo "Rinomina" con delle righe selezionate: la tabella cercava i file con i nomi vecchi. Se un file sparisce davvero (spostato o cancellato fuori dall'app) la riga è rossa con "⚠ file non trovato" e non viene rinominata.
- **Nuovo:** un errore non previsto non chiude più l'app di colpo: viene scritto nel log e mostrato in un messaggio, e il programma resta aperto.
- **Nuovo:** pulsante 🧹 accanto allo Schema: svuota gli schemi recenti (con conferma), nel menu restano solo i predefiniti.

## [3.0.0] — 2026-10-14

### Rinomina
- **Nuovo:** si possono rinominare i fumetti direttamente dall'app: doppio click sul nome nella card, tasto **F2** o pulsante "Rinomina selezionati" (compare con almeno un fumetto selezionato).
- **Nuovo:** finestra "Rinomina" con anteprima: una riga per fumetto (ordine naturale), con il nome attuale e il nuovo nome, modificabile a mano cella per cella.
- **Nuovo:** schema del nome libero, con i segnaposto `<nome>` (nome attuale), `<num>` (il numero già presente nel nome, uniformato nelle cifre: ideale per numerazioni sparse), `<n>` (numero progressivo) e `<p1>`, `<p2>`… (i pezzi del nome separati da " - ", per i nomi con più titoli e numeri). Esempio: `<p1> - #<num> - <p3>`.
- **Nuovo:** tasti "_ → spazio", "Iniziali Maiuscole" (senza abbassare le sigle come DC) e Cerca/Sostituisci, sulle righe selezionate o su tutte.
- **Cambiato:** le parti (`<p1>`, `<p2>`…) si dividono anche ai numeri staccati, anche con `#` davanti: "titolo 43 sottotitolo" → titolo · 43 · sottotitolo. Il numero attaccato a una parola (`X-Men2`) non divide; per nomi come "Fantastici 4" si toglie la spunta a "Dividi anche ai numeri". Una parte fatta solo di cifre prende le "Cifre" scelte (43 → 043).
- **Cambiato:** la colonna "Nuovo nome" si aggiorna in tempo reale, anche mentre si scrive in Cerca/Sostituisci (il pulsante "Sostituisci" non serve più). "_ → spazio" e "Iniziali Maiuscole" diventano interruttori (acceso/spento). Le correzioni a mano restano fisse anche cambiando schema o tasti; svuotando la cella torna il nome automatico.
- **Nuovo:** in "Sostituisci con", `*` e `?` rimettono il testo trovato dai jolly di Cerca, nello stesso ordine: Cerca `[*]` e Sostituisci `*` toglie solo le parentesi e tiene il testo (`Titolo [ testo ] 2` → `Titolo testo 2`); `* - *` → `* (*)` scambia i pezzi.
- **Nuovo:** jolly in Cerca: `?` = un carattere, `*` = qualsiasi testo (es. `(*)` toglie ogni gruppo tra parentesi), con la casella "Maiuscole/minuscole", come nel rinomina file di Mint.
- **Nuovo:** righe della tabella selezionabili col mouse, come in un file manager: il click seleziona solo quella riga (un altro click sulla stessa la deseleziona), trascinando o con Shift+click si seleziona un intervallo, Ctrl+click e Ctrl+trascina aggiungono o tolgono righe; pulsanti "Tutte" e "Nessuna". Con righe selezionate si rinominano solo quelle (schema, Cerca/Sostituisci e tasti) e il progressivo `<n>` conta solo loro; senza selezione si lavora su tutte.
- **Nuovo:** con una sola riga selezionata, lo Schema mostra direttamente il suo nome (come quando si rinomina un solo file): si scrive quello nuovo e vale solo per quella riga. Selezionando altro, il nome scritto resta su quella riga come correzione a mano e torna lo schema di prima.
- **Nuovo:** il campo Schema ricorda gli ultimi 10 schemi usati (menu a tendina), anche dopo aver chiuso l'app. Nel menu ci sono anche tre schemi pronti: serie (`<p1> #<p2>`), una storia per numero (`<p1> #<p2> - <p3>`) e testate contenitore con storie a volumi (`<p1> #<p2> - <p3> (Vol. <p4:1>)`).
- **Cambiato:** segnaposto più corti: `<p1>`, `<p2>`… (parti), `<aut>` (autore), `<pub>` (editore), `<edz>` (edizione), `<lang>` (lingua). Le forme lunghe di prima (`<parte1>`, `<autore>`…) funzionano ancora, così gli schemi già salvati restano validi.
- **Corretto:** un numero tra quadre, come in `Y L'ultimo Uomo [01] Senza Uomini`, non divideva le parti (risultava "parte 2 mancante"). Ora divide come un numero staccato; quelli tra parentesi tonde (anni, etichette) no.
- **Nuovo:** pulsante **🔍 Cerca** accanto ad Autore: cerca online gli autori dal titolo del fumetto (ricavato dal nome del file, modificabile) su **Wikidata** (titoli italiani, inglesi e originali; manga, comics e fumetti italiani) e **AniList** (manga), e riempie la casella con il risultato scelto. Viene inviato solo il titolo, e solo premendo il pulsante: l'informativa Privacy è aggiornata.
- **Cambiato:** dopo "Rinomina" la finestra resta aperta per altri passaggi: i nomi attuali si aggiornano, lo Schema torna `<nome>` e Cerca/Sostituisci e interruttori si azzerano (le caselle Autore, Editore, Edizione, Lingua restano). "Annulla" diventa "Chiudi"; "Annulla rinomina" annulla tutti i passaggi fatti nella finestra.
- **Nuovo:** caselle **Autore**, **Editore**, **Edizione** e **Lingua** nella finestra Rinomina, da inserire nello schema con `<aut>`, `<pub>`, `<edz>`, `<lang>` (es. `Berserk (Kentaro Miura) (Panini) Vol. 03 [ITA]`). Se lo schema usa una casella vuota la riga diventa rossa.
- **Nuovo:** segnaposto `<anno>`: l'anno a 4 cifre presente nel nome, preferito quello tra parentesi (`Absolute Batman 024 (2024) (Digital)` → `2024`).
- **Cambiato:** sette schemi pronti nel menu, ognuno con la descrizione del tipo di fumetto (es. "Manga a volumi · <p1> (<aut>) Vol. <p2:2>"; nel campo entra solo lo schema): manga a volumi (`<p1> (<aut>) Vol. <p2:2>`), manga a capitoli (`<p1> (<aut>) Ch. <p2>`), manga in edizione completa (`<p1> (<aut>) (<pub>) Vol. <p2:2> [<lang>]`), comics americani (`<p1> (<anno>) (<aut>) #<p2>`, anche con ` - <p3>` per il sottotitolo), una storia per numero e contenitori (questi due senza autore, che cambia da un numero all'altro). L'Aiuto spiega come conviene chiamare i file e organizzare le cartelle (una cartella per serie) per Komga, Kavita e YACReader.
- **Nuovo:** cifre per singolo segnaposto: `<num:4>` → 0045, `<p4:1>` → 2 (`:1` = il numero così com'è). Senza `:` valgono le "Cifre" del campo.
- **Nuovo:** nell'Aiuto della rinomina, la sezione "Come conviene chiamare i file": testata, `#` e numero a 3 cifre, titolo della storia dopo " - ", anno solo se serve, niente etichette; con esempi per serie, storie e contenitori.
- **Nuovo:** pulsante "Annulla rinomina" nella finestra principale: rimette i nomi di prima ai fumetti dell'ultima rinomina, senza mai sovrascrivere. Sparisce dopo un nuovo lavoro o con "Pulisci lista".
- **Corretto:** il pulsante della rinomina mostrava "Rinomina <n> di …" invece del numero dei file.
- **Corretto:** la finestra di aiuto non scorreva e il testo lungo non si leggeva tutto: ora è un'area con la barra di scorrimento, adattata allo schermo.
- **Nuovo:** pulsante "Aiuto" (o tasto F1) con la spiegazione di schema, segnaposto, tasti e righe rosse.
- **Sicurezza:** si cambia solo il nome sul disco (contenuto ed estensione restano uguali); un file esistente non viene mai sovrascritto. Le righe con un problema (nome già esistente, ripetuto, vuoto, numero o parte mancante) sono rosse e non vengono rinominate. La rinomina non è disponibile durante un lavoro in corso.

### Selezione
- **Nuovo:** selezione trascinando il mouse: premi sulla griglia (anche sopra una card) e trascina; le card toccate dal riquadro si aggiungono alla selezione. Con **Ctrl** premuto vengono invece tolte. Vicino al bordo superiore o inferiore la griglia scorre da sola, così si possono selezionare anche le card fuori vista.
- **Nuovo:** pulsante "Seleziona tutto", che diventa "Deseleziona tutto" appena c'è almeno un fumetto selezionato (un click toglie tutta la selezione), **Ctrl+A** per selezionare tutto ed **Esc** per togliere la selezione.
- **Invariato:** il click su una card la seleziona o deseleziona, Shift+click seleziona un intervallo, il doppio click apre l'editor (o la rinomina, sul nome).
- **Cambiato:** la riga con il suggerimento e la frase ironica (e, durante il lavoro, la barra di avanzamento con STOP) ora sta sotto i pulsanti, su una riga tutta sua: non sparisce più quando compaiono molti pulsanti.
- **Nuovo:** dodici nuove frasi ironiche all'avvio.
- **Corretto:** su schermi stretti la griglia mostrava fino a 7 colonne anche se non ci stavano: le ultime card restavano fuori dalla finestra e non si potevano raggiungere. Ora le colonne si adattano alla larghezza dello schermo (sugli schermi larghi non cambia nulla).

### Interfaccia
- **Cambiato:** pulsanti più compatti, così la finestra non si allarga oltre la griglia: "Sistema tutto" e "Sistema selezionati" diventano un solo pulsante **"Sistema"** (con dei fumetti selezionati chiede se sistemare i selezionati o tutti); "Rinomina selezionati", "Unisci selezionati" e "Cestina selezionati" diventano **"Rinomina"**, **"Unisci"** e **"Cestina"** (la spiegazione completa è nel suggerimento al passaggio del mouse).
- **Nuovo:** banner in stile cyberpunk al posto della scritta "ComicOptimizer, by Shuren" (fumetti in PDF, ZIP e RAR che diventano un CBZ ottimizzato). Si adatta alla larghezza della finestra; si rigenera con `tools/make_banner.py`. Incluso negli eseguibili per Windows e Linux.
- **Cambiato:** rimosso il riquadro "Trascina qui i file", che occupava molto spazio. Quando la lista è vuota la scritta compare al centro dello spazio delle card, senza riquadri, e sparisce appena si importano fumetti. I file si possono rilasciare in un punto qualsiasi della finestra; mentre li trascini la scritta e il bordo della griglia si illuminano.
- **Cambiato:** con la lista vuota la schermata è pulita: spariscono i pulsanti in alto, dietro la scritta "Trascina qui i file" compare un disegno al neon fatto solo di contorni (si rigenera con `tools/make_drop_art.py`) e il suggerimento azzurro diventa una frase d'invito ironica. Appena ci sono fumetti tutto torna come prima.
- **Corretto:** con la finestra massimizzata la griglia restava a 7 colonne e il banner piccolo, con molto spazio vuoto. Ora le colonne si adattano a tutta la larghezza (es. 9–10 su uno schermo da 2000 px), la griglia è centrata e il banner si allarga fino alla sua risoluzione piena; ripristinando la finestra torna la larghezza calcolata sulle card.
- **Corretto:** importando i fumetti, lo spazio delle card era di poco troppo basso e compariva la barra di scorrimento anche con una sola fila (la riga dei pulsanti ricompare e il banner è più alto con molte colonne). Ora la finestra si allunga quanto serve per una fila intera; se lo schermo è troppo basso, si abbassa il banner.
- **Corretto:** con pochi fumetti, il doppio click sul nome di una card per rinominarla poteva finire su un'altra zona: al primo click comparivano i pulsanti della selezione, la finestra si allargava e il banner, diventando più alto, spingeva giù le card. Ora il banner segue la larghezza della griglia (non cambia altezza) e la finestra si allarga solo dopo il tempo di un doppio click.
- **Nuovo:** a fine lavoro, chiuso il riepilogo, la lista si pulisce da sola se tutti i fumetti sono "CONVERTITO" (sistemati e in WebP). Se anche uno solo è in un altro stato, la lista resta.

### Compilazione
- **Nuovo:** script per compilare in locale, senza GitHub Actions: `tools/build_appimage.sh` (AppImage, su Linux) e `tools/build_windows.ps1` (exe, su Windows), con le stesse opzioni della compilazione su GitHub.
- **Nuovo:** versione per macOS: `tools/build_macos.sh` crea `ComicOptimizer.app` e un DMG, con 7-Zip incluso (legge anche i RAR). Va lanciato su un Mac; l'app funziona sui Mac con lo stesso processore (Apple Silicon o Intel) e non è firmata (la prima volta: tasto destro → Apri).
- **Corretto:** su macOS l'avviso "Dipendenze mancanti" chiedeva `unrar` e suggeriva `apt`: ora, come su Windows, basta 7-Zip. 7-Zip viene cercato anche con il nome `7zz` e nelle cartelle di Homebrew; il log dell'app per Mac va in `~/Library/Logs/ComicOptimizer`.

### Sicurezza e affidabilità (revisione del codice)
- **Corretto:** si potevano avviare due lavori insieme (per esempio "Fix" su una card mentre era in corso "Sistema tutto"): la risposta a un conflitto di nomi arrivava al lavoro sbagliato e il primo restava bloccato per sempre, fino a un possibile crash alla chiusura. Ora c'è un lavoro alla volta: Fix, Edita, Sistema, Unisci, Rinomina e Cestina chiedono di attendere la fine di quello in corso (anche durante l'estrazione).
- **Corretto:** se il cestino non era disponibile (dischi di rete, alcune chiavette), l'originale veniva cancellato definitivamente. Ora resta al suo posto; nella riparazione "sul posto" di un .cbz il vecchio file viene conservato come `.bak`. Mai cancellazioni definitive.
- **Corretto:** su macOS, se send2trash falliva, il cestino passava per uno script in cui il nome del file finiva dentro il testo: un nome costruito apposta poteva eseguire comandi. Ora il nome viene passato a parte.
- **Nuovo:** trascinando una cartella di immagini con più sottocartelle, l'app chiede conferma prima di farne un unico fumetto (una libreria trascinata per sbaglio diventava un solo CBZ enorme).
- **Migliorato:** dopo ogni lavoro l'analisi ricontrolla solo i file cambiati, non più tutta la lista (con centinaia di fumetti voleva dire minuti di attesa).
- **Migliorato:** le miniature si caricano poche alla volta (quanti sono i core): importando migliaia di CBR non partono più migliaia di processi 7z insieme. Le miniature non riuscite non lasciano più thread in memoria.
- **Corretto:** una cartella di immagini e un CBZ con lo stesso nome non sono più segnati come duplicati (e "Pulisci duplicati" non cestina più la cartella).
- **Cambiato:** lo stato dei fumetti (da sistemare / OK / convertito) è deciso da una sola regola, uguale all'importazione e all'analisi; sparisce il falso errore "check_status error" nel log per le cartelle. Un archivio di formato sconosciuto risulta "da sistemare" invece di "OK".
- **Cambiato:** l'apertura dell'editor usa la stessa estrazione degli altri lavori (circa 70 righe in meno); tolto codice inutilizzato.

### Test
- **Nuovo:** `tests/test_processing.py`: riparazione, WebP, cartelle di immagini, unione, originali al sicuro senza cestino, analisi, un lavoro alla volta, conferma delle cartelle, miniature.
- **Nuovo:** cartella `tests/` con i test automatici della rinomina e della selezione (`venv/bin/python tests/test_rename.py`, `tests/test_selection.py`, `tests/test_layout.py`, `tests/test_platform.py`, `tests/test_processing.py`, `tests/test_online.py`).

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
