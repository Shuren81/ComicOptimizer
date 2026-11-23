"""Test del comportamento su macOS, simulato (headless, gira su Linux). Uso:

    venv/bin/python tests/test_platform.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def touch_exe(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    os.chmod(path, 0o755)
    return path


def test_find_tool(work):
    from comicoptimizer import utils
    utils.IS_MAC, utils.RES_DIR = True, work
    brew_7zz = touch_exe(os.path.join(work, "brew", "7zz"))
    utils.shutil.which = lambda n: brew_7zz if n == "7zz" else None   # niente "7z" nel PATH

    utils._TOOL_CACHE.clear()
    assert utils.find_tool("7z") == brew_7zz          # 7-Zip di Homebrew/ufficiale: "7zz"
    assert utils.find_tool("unrar") is None
    bundled = touch_exe(os.path.join(work, "bin", "7z"))
    utils._TOOL_CACHE.clear()
    assert utils.find_tool("7z") == bundled            # quello incluso nell'app ha la precedenza


def test_log_path(work):
    from comicoptimizer import logsetup
    logsetup.IS_FROZEN, logsetup.IS_WIN, logsetup.IS_MAC = True, False, True
    os.environ["HOME"] = work
    path = logsetup._log_file_path()
    assert path == os.path.join(work, "Library", "Logs", "ComicOptimizer", "comicoptimizer.log"), path


def test_check_deps():
    import comicoptimizer.main_window as mw
    shown = []
    mw.QMessageBox.warning = lambda parent, title, text: shown.append(text)
    mw.IS_MAC, mw.IS_WIN = True, False
    mw.find_tool = lambda n: "/x/7z" if n == "7z" else None          # unrar assente
    w = mw.MainWindow()
    shown.clear()
    w.check_deps()
    assert shown == [], shown                         # sul Mac unrar non serve
    mw.find_tool = lambda n: None
    w.check_deps()
    assert len(shown) == 1 and "7-Zip" in shown[0] and "brew install sevenzip" in shown[0]
    assert "apt" not in shown[0] and "unrar" not in shown[0]
    w._closing = True


def test_installa_mancanti():
    from comicoptimizer import utils
    from comicoptimizer import main_window as mw
    from comicoptimizer.opzioni import Opzioni
    utils.IS_MAC = utils.IS_WIN = False
    c = lambda *gestori: (lambda n: n in gestori)
    assert utils.comandi_installazione(["7z", "unrar"], [], c("apt", "dnf")) == \
        [["pkexec", "apt", "install", "-y", "p7zip-full", "unrar"]], "il primo gestore presente"
    assert utils.comandi_installazione(["unrar"], [], c("pacman")) == [["pkexec", "pacman", "-S", "--noconfirm", "unrar"]]
    assert utils.comandi_installazione(["7z"], [], c()) is None, "gestore sconosciuto: a mano"
    assert utils.comandi_installazione([], ["send2trash"], c()) == [[sys.executable, "-m", "pip", "install", "send2trash"]]
    utils.IS_MAC = True
    assert utils.comandi_installazione(["7z"], [], c("apt")) is None, "sul Mac niente apt"
    utils.IS_MAC = False

    mancano = [(["unrar"], [])]
    utils.dipendenze_mancanti = lambda: mancano[0]
    w = mw.MainWindow()
    o = Opzioni(w.library)
    assert o.dipendenze.text() == "7z ✓ · unrar ✗ · librerie ✓" and o.installa.isVisibleTo(o)
    mancano[0] = ([], [])
    o._mostra_dipendenze()
    assert not o.installa.isVisibleTo(o), "niente da installare: niente pulsante"

    # scheda «Ricerca online»: le chiavi delle fonti, salvate dove le legge la finestra di ricerca
    from PyQt6.QtCore import QSettings
    from comicoptimizer.config import SETTINGS
    from comicoptimizer.ricerca import FONTI_RICERCA
    assert [o.schede.tabText(i) for i in range(o.schede.count())] == ["Generali", "Ricerca online"]
    assert set(o.chiavi) == {f["chiave_config"] for f in FONTI_RICERCA.values() if f["chiave_config"]}
    o.chiavi["metron_accesso"].setText("  io:segreta ")
    o.accept()
    assert QSettings(*SETTINGS).value("ricerca/metron_accesso") == "io:segreta"
    assert Opzioni(w.library).chiavi["metron_accesso"].text() == "io:segreta"

    # dalla Ricerca online: ✘ e «Inserisci la chiave…» aprono le Opzioni sulla scheda giusta
    from comicoptimizer import metadata_dialog as md
    QSettings(*SETTINGS).setValue("ricerca/fonte", "ComicVine")
    s = md.SearchDialog("Batman 1", {}, w)
    assert s.icona_chiave.text() == "✘" and not s.b_chiave.isHidden()
    aperte = []
    Opzioni.exec = lambda self: aperte.append(self.schede.tabText(self.schede.currentIndex())) or \
        md.salva_chiave("comicvine_api_key", "k") or 0
    s.b_chiave.click()
    assert aperte == ["Ricerca online"] and s.icona_chiave.text() == "✔" and s.b_chiave.isHidden()
    s.combo_fonte.setCurrentText("ComicsBox")
    assert s.icona_chiave.text() == "✔", "fonte senza chiave: pronta"
    w._closing = True


def test_popup_evidenziati(app):
    import time
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QDialog
    from comicoptimizer.style import EvidenziaFinestre
    filtro = EvidenziaFinestre(app)
    app.installEventFilter(filtro)
    d = QDialog()
    d.show()
    QCoreApplication.sendEvent(d, QEvent(QEvent.Type.WindowActivate))
    lampi = []
    for _ in range(120):
        app.processEvents()
        lampi.append(bool(d.property("lampo")))
        time.sleep(0.01)
    assert d.property("attiva") is True, "la finestra attiva ha il bordo colorato"
    assert True in lampi and not d.property("lampo"), "lampeggia e poi si ferma"
    QCoreApplication.sendEvent(d, QEvent(QEvent.Type.WindowDeactivate))
    for _ in range(5):
        app.processEvents()
    assert d.property("attiva") is False
    # finestra distrutta subito dopo l'attivazione: il timer muore con lei, nessun crash
    e = QDialog()
    e.show()
    QCoreApplication.sendEvent(e, QEvent(QEvent.Type.WindowActivate))
    QCoreApplication.sendEvent(e, QEvent(QEvent.Type.WindowDeactivate))
    e.deleteLater()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)
    app.removeEventFilter(filtro)


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        from PyQt6.QtCore import QSettings             # mai le impostazioni vere (librerie, chiavi)
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, os.path.join(work, "cfg"))
        test_find_tool(work)
        test_log_path(work)
        test_check_deps()
        test_installa_mancanti()
        test_popup_evidenziati(app)
    print("TUTTO OK")
