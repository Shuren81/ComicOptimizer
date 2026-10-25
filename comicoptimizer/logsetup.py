"""Configurazione del log (file + console + finestra di log in-app)."""

import logging
import logging.handlers
import multiprocessing
import os
import sys

from PyQt6.QtCore import QObject
from PyQt6.QtCore import pyqtSignal as _pyqtSignal

from .config import IS_FROZEN, IS_MAC, IS_WIN


def _log_file_path():
    """
    Su Windows e nell'eseguibile il log va in %LOCALAPPDATA%\\ComicOptimizer:
    la cartella corrente potrebbe essere Program Files (non scrivibile).
    Nell'eseguibile su Linux va in ~/.local/state/ComicOptimizer (o $XDG_STATE_HOME),
    non in una cartella visibile nella home; nell'app per Mac in ~/Library/Logs/ComicOptimizer.
    Da sorgente su Linux resta accanto a dove si lancia lo script, come prima.
    """
    if IS_WIN or IS_FROZEN:
        if IS_WIN:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        elif IS_MAC:
            base = os.path.expanduser("~/Library/Logs")
        else:
            base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        folder = os.path.join(base, "ComicOptimizer")
        try:
            os.makedirs(folder, exist_ok=True)
            return os.path.join(folder, "comicoptimizer.log")
        except OSError:
            pass
    return "comicoptimizer.log"

LOG_PATH = _log_file_path()

# --- LOGGING ---
# al massimo 2 MB, più 3 copie (.1 .2 .3): con "Mantieni log" il file non cresce senza limite.
# Solo il processo principale: i processi di lavoro (PDF, WebP) che ruotano lo stesso file
# cancellavano quello in cui scrive l'app, e il log andava perso.
_log_handlers = [] if multiprocessing.parent_process() else [
    logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")]

if sys.stderr:   # nell'exe senza console sys.stderr è None
    _log_handlers.insert(0, logging.StreamHandler())

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers,
)

log = logging.getLogger("ComicOptimizer")

# Le librerie esterne scrivono nel log solo avvisi ed errori, non i loro messaggi di debug
for _lib in ("PIL", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

class _LogEmitter(QObject):
    new_record = _pyqtSignal(str)

class _QtLogHandler(logging.Handler):
    # Il segnale Qt sta in un QObject separato: così l'handler resta un oggetto
    # Python puro e logging.shutdown() alla chiusura non va in errore.
    def __init__(self):
        logging.Handler.__init__(self)
        self._emitter  = _LogEmitter()
        self.new_record = self._emitter.new_record
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.new_record.emit(msg)
        except Exception:
            pass

_qt_log_handler = _QtLogHandler()

log.addHandler(_qt_log_handler)
