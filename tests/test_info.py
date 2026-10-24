"""Test delle info del fumetto (ComicInfo.xml) e del nome dalle info (headless). Uso:

    venv/bin/python tests/test_info.py
"""
import os
import shutil
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication


def png(path, color):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (40, 60), color).save(path)


def cbz(path, n, ci=None):
    with zipfile.ZipFile(path, "w") as z:
        for i in range(n):
            tmp = path + f".{i}.png"
            png(tmp, (i * 40, 0, 0))
            z.write(tmp, f"{i + 1:04d}.png")
            os.remove(tmp)
        if ci:
            z.writestr("ComicInfo.xml", ci)
    return path


def test_engine(work):
    from comicoptimizer.cbz import build_comicinfo, read_comicinfo
    from comicoptimizer.utils import apply_schema, name_info
    # dal nome, con le regole della Rinomina; il numero com'è
    assert name_info("Batman 050 - The Wedding (2016)") == {
        "titolo": "Batman", "num": "50", "sottotitolo": "The Wedding", "anno": "2016",
        "autore": "", "editore": "", "edizione": "", "lingua": ""}
    assert name_info("Berserk 03", fields={"autore": "Kentaro Miura"})["autore"] == "Kentaro Miura"
    # il nome dalle info: i valori vincono; un campo vuoto usato nello schema è un errore
    v = {"titolo": "Batman", "num": "50", "sottotitolo": "The Wedding", "anno": "2016", "lingua": "ENG"}
    assert apply_schema("x", "<tit> (<anno>) - #<num> - <sott> (<lang>)", 1, 3, values=v) == \
        "Batman (2016) - #050 - The Wedding (ENG)"
    for role, msg in (("autore", "autore vuoto"), ("num", "numero vuoto")):
        try:
            apply_schema("x 1", f"<{'aut' if role == 'autore' else 'num'}>", 1, 3, values={role: ""})
            raise AssertionError(role)
        except ValueError as e:
            assert str(e) == msg, e
    # ComicInfo nuovo: campi, lingua ISO, manga, ordine dello schema
    root = ET.fromstring(build_comicinfo(None, 3, info={**v, "autore": "", "manga": True}))
    assert [e.tag for e in root] == ["Title", "Series", "Number", "Year", "PageCount", "LanguageISO", "Manga"]
    assert root.findtext("LanguageISO") == "en" and root.findtext("Manga") == "YesAndRightToLeft"
    assert ET.fromstring(build_comicinfo(None, 1, info={"lingua": "Italiano"})).findtext("LanguageISO") == "it"
    # ComicInfo esistente: si aggiorna, gli altri campi restano; un campo svuotato si toglie
    old = os.path.join(work, "old.xml")
    open(old, "w").write("<ComicInfo><Summary>Trama</Summary><Series>Vecchia</Series>"
                         "<Writer>X</Writer><PageCount>3</PageCount><Penciller>Y</Penciller></ComicInfo>")
    root = ET.fromstring(build_comicinfo(old, 3, info={"titolo": "Nuova", "autore": ""}))
    assert root.findtext("Series") == "Nuova" and root.find("Writer") is None
    assert root.findtext("Summary") == "Trama" and root.findtext("Penciller") == "Y"
    # lettura da CBZ e da cartella; niente ComicInfo → {}
    a = cbz(os.path.join(work, "A.cbz"), 1, "<ComicInfo><Series>S</Series><Number>7</Number>"
                                             "<Manga>Yes</Manga></ComicInfo>")
    info = read_comicinfo(a)
    assert info["titolo"] == "S" and info["num"] == "7" and info["manga"] is True
    folder = os.path.join(work, "Cartella")
    png(os.path.join(folder, "1.png"), (0, 0, 0))
    assert read_comicinfo(folder) == {}
    open(os.path.join(folder, "ComicInfo.xml"), "w").write("<ComicInfo><Writer>W</Writer></ComicInfo>")
    assert read_comicinfo(folder)["autore"] == "W"


