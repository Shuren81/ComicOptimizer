"""Avvio dell'applicazione."""

import os
import sys

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import config
from .config import APP_VERSION, RES_DIR
from .logsetup import LOG_PATH, log
from .main_window import MainWindow
from .style import STYLESHEET
from .utils import cleanup_stale_temp


_showing_error = False


def _on_unexpected_error(etype, value, tb):
    """Errore non previsto in un comando: nel log e in un messaggio, e l'app resta aperta
    (senza questo, PyQt6 chiude tutto di colpo con "core dump")."""
    global _showing_error
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    log.critical(f"Errore non previsto: {value}", exc_info=(etype, value, tb))
    app = QApplication.instance()
    # il messaggio solo dal thread dell'interfaccia, e uno alla volta
    if app is None or QThread.currentThread() is not app.thread() or _showing_error:
        return
    _showing_error = True
    try:
        QMessageBox.critical(QApplication.activeWindow(), "ComicOptimizer — errore",
                             f"Errore non previsto: il comando è stato interrotto.\n\n{etype.__name__}: {value}"
                             f"\n\nDettagli nel log:\n{LOG_PATH}")
    finally:
        _showing_error = False


def main():
    sys.excepthook = _on_unexpected_error
    app = QApplication(sys.argv)
    app.setApplicationName("ComicOptimizer")
    app.setApplicationVersion(APP_VERSION)
    cleanup_stale_temp()

    # setDesktopFileName va chiamato solo quando si gira come AppImage
    # (o con un .desktop file effettivamente installato), altrimenti
    # causa l'errore "Could not register app ID" sul portal D-Bus di freedesktop.
    _appdir = os.environ.get('APPDIR', '')
    if _appdir:
        # Dentro AppImage: usa il nome del .desktop file incluso nel bundle
        app.setDesktopFileName('comicoptimizer')

    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f'Shuren.ComicOptimizer.{APP_VERSION}')
        except Exception:
            pass

    base_path = _appdir or RES_DIR
    icon_path = os.path.join(base_path, "comicoptimizer.png")
    if os.path.exists(icon_path):
        config.APP_ICON_PATH = icon_path
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon.fromTheme("applications-graphics"))

    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window,          QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.WindowText,      Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base,            QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase,     Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText,     Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text,            Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button,          QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ColorRole.ButtonText,      Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText,      Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link,            QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.Highlight,       QColor(0, 229, 255))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    try:
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        log.critical(f"Errore critico: {e}", exc_info=True)
        if sys.stdout:
            print(f"Errore critico: {e}")
        QMessageBox.critical(None, "ComicOptimizer — errore critico",
                             f"{e}\n\nDettagli nel log:\n{LOG_PATH}")
