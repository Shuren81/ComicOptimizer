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


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        test_find_tool(work)
        test_log_path(work)
        test_check_deps()
    print("TUTTO OK")
