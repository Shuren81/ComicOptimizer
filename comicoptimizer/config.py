"""Costanti e percorsi condivisi da tutta l'applicazione."""

import os
import sys

# --- VERSIONE (unica fonte: usata da titolo, popup e log) ---
APP_VERSION = "3.3.1"

# --- COSTANTI ELABORAZIONE ---
WEBP_QUALITY  = 85       # qualità WebP (0-100)

WEBP_MAX_SIDE = 16383    # limite del formato WebP per lato

PDF_ZOOM      = 2.0      # zoom per le pagine PDF che vanno renderizzate (~144 dpi)

TMP_PREFIX    = "comicopt_"   # prefisso cartelle temporanee (per la pulizia)

APP_ICON_PATH = ""       # impostato all'avvio, usato dalle notifiche di sistema

# --- PERCORSI ---
IS_FROZEN = getattr(sys, "frozen", False)          # True dentro l'eseguibile (PyInstaller)

IS_WIN    = sys.platform == "win32"

IS_MAC    = sys.platform == "darwin"

# Cartella delle risorse incluse (icona, 7z.exe): _MEIPASS nell'exe, altrimenti nella cartella del progetto (sopra il pacchetto comicoptimizer)
RES_DIR   = getattr(sys, "_MEIPASS",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- LAYOUT COSTANTI ---
# Usate sia da ComicCard che da MainWindow per calcolare la larghezza adattiva
CARD_W       = 195   # larghezza fissa di ogni card

CARD_H       = 385   # altezza fissa di ogni card

CARD_SPACING = 15    # spacing tra card nella griglia

CARD_MARGIN  = 15    # margine esterno della griglia

COLS_DEFAULT = 4     # colonne all'avvio

COLS_MAX     = 7     # massimo assoluto di colonne
