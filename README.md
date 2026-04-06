### 📚 ComicOptimizer v2.1.5

La soluzione definitiva per la gestione, riparazione e ottimizzazione della tua libreria di fumetti digitali.

Sviluppato con passione da **Michele "Shuren" Bancheri**, ComicOptimizer nasce dall'esigenza di trasformare collezioni disordinate e pesanti in librerie fluide, standardizzate e pronte per qualsiasi lettore.

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

* **Analisi Duplicati:** Algoritmo che confronta metadati e conteggio pagine per identificare doppioni inutili.
* **Advanced Editor:** Un editor visuale integrato per riordinare pagine, eliminare scansioni errate o aggiungere nuove immagini a un archivio esistente.
* **Integrazione di Sistema:** Gestione sicura degli scarti tramite gio trash, ottimizzata specificamente per Linux Mint.

### 📦 Installazione e Requisiti

**1. Dipendenze di Sistema (Linux/Ubuntu/Mint)**

Per gestire gli archivi e i file PDF, apri il terminale e installa:

```bash

sudo apt update
sudo apt install p7zip-full unrar
```

### 2. Dipendenze Python

Installa le librerie necessarie tramite pip:

```bash

pip install PyQt6 Pillow pymupdf
```

### 🛠️ Utilizzo Rapido

* Avvio: Esegui lo script con python3 main.py.
* Importazione: Trascina i tuoi file o cartelle direttamente nella "Drop Zone" dell'app. (file con estensioni non supportate non verranno importati)
* Analisi: L'analisi viene effettuata in automatico. 
* Ottimizzazione: Scegli se riparare i file (uniformare i numeri di pagina e convertire in .CBZ) o convertire le pagine in WebP per risparmiare spazio.
* Ordinamento pagine: Per ogni file è possibile modificare l'ordinamento delle pagine, aggiungerne di nuove e o rimuoverne. I numeri di pagina vengono adeguati. Le nuove pagine caricate, vengono inserite in fondo, **ricordati di spostarle manualmente nella posizione preferita**

### 🛡️ Privacy e Sicurezza

**100% Locale:** Nessun dato o immagine viene caricato su server esterni. Tutto avviene sul tuo PC.

**Resilienza:** Gestione sicura dei processi: se interrompi un'operazione, i tuoi file originali rimangono intatti fino alla corretta creazione del nuovo archivio.


### ✍️ Note dell'Autore

"ComicOptimizer nasce per mettere ordine nel caos digitale. Un ringraziamento speciale a mia moglie, la scrittrice [Keyla Damaer](https://keyladamaer.com/), per il supporto costante, e a Gemini per l'assistenza tecnica nel perfezionamento del codice."

***Creato con ❤️ per i collezionisti di fumetti.***