def test_dialog(work):
    from comicoptimizer.dialogs import InfoDialog
    from comicoptimizer.utils import new_rule
    d_ = os.path.join(work, "dlg")
    os.makedirs(d_)
    a = cbz(os.path.join(d_, "Batman 050 - The Wedding (2016).cbz"), 1)
    b = cbz(os.path.join(d_, "Batman 051 - Il ritorno (2016).cbz"), 1,
            "<ComicInfo><Series>Batman</Series><Number>51</Number><Title>Il ritorno</Title>"
            "<Year>2016</Year></ComicInfo>")
    d = InfoDialog([b, a], fields={"lingua": "ENG"})
    col = lambda c: [d.table.item(i, c).text() for i in range(2)]
    serie, numero, titolo, autore, lingua = (d.C_FIRST + k for k in (0, 1, 2, 4, 7))
    assert d.paths == [a, b] and col(serie) == ["Batman", "Batman"] and col(numero) == ["50", "51"]
    assert col(lingua) == ["ENG", "ENG"]                         # dalla casella della Rinomina
    # b ha già le stesse info e nessun nome nuovo... ma la lingua ENG è nuova: si salva
    assert set(d.jobs()) == {a, b}
    d.table.item(1, lingua).setText("")
    assert d.table.item(1, d.C_NOTE).text() == "invariato" and set(d.jobs()) == {a}
    f = d.table.item(1, lingua).font()
    assert f.italic()                                            # cella cambiata a mano
    # caselle per più righe: il valore va subito nelle righe selezionate, senza "Applica"
    calls = []
    real_refresh = d._refresh
    d._refresh = lambda: (calls.append(1), real_refresh())
    d.table.selectRow(0)
    d.bulk["autore"].setText("Tom King")
    assert col(autore) == ["Tom King", ""] and len(calls) == 1 and d.table.item(0, autore).font().italic()
    d.bulk_manga.setCurrentText("Sì")
    assert d.info[0]["manga"] and not d.info[1]["manga"]
    d.bulk["autore"].clear()                                     # casella vuota: torna il valore di prima
    assert col(autore) == ["", ""]
    d.bulk["autore"].setText("Tom King")
    d._refresh = real_refresh
    d.table.clearSelection()                                     # altra selezione: caselle vuote, valori restano
    assert d.bulk["autore"].text() == "" and d.bulk_manga.currentText() == "" and col(autore) == ["Tom King", ""]
    # il nome dalle info; una riga con un campo dello schema vuoto è rossa e non si salva
    d.schema.setEditText("<tit> (<anno>) - #<num> - <sott> (<aut>)")
    assert d.table.item(0, d.C_NEW).text() == "Batman (2016) - #050 - The Wedding (Tom King).cbz"
    assert d.table.item(1, d.C_NOTE).text() == "⚠ autore vuoto" and list(d.jobs()) == [a]
    info, dest = d.jobs()[a]
    assert info["autore"] == "Tom King" and dest == os.path.join(d_, "Batman (2016) - #050 - The Wedding (Tom King).cbz")
    assert d.b_ok.text() == "Salva 1 di 2"
    # 🔍 Cerca: titolo dalla colonna Titolo, autore nella casella per più righe (senza selezione: tutte)
    assert d._search_title() == "Batman"
    d._set_author("Bob Kane")
    assert d.bulk["autore"].text() == "Bob Kane" and col(autore) == ["Bob Kane", "Bob Kane"]
    assert [h for h in (d.table.horizontalHeaderItem(c).text() for c in (serie, titolo))] == ["Titolo", "Sottotitolo"]
    d.reject()
    # dalla Rinomina con le marcature: l'autore marcato nel nome
    c = cbz(os.path.join(d_, "Berserk - Kentaro Miura - 03.cbz"), 1)
    rule = new_rule("Berserk - Kentaro Miura - 03")
    rule["marks"] = {"autore": ((1, 0), (1, 0))}
    d = InfoDialog([c], rule=rule)
    assert d.table.item(0, autore).text() == "Kentaro Miura" and d.table.item(0, serie).text() == "Berserk"
    # "Ch." non è un sottotitolo; "(Autore)" nemmeno
    from comicoptimizer.utils import name_info
    info = name_info("Juujika no Rokunin (Shiryuu Nakatake) Ch. 015")
    assert info["titolo"] == "Juujika no Rokunin" and info["sottotitolo"] == "" and info["num"] == "15"
    # una lettera da sola è un titolo ("V" for Vendetta), con il punto è un'etichetta ("V. 3")
    assert name_info("V 01")["titolo"] == "V"
    info = name_info("Saga (Vaughan) V. 3 - Fine")
    assert info["titolo"] == "Saga" and info["sottotitolo"] == "Fine"
    # anno non di 4 cifre: riga rossa, non si salva
    d.table.item(0, d.C_FIRST + 3).setText("circa 1990")
    assert d.table.item(0, d.C_NOTE).text() == "⚠ anno non valido (4 cifre)" and not d.jobs()
    d.table.item(0, d.C_FIRST + 3).setText("1990")
    assert d.jobs()
    d.reject()


