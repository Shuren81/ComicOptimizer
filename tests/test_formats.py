"""Test dei formati CB7 ed EPUB (headless, con il 7z vero). Uso:

    venv/bin/python tests/test_formats.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication


def png(path, color):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (30, 45), color).save(path)


def import_paths(paths):
    from comicoptimizer import workers
    got = []
    iw = workers.ImportWorker(paths)
    iw.finished.connect(lambda ok, skipped: got.append((dict(ok), dict(skipped))))
    iw.run()
    return got[0]


def convert(paths, trash):
    """Sistema → Solo Ripara con i worker veri; restituisce il riepilogo."""
    from comicoptimizer import workers
    workers._trash_file_cross_platform = lambda p: (shutil.move(p, os.path.join(trash, os.path.basename(p))),
                                                    True)[1]
    tasks, done = [], []
    bw = workers.BatchPrepWorker(paths, False)
    bw.ready.connect(lambda t, m: tasks.extend(t))
    bw.run()
    pw = workers.ProcessingWorker(tasks)
    pw.job_done.connect(done.append)
    pw.run()
    return done[0]


def seven_zip(work, name, src, password=None, headers=False):
    out = os.path.join(work, name)
    cmd = ["7z", "a", "-bd", "-t7z", out, "."] + ([f"-p{password}"] if password else []) \
        + (["-mhe=on"] if headers else [])
    subprocess.run(cmd, cwd=src, check=True, capture_output=True)
    return out


def test_cb7(work, trash):
    from comicoptimizer.archives import get_archive_file_list
    from comicoptimizer.cbz import file_status
    src = os.path.join(work, "src7")
    png(os.path.join(src, "Cap 10", "1.png"), (0, 0, 250))
    png(os.path.join(src, "Cap 2", "10.png"), (0, 250, 0))
    png(os.path.join(src, "Cap 2", "2.png"), (250, 0, 0))
    ok = seven_zip(work, "Saga 1.cb7", src)
    locked = seven_zip(work, "Chiuso.cb7", src, password="x", headers=True)    # nomi cifrati
    locked2 = seven_zip(work, "Chiuso 2.cb7", src, password="x")               # solo pagine cifrate
    renamed = os.path.join(work, "Finto.cbz")
    shutil.copy(ok, renamed)                                                   # 7z con estensione .cbz
    # pagine in sottocartelle, in ordine naturale
    assert get_archive_file_list(ok) == ["Cap 2/2.png", "Cap 2/10.png", "Cap 10/1.png"]
    assert file_status(renamed) == 0                                           # da sistemare, non "CBZ ok"
    good, skipped = import_paths([ok, locked, locked2, renamed])
    assert set(good) == {ok, renamed} and good[ok] == 3
    assert skipped == {locked: "protetto da password", locked2: "protetto da password"}, skipped
    # convertiti in CBZ, pagine nell'ordine giusto
    s = convert([ok, renamed], trash)
    assert s["done"] == 2 and not s["errors"], s
    for name in ("Saga 1.cbz", "Finto.cbz"):
        with zipfile.ZipFile(os.path.join(work, name)) as z:
            pages = sorted(n for n in z.namelist() if n.endswith(".png"))
            colors = [Image.open(z.open(n)).convert("RGB").getpixel((3, 3)) for n in pages]
        assert [max(range(3), key=c.__getitem__) for c in colors] == [0, 1, 2], (name, colors)   # rosso, verde, blu


def epub(path, pages, meta="", spine=None, extra=None, text_only=False):
    """EPUB sintetico: una pagina XHTML per immagine, spine nell'ordine di `spine` (indici)."""
    opf_items, spine_refs = [], []
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        for i, color in enumerate(pages):
            tmp = path + f".{i}.png"
            png(tmp, color)
            z.write(tmp, f"OEBPS/images/img {i}.png")
            os.remove(tmp)
            body = "<p>Solo testo</p>" if text_only else f'<div><img src="../images/img%20{i}.png" alt=""/></div>'
            z.writestr(f"OEBPS/text/p{i}.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>')
            opf_items.append(f'<item id="p{i}" href="text/p{i}.xhtml" media-type="application/xhtml+xml"/>'
                             f'<item id="i{i}" href="images/img {i}.png" media-type="image/png"/>')
        for i in (spine if spine is not None else range(len(pages))):
            spine_refs.append(f'<itemref idref="p{i}"/>')
        z.writestr("OEBPS/content.opf",
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">{meta}</metadata>'
                   f'<manifest>{"".join(opf_items)}</manifest><spine>{"".join(spine_refs)}</spine></package>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_epub(work, trash):
    from comicoptimizer.archives import get_archive_file_list
    from comicoptimizer.cbz import file_status, read_comicinfo
    from comicoptimizer.epub import epub_meta
    R, G, B = (250, 0, 0), (0, 250, 0), (0, 0, 250)
    calibre = ('<dc:title>La fuga</dc:title><dc:creator>Tizio</dc:creator><dc:creator>Caio</dc:creator>'
               '<dc:publisher>Panini</dc:publisher><dc:date>2019-05-01</dc:date><dc:language>it</dc:language>'
               '<meta name="calibre:series" content="Dylan Dog"/><meta name="calibre:series_index" content="3.0"/>')
    # lo spine (2, 0, 1) comanda, non i nomi dei file
    e = epub(os.path.join(work, "Fumetto.epub"), [R, G, B], calibre, spine=[2, 0, 1])
    assert get_archive_file_list(e) == ["OEBPS/images/img 2.png", "OEBPS/images/img 0.png",
                                        "OEBPS/images/img 1.png"]
    assert file_status(e) == 0
    info = epub_meta(e)
    assert (info["titolo"], info["num"], info["sottotitolo"], info["autore"], info["editore"],
            info["anno"], info["lingua"]) == ("Dylan Dog", "3", "La fuga", "Tizio, Caio", "Panini", "2019", "it")
    assert read_comicinfo(e)["titolo"] == "Dylan Dog"                          # precompila la finestra Info
    # EPUB3 con belongs-to-collection
    e3 = epub(os.path.join(work, "E3.epub"), [R], '<dc:title>Uno</dc:title>'
              '<meta property="belongs-to-collection" id="c">Saga</meta>'
              '<meta refines="#c" property="group-position">7</meta>')
    assert epub_meta(e3)["titolo"] == "Saga" and epub_meta(e3)["num"] == "7"
    # solo testo e DRM: saltati con il motivo, niente CBZ vuoto
    txt = epub(os.path.join(work, "Romanzo.epub"), [R], "<dc:title>R</dc:title>", text_only=True)
    drm = epub(os.path.join(work, "Drm.epub"), [R], "", extra={"META-INF/rights.xml": "<rights/>"})
    font = epub(os.path.join(work, "Font.epub"), [G], "", extra={
        "META-INF/encryption.xml": '<encryption><EncryptedData><CipherData>'
                                   '<CipherReference URI="OEBPS/fonts/a.otf"/></CipherData></EncryptedData></encryption>'})
    good, skipped = import_paths([e, txt, drm, font])
    assert set(good) == {e, font}, good                                        # i font offuscati non sono DRM
    assert skipped[txt].startswith("EPUB di solo testo") and skipped[drm] == "EPUB protetto (DRM)"
    # conversione: CBZ con le pagine nell'ordine dello spine e il ComicInfo dall'OPF
    s = convert([e], trash)
    assert s["done"] == 1 and s["mode"] == "repair", s
    with zipfile.ZipFile(os.path.join(work, "Fumetto.cbz")) as z:
        pages = sorted(n for n in z.namelist() if n.endswith(".png"))
        first = Image.open(z.open(pages[0])).convert("RGB").getpixel((3, 3))
        ci = ET.fromstring(z.read("ComicInfo.xml"))
    assert first[2] > 200                                                      # prima pagina: la blu (img 2)
    assert ci.findtext("Series") == "Dylan Dog" and ci.findtext("Number") == "3"
    assert ci.findtext("Writer") == "Tizio, Caio" and ci.findtext("LanguageISO") == "it"
    assert ci.findtext("PageCount") == "3"
    assert os.path.exists(os.path.join(trash, "Fumetto.epub"))


def test_no_password_prompt(work):
    """7z e unrar non devono mai fermarsi a chiedere una password."""
    from comicoptimizer import utils
    seen = []
    real = utils.subprocess.run
    utils.subprocess.run = lambda args, **kw: (seen.append((args, kw)), real(["true"]))[1]
    try:
        utils.run_tool(["7z", "t", "x.cb7"])
        utils.run_tool(["unrar", "lb", "x.cbr"])
    finally:
        utils.subprocess.run = real
    assert seen[0][0][1:3] == ["t", "-pComicOptimizer"] and seen[1][0][1:3] == ["lb", "-p-"]
    assert all(kw["stdin"] is subprocess.DEVNULL for _, kw in seen)


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        trash = os.path.join(work, "_cestino")
        os.makedirs(trash)
        test_no_password_prompt(work)
        test_cb7(work, trash)
        test_epub(work, trash)
    print("TUTTO OK")
