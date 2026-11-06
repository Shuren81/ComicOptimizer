"""Test dell'aggiornamento (confronto versioni e sostituzione dell'AppImage). Uso:

    venv/bin/python tests/test_aggiorna.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comicoptimizer import aggiorna


def test_versioni():
    assert aggiorna.piu_nuova("v3.4.1", "3.4.0")
    assert aggiorna.piu_nuova("v3.10.0", "3.9.9")
    assert not aggiorna.piu_nuova("v3.4.0", "3.4.0")
    assert not aggiorna.piu_nuova("v3.1.0", "3.4.0")


def test_sostituzione(work):
    in_uso = os.path.join(work, "ComicOptimizer.AppImage")
    open(in_uso, "wb").write(b"vecchia")
    nuova = os.path.join(work, "scaricata")
    open(nuova, "wb").write(b"\x7fELF nuova")
    import hashlib
    asset = {"name": "ComicOptimizer-v9.0.0-x86_64.AppImage", "browser_download_url": "file://" + nuova,
             "size": os.path.getsize(nuova), "digest": "sha256:" + hashlib.sha256(b"\x7fELF nuova").hexdigest()}
    in_uso = aggiorna.sostituisci_appimage(asset, in_uso)
    assert in_uso == os.path.join(work, asset["name"]), "prende il nome della release"
    assert open(in_uso, "rb").read() == b"\x7fELF nuova"
    assert os.access(in_uso, os.X_OK)

    # file sbagliato o con un'impronta diversa: la versione in uso non si tocca e non restano file a metà
    for contenuto in (b"<html>errore</html>", b"\x7fELF NUOVA"):
        open(nuova, "wb").write(contenuto)
        asset["size"] = os.path.getsize(nuova)
        try:
            aggiorna.sostituisci_appimage(asset, in_uso)
            raise AssertionError("doveva fallire")
        except RuntimeError:
            pass
    assert open(in_uso, "rb").read() == b"\x7fELF nuova"
    assert sorted(os.listdir(work)) == [asset["name"], "scaricata"], "la vecchia è stata tolta"


if __name__ == "__main__":
    test_versioni()
    with tempfile.TemporaryDirectory() as w:
        test_sostituzione(w)
    print("OK")
