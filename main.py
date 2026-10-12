#!/usr/bin/env python3
"""ComicOptimizer — punto di avvio. Il codice vive nel pacchetto `comicoptimizer/`."""
import multiprocessing

from comicoptimizer.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()   # necessario per l'eseguibile (PyInstaller)
    main()
