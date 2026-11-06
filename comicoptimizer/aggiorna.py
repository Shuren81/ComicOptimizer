"""Controllo della versione su GitHub e aggiornamento dell'AppImage su Linux."""
import os
import re
import shutil
import urllib.request

from .ricerca import USER_AGENT, contesto_ssl, richiesta_json

API_LATEST = "https://api.github.com/repos/Shuren81/ComicOptimizer/releases/latest"


def ultima_release():
    """La release segnata come 'Latest' su GitHub (dict dell'API)."""
    return richiesta_json(API_LATEST, timeout=15)


def numeri(versione):
    return tuple(int(n) for n in re.findall(r"\d+", versione))


def piu_nuova(tag, attuale):
    return numeri(tag) > numeri(attuale)


def appimage_in_uso():
    """Percorso dell'AppImage che sta girando, None se non è un'AppImage."""
    return os.environ.get("APPIMAGE")


def asset_appimage(release):
    return next((a for a in release.get("assets", []) if a["name"].endswith(".AppImage")), None)


def sostituisci_appimage(asset, in_uso):
    """Scarica la nuova AppImage accanto a quella in uso, col nome della release, e toglie la vecchia.
    Il file in uso resta valido finché il programma non si chiude (Linux). Ritorna il nuovo percorso."""
    destinazione = os.path.join(os.path.dirname(in_uso), os.path.basename(asset["name"]))
    nuova = destinazione + ".nuova"
    richiesta = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(richiesta, timeout=60, context=contesto_ssl()) as r, open(nuova, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        with open(nuova, "rb") as f:
            if f.read(4) != b"\x7fELF" or os.path.getsize(nuova) != asset["size"]:
                raise RuntimeError("Il file scaricato è incompleto o non è un'AppImage.")
        os.chmod(nuova, 0o755)
        os.replace(nuova, destinazione)
        if os.path.abspath(destinazione) != os.path.abspath(in_uso):
            os.remove(in_uso)
        return destinazione
    finally:
        if os.path.exists(nuova):
            os.remove(nuova)