def test_save(work):
    """Salvataggio completo con i worker veri: info nel CBZ, nome nuovo, pagine identiche, originale nel cestino."""
    from comicoptimizer import workers
    from comicoptimizer.dialogs import InfoDialog
    s_ = os.path.join(work, "save")
    trash = os.path.join(work, "_cestino")
    os.makedirs(trash)
    workers._trash_file_cross_platform = lambda p: (shutil.move(p, os.path.join(trash, os.path.basename(p))),
                                                    True)[1]
    os.makedirs(s_)
    src = cbz(os.path.join(s_, "naruto_12.cbz"), 3,
              "<ComicInfo><Summary>Trama</Summary><PageCount>3</PageCount></ComicInfo>")
    with zipfile.ZipFile(src) as z:
        pages_before = [z.read(n) for n in sorted(z.namelist()) if n.endswith(".png")]
    folder = os.path.join(s_, "Saga 1")
    png(os.path.join(folder, "1.png"), (0, 200, 0))
    d = InfoDialog([src, folder])
    d.table.item(0, d.C_FIRST).setText("Naruto")
    d.table.item(0, d.C_FIRST + 4).setText("Masashi Kishimoto")
    d.schema.setEditText("<aut> - <tit> - Cap #<num>")
    d.table.item(1, d.C_FIRST + 4).setText("Brian K. Vaughan")
    assert "diventa CBZ" in d.table.item(1, d.C_NOTE).text()
    jobs = d.jobs()
    d.reject()
    tasks = []
    bw = workers.BatchPrepWorker(list(jobs), False)
    bw.ready.connect(lambda t, m: tasks.extend(t))
    bw.run()
    for t in tasks:
        t["info"], t["dest"] = jobs[t["src"]]
        t["info_job"] = True
    done = []
    pw = workers.ProcessingWorker(tasks)
    pw.job_done.connect(done.append)
    pw.run()
    assert done[0]["done"] == 2 and not done[0]["errors"] and done[0]["mode"] == "info", done
    out = os.path.join(s_, "Masashi Kishimoto - Naruto - Cap #012.cbz")
    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read("ComicInfo.xml"))
        pages_after = [z.read(n) for n in sorted(z.namelist()) if n.endswith(".png")]
    assert pages_after == pages_before                           # copiate, non ricompresse
    assert root.findtext("Series") == "Naruto" and root.findtext("Number") == "12"
    assert root.findtext("Writer") == "Masashi Kishimoto" and root.findtext("Summary") == "Trama"
    assert not os.path.exists(src) and os.path.exists(os.path.join(trash, "naruto_12.cbz"))
    out2 = os.path.join(s_, "Brian K. Vaughan - Saga - Cap #001.cbz")
    with zipfile.ZipFile(out2) as z:
        assert ET.fromstring(z.read("ComicInfo.xml")).findtext("Writer") == "Brian K. Vaughan"


def test_window(work):
    """INFO nella finestra principale e "Info…" dalla Rinomina."""
    import comicoptimizer.main_window as mw
    w_ = os.path.join(work, "win")
    os.makedirs(w_)
    a = cbz(os.path.join(w_, "Tex 701.cbz"), 1)
    w = mw.MainWindow()
    w.import_files([(a, 1)])
    assert not w.btn_info.isVisible()
    w.show()
    w.cards[a].selected = True
    w._update_sel_buttons()
    assert w.btn_info.isVisible()
    opened = []

    class FakeInfo:
        def __init__(self, paths, parent=None, rule=None, fields=None, split_numbers=True):
            opened.append((paths, rule, fields, split_numbers))

        def exec(self):
            return 0
    mw.InfoDialog = FakeInfo
    w.info_selected()
    assert opened[-1] == ([a], None, None, True)

    class FakeRename:
        done_pairs = []

        def __init__(self, paths, parent=None, on_rename=None):
            self.info_request = (paths, "regola", {"autore": "X"}, False)

        def exec(self):
            return 0
    mw.RenameDialog = FakeRename
    w.rename_cards([a])
    assert opened[-1] == ([a], "regola", {"autore": "X"}, False)
    w._closing = True


def test_rename_to_info(work):
    """Il pulsante "Info…" della Rinomina passa righe selezionate, marcature e caselle."""
    from comicoptimizer.dialogs import RenameDialog
    r_ = os.path.join(work, "ren")
    os.makedirs(r_)
    paths = [cbz(os.path.join(r_, f"Zagor {n}.cbz"), 1) for n in (1, 2, 3)]
    d = RenameDialog(paths)
    d.fields["autore"].setText("Nolitta")
    d.table.selectRow(1)
    d.to_info()
    rows, rule, fields, split = d.info_request
    assert rows == [paths[1]] and rule is None and fields["autore"] == "Nolitta" and split is True
    assert d.result() == 0                                       # la Rinomina si chiude


if __name__ == "__main__":
    app = QApplication([])
    with tempfile.TemporaryDirectory() as work:
        QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, work)
        from comicoptimizer import history
        history.HISTORY_PATH = os.path.join(work, "rinomine.jsonl")   # non il registro vero
        test_engine(work)
        test_dialog(work)
        test_save(work)
        test_window(work)
        test_rename_to_info(work)
    print("TUTTO OK")
