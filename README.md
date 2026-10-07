### 📚 ComicOptimizer v2.7.1

La soluzione definitiva per la gestione, riparazione e ottimizzazione della tua libreria di fumetti digitali.

Sviluppato con passione da **Michele** *"Shuren"* **Bancheri**, ComicOptimizer nasce dall'esigenza di trasformare collezioni disordinate e pesanti in librerie fluide, standardizzate e pronte per qualsiasi lettore.

### 🆕 Novità della v2.7.1

* **Originali al sicuro:** il nuovo CBZ viene verificato (integrità e numero di pagine) prima di toccare l'originale, che viene spostato nel cestino invece di essere cancellato.
* **Nessuna pagina persa:** le pagine molto leggere (bianche, crediti, WebP semplici) non vengono più scartate.
* **Metadati conservati:** il file ComicInfo.xml resta nell'archivio (utile per Komga, Kavita, YACReader...).
* **Conversione WebP su più core:** molto più veloce sulle raccolte grandi. Le pagine già in WebP non vengono ricompresse e, se il WebP pesa più dell'originale, la pagina resta com'è.
* **PDF migliori:** le pagine-scansione vengono estratte nella qualità originale; le altre vengono renderizzate in JPEG (molto più leggero del vecchio PNG).
* **Duplicati per contenuto:** riconosciuti anche con nomi diversi.
* **Fine lavoro:** riepilogo con spazio risparmiato e tempo impiegato, notifica di sistema e suono (disattivabili con "🔔 Avvisi").

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

* **Analisi Duplicati:** Riconosce come doppioni i file con lo stesso nome (es. .cbr e .cbz) e gli archivi con contenuto identico (stesso numero di pagine e stesse dimensioni delle immagini), anche se hanno nomi diversi.
* **Advanced Editor:** Un editor visuale integrato per riordinare pagine, eliminare scansioni errate o aggiungere nuove immagini a un archivio esistente.
* **Integrazione di Sistema:** Duplicati e originali sostituiti finiscono nel cestino di sistema (send2trash, con gio trash come riserva su Linux).

### 🪟 Windows

Scarica lo zip **ComicOptimizer-…-windows.zip** dalla pagina [Releases](https://github.com/Shuren81/ComicOptimizer/releases), estrai la cartella e avvia `ComicOptimizer.exe`. 7-Zip è già incluso, non serve installare nulla.

Al primo avvio Windows può mostrare l'avviso "Windows ha protetto il PC" perché l'eseguibile non è firmato: clicca **Ulteriori informazioni → Esegui comunque**.

Il log su Windows si trova in `%LOCALAPPDATA%\ComicOptimizer\comicoptimizer.log`.

L'eseguibile viene compilato automaticamente da GitHub Actions (`.github/workflows/build-windows.yml`) ad ogni nuova Release.

### 📦 Installazione e Requisiti (Linux / da sorgente)

**1. Dipendenze di Sistema (Linux/Ubuntu/Mint)**

Per gestire gli archivi e i file PDF, apri il terminale e installa:

```bash

sudo apt update
sudo apt install p7zip-full unrar
```

### 2. Dipendenze Python

Installa le librerie necessarie tramite pip:

```bash

pip install PyQt6 Pillow pymupdf send2trash
```

### 🛠️ Utilizzo Rapido

* Avvio: Esegui lo script con python3 main.py.
* Importazione: Trascina i tuoi file o cartelle direttamente nella "Drop Zone" dell'app. (file con estensioni non supportate non verranno importati)
* Analisi: L'analisi viene effettuata in automatico. 
* Ottimizzazione: Scegli se riparare i file (uniformare i numeri di pagina e convertire in .CBZ) o convertire le pagine in WebP per risparmiare spazio.
* Ordinamento pagine: Per ogni file è possibile modificare l'ordinamento delle pagine, aggiungerne di nuove e o rimuoverne. I numeri di pagina vengono adeguati. Le nuove pagine caricate, vengono inserite in fondo, **ricordati di spostarle manualmente nella posizione preferita**

### 🛡️ Privacy e Sicurezza

**100% Locale:** Nessun dato o immagine viene caricato su server esterni. Tutto avviene sul tuo PC.

**Resilienza:** Se interrompi un'operazione, i tuoi file originali rimangono intatti: vengono spostati nel cestino solo dopo che il nuovo archivio è stato creato e verificato. Le cartelle temporanee vengono sempre ripulite.


### ✍️ Note dell'Autore

"ComicOptimizer nasce per mettere ordine nel caos digitale. Un ringraziamento speciale a mia moglie, la scrittrice [Keyla Damaer](https://keyladamaer.com/), per il supporto costante, e a Gemini per l'assistenza tecnica nel perfezionamento del codice."

***Creato con ❤️ per i collezionisti di fumetti.***
