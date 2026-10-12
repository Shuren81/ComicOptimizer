### 📚 ComicOptimizer v2.8.0

La soluzione definitiva per la gestione, riparazione e ottimizzazione della tua libreria di fumetti digitali.

Sviluppato con passione da **Michele** *"Shuren"* **Bancheri**, ComicOptimizer nasce dall'esigenza di trasformare collezioni disordinate e pesanti in librerie fluide, standardizzate e pronte per qualsiasi lettore.

### 🆕 Novità

**v2.8.0: codice riorganizzato.** Il programma ora è diviso in più moduli (vedi [Struttura del progetto](#-struttura-del-progetto)) invece che in un unico file enorme. Il funzionamento non cambia, ma sviluppare e correggere diventa più semplice.

**v2.7: nuova interfaccia.** Pulsanti arrotondati, barre di scorrimento sottili e uno stile uniforme in tutta l'app. La barra in alto si adatta ai pulsanti visibili, il pulsante "Analizza" è stato rimosso (l'analisi parte da sola) e nel log il pulsante di salvataggio si chiama semplicemente "Salva".

**v2.6: più sicuro e più veloce.**

* **Originali al sicuro:** il nuovo CBZ viene verificato (integrità e numero di pagine) prima di toccare l'originale, che viene spostato nel cestino invece di essere cancellato.
* **Nessuna pagina persa:** le pagine molto leggere (bianche, crediti, WebP semplici) non vengono più scartate.
* **Metadati conservati:** il file ComicInfo.xml resta nell'archivio (utile per Komga, Kavita, YACReader...).
* **Conversione WebP su più core:** molto più veloce sulle raccolte grandi. Le pagine già in WebP non vengono ricompresse e, se il WebP pesa più dell'originale, la pagina resta com'è.
* **PDF migliori e più veloci:** le pagine-scansione vengono estratte nella qualità originale; le altre vengono renderizzate in JPEG (molto più leggero del vecchio PNG). I PDF lunghi usano più core.
* **Duplicati per contenuto:** riconosciuti anche con nomi diversi.
* **Fine lavoro:** riepilogo con spazio risparmiato e tempo impiegato, notifica di sistema e suono (disattivabili con "🔔 Avvisi").
* **Windows e Linux:** eseguibile per Windows (7-Zip incluso) e AppImage per Linux, compilati automaticamente.

Il dettaglio completo è in [CHANGELOG.md](CHANGELOG.md).

### 🚀 Cosa c'è di nuovo nella v2.0+

La **versione 2.0** segna un punto di svolta per il progetto:

* **Supporto PDF Nativo:** Conversione fluida da PDF a CBZ con estrazione immagini ad alta fedeltà.
* **Motore Turbo:** Gestione della memoria ottimizzata e velocità di elaborazione raddoppiata.
* **Interfaccia Asincrona:** Grazie a un sistema di threading avanzato, l'UI rimane reattiva anche durante la scansione di migliaia di file.
* **Gestione Conflitti:** Sistema intelligente per decidere se sovrascrivere, rinominare o saltare file esistenti.

### ✨ Funzionalità Principali

***🛠️ Standardizzazione Universale***

* **Conversione Totale:** Importa .pdf, .cbr, .rar, .zip e trasformali istantaneamente nello standard .cbz.
* **Ottimizzazione WebP:** Riduci drasticamente il peso della tua collezione senza sacrificare la qualità visiva.
* **Sanificazione Archivi:** Eliminazione automatica di file "spazzatura" come .DS_Store, __MACOSX o file temporanei.

### 🧠 Intelligenza e Controllo

* **Analisi Duplicati:** Riconosce come doppioni i file con lo stesso nome (es. .cbr e .cbz) e gli archivi con contenuto identico (stesso numero di pagine e stesse dimensioni delle immagini), anche se hanno nomi diversi. L'analisi parte in automatico quando aggiungi i file.
* **Advanced Editor:** Un editor visuale integrato per riordinare pagine, eliminare scansioni errate o aggiungere nuove immagini a un archivio esistente.
* **Integrazione di Sistema:** Duplicati e originali sostituiti finiscono nel cestino di sistema (send2trash, con gio trash come riserva su Linux).

### 📥 Download

Gli eseguibili si scaricano dalla pagina [Releases](https://github.com/Shuren81/ComicOptimizer/releases).

#### 🪟 Windows

Scarica lo zip **ComicOptimizer-…-windows.zip**, estrai TUTTA la cartella e avvia `ComicOptimizer.exe`. 7-Zip è già incluso, non serve installare nulla.

Al primo avvio Windows può mostrare l'avviso "Windows ha protetto il PC" perché l'eseguibile non è firmato: clicca **Ulteriori informazioni → Esegui comunque**.

Il log su Windows si trova in `%LOCALAPPDATA%\ComicOptimizer\comicoptimizer.log`.

#### 🐧 Linux (AppImage)

Scarica il file `.AppImage`, rendilo eseguibile e avvialo:

```bash
chmod +x ComicOptimizer-*.AppImage
./ComicOptimizer-*.AppImage
```

Per leggere i RAR servono `p7zip-full` e `unrar` (vedi sotto).

Gli eseguibili vengono compilati automaticamente da GitHub Actions (`.github/workflows/build.yml`) ad ogni nuova Release.

### 📦 Installazione e Requisiti (Linux / da sorgente)

**1. Dipendenze di Sistema (Linux/Ubuntu/Mint)**

Per gestire gli archivi e i file PDF, apri il terminale e installa:

```bash
sudo apt update
sudo apt install p7zip-full unrar
```

**2. Dipendenze Python**

Installa le librerie necessarie tramite pip, dalla cartella del progetto:

```bash
pip install -r requirements.txt
```

(oppure, a mano: `pip install PyQt6 Pillow pymupdf send2trash`)

### 🛠️ Utilizzo Rapido

* **Avvio:** esegui `python3 main.py` dalla cartella del progetto.
* **Importazione:** trascina i tuoi file o cartelle direttamente nella "Drop Zone" dell'app (i file con estensioni non supportate non vengono importati).
* **Analisi:** viene effettuata in automatico. Ogni fumetto mostra il suo stato: da sistemare, ok, riparato, convertito, duplicato o danneggiato.
* **Selezione:** clicca sulle card per selezionarle (Ctrl e Shift supportati). Con una selezione compaiono "Sistema selezionati" e "Cestina selezionati".
* **Ottimizzazione:** scegli se riparare i file (uniformare i numeri di pagina e convertire in .CBZ) o convertire le pagine in WebP per risparmiare spazio.
* **Ordinamento pagine:** per ogni file è possibile modificare l'ordine delle pagine, aggiungerne di nuove e/o rimuoverne. I numeri di pagina vengono adeguati. Le nuove pagine caricate vengono inserite in fondo: **ricordati di spostarle manualmente nella posizione preferita**.
* **Log:** il pulsante "Log" (o il tasto `L`) apre la finestra del log, con filtro per livello, ricerca e pulsante "Salva".

### 🧩 Struttura del progetto

```
main.py                   punto di avvio
comicoptimizer/
  config.py               versione, costanti, percorsi (APP_VERSION si cambia qui)
  logsetup.py             log su file, console e finestra di log
  utils.py                cestino, 7z/unrar, nomi, cartelle temporanee, formattazione
  pdf.py                  supporto PDF (PyMuPDF)
  archives.py             lettura, controllo ed estrazione degli archivi
  images.py               preparazione e conversione delle pagine (WebP...)
  cbz.py                  creazione e verifica dei CBZ, ComicInfo.xml
  workers.py              thread di lavoro (importazione, analisi, elaborazione...)
  style.py                foglio di stile (QSS)
  dialogs.py              finestra di log, finestra di interruzione, widget generici
  card.py                 card di un fumetto nella griglia
  editor.py               editor avanzato delle pagine
  main_window.py          finestra principale
  app.py                  avvio dell'applicazione Qt
.github/workflows/        compilazione automatica (Windows e AppImage)
```

Per compilare a mano un eseguibile: `pip install pyinstaller` e poi `pyinstaller main.py --onedir --name ComicOptimizer --add-data "comicoptimizer.png:."` (su Windows il separatore di `--add-data` è `;`). I comandi completi sono in `.github/workflows/build.yml`.

### 🛡️ Privacy e Sicurezza

**100% Locale:** Nessun dato o immagine viene caricato su server esterni. Tutto avviene sul tuo PC.

**Resilienza:** Se interrompi un'operazione, i tuoi file originali rimangono intatti: vengono spostati nel cestino solo dopo che il nuovo archivio è stato creato e verificato. Le cartelle temporanee vengono sempre ripulite.

### ☕ Sostieni il progetto

ComicOptimizer è gratuito. Se ti è utile, puoi lasciare una mancia con il pulsante *Sponsor* di GitHub, su [Ko-fi](https://ko-fi.com/shuren81) o su [PayPal](https://paypal.me/MicheleBancheri).

### ✍️ Note dell'Autore

"ComicOptimizer nasce per mettere ordine nel caos digitale. 

Un ringraziamento speciale a mia moglie, la scrittrice [Keyla Damaer](https://keyladamaer.com/), per il suo supporto costante."

### 🤖 Ringraziamenti all'IA

Questo progetto è stato scritto con l'aiuto dell'intelligenza artificiale, e non c'è niente da nascondere:

* **Gemini** ha accompagnato le prime versioni, rispondendo alle domande esistenziali sul codice alle tre di notte.
* **Claude** (Anthropic) ha scritto, riscritto e testato buona parte del codice dalla 2.6 in poi: correzioni, conversione WebP su più core, PDF più veloci, nuova interfaccia, versioni per Windows e Linux e la divisione in moduli. Ha anche cancellato senza lamentarsi una funzione intera, quando abbiamo cambiato idea.

Le idee, le decisioni e i collaudi sono di Michele: l'IA scrive il codice e ogni tanto da qualche suggerimento.

***Creato con ❤️ per i collezionisti di fumetti.***
