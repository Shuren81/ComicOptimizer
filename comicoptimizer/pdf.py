"""Supporto PDF (PyMuPDF, opzionale): estrazione delle pagine."""

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image

from .config import PDF_ZOOM
from .logsetup import log
from .utils import fmt_duration

# --- IMPORT PDF (opzionale) ---
# "fitz" è deprecato nelle versioni recenti di PyMuPDF: si usa "pymupdf"
# e si ripiega su "fitz" solo per le versioni vecchie.
# Qualsiasi errore (non solo "non installato") spegne i PDF invece di impedire l'avvio dell'app.
try:
    import pymupdf as fitz
    HAS_PDF = True
except Exception as e:
    if not isinstance(e, ImportError):
        log.error(f"PyMuPDF non utilizzabile, PDF disattivati: {e}")
    try:
        import fitz
        HAS_PDF = True
    except Exception:
        HAS_PDF = False

# --- PDF ---

def _pdf_page_is_single_scan(page):
    """
    Restituisce l'xref dell'immagine se la pagina è una "scansione": UNA sola
    immagine che copre quasi tutta la pagina, senza testo visibile né disegni
    vettoriali sopra (che andrebbero persi estraendo solo l'immagine, es.
    fumetti digitali con lettering vettoriale). Altrimenti None.
    Usa get_bboxlog(), che elenca le operazioni di disegno SENZA decodificare le
    immagini: ~0,1 ms a pagina (i vecchi controlli costavano ~100 ms).
    """
    if page.rotation:
        return None
    imgs = page.get_images(full=True)
    if len(imgs) != 1:
        return None
    xref, smask = imgs[0][0], imgs[0][1]
    if smask:                      # immagine con trasparenza → meglio il render
        return None
    # il testo invisibile (OCR) non conta; qualunque altra operazione sì
    ops = [(t, r) for t, r in page.get_bboxlog() if t != "ignore-text"]
    if len(ops) != 1 or ops[0][0] != "fill-image":
        return None
    r = fitz.Rect(ops[0][1])       # get_bboxlog dà tuple, non Rect
    page_area = page.rect.width * page.rect.height
    if page_area <= 0 or (r.width * r.height) < 0.85 * page_area:
        return None
    return xref

def _pdf_extract_native(doc, page, base):
    """
    Salva l'immagine originale della pagina alla risoluzione originale.
    - JPEG (DCT): i byte vengono copiati così come sono (nessuna perdita, ~0 ms)
    - tutto il resto (Flate, JPEG2000, JBIG2, CMYK...): decodificato da MuPDF e
      salvato in JPEG qualità 95 (1 bit → PNG). NON si usa extract_image(), che
      ricodifica in PNG ed è ~30 volte più lento (circa 2,7 s a pagina).
    True se riesce, False se la pagina va renderizzata.
    """
    xref = _pdf_page_is_single_scan(page)
    if not xref:
        return False
    imgs = page.get_images(full=True)
    bpc, filt = imgs[0][4], (imgs[0][8] or "")

    if "DCTDecode" in filt:
        info = doc.extract_image(xref)
        if info and info.get("image") and info.get("ext", "").lower() in ("jpeg", "jpg") \
                and info.get("colorspace") != 4:
            with open(base + ".jpg", "wb") as f:
                f.write(info["image"])
            return True

    pix = fitz.Pixmap(doc, xref)
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    if pix.colorspace is None or pix.colorspace.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)          # CMYK, Lab, DeviceN...
    mode = "L" if pix.n == 1 else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    if bpc == 1:
        img.convert("1").save(base + ".png", "PNG")
    else:
        img.save(base + ".jpg", "JPEG", quality=95)
    return True

def _pdf_render(page, base):
    """Renderizza la pagina e la salva in JPEG (molto più leggero del vecchio PNG)."""
    pix = page.get_pixmap(matrix=fitz.Matrix(PDF_ZOOM, PDF_ZOOM), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.save(base + ".jpg", "JPEG", quality=92)

def _pdf_process_page(doc, i, dest):
    """Estrae/renderizza la pagina `i`. Restituisce 1 se estratta in qualità originale."""
    page = doc.load_page(i)
    base = os.path.join(dest, f"{i + 1:04d}")
    try:
        if _pdf_extract_native(doc, page, base):
            return 1
    except Exception as e:
        log.debug(f"  PDF pag. {i + 1}: estrazione nativa fallita ({e}), render")
        for ext in (".jpg", ".png"):          # niente file a metà
            if os.path.exists(base + ext):
                try:
                    os.remove(base + ext)
                except OSError:
                    pass
    _pdf_render(page, base)
    return 0

def _pdf_chunk_worker(args):
    """Eseguita in un processo separato: ogni processo apre il PDF per conto suo."""
    path, start, end, dest = args
    doc = fitz.open(path)
    native = 0
    try:
        for i in range(start, end):
            native += _pdf_process_page(doc, i, dest)
    finally:
        doc.close()
    return end - start, native

_PDF_CHUNK      = 6     # pagine per blocco di lavoro (equilibrio tra carico e avvio)

_PDF_MIN_PARALLEL = 16  # sotto questo numero di pagine non vale la pena avviare processi

def extract_pdf_pages(path, dest, progress_cb=None):
    """
    Estrae le pagine di un PDF in `dest` (0001.jpg, 0002.png, ...).
    Pagine-scansione → immagine originale; altre pagine → render JPEG.
    Su più core quando il PDF ha abbastanza pagine.
    Restituisce il numero di pagine.
    """
    doc = fitz.open(path)
    n = len(doc)
    doc.close()
    workers = min(max(1, (os.cpu_count() or 2) - 1), max(1, n // _PDF_CHUNK))
    native, done = 0, 0
    t0 = time.time()

    if n >= _PDF_MIN_PARALLEL and workers > 1:
        chunks = [(path, s, min(s + _PDF_CHUNK, n), dest) for s in range(0, n, _PDF_CHUNK)]
        try:
            with ProcessPoolExecutor(max_workers=workers,
                                     mp_context=multiprocessing.get_context("spawn")) as pool:
                for fut in as_completed([pool.submit(_pdf_chunk_worker, c) for c in chunks]):
                    cnt, nat = fut.result()
                    done += cnt
                    native += nat
                    if progress_cb:
                        progress_cb(done, n)
            log.info(f"  PDF: estratto su {workers} processi in {fmt_duration(time.time() - t0)}")
        except Exception as e:
            log.warning(f"  PDF: estrazione parallela non riuscita ({e}), riprovo in sequenza")
            done, native = 0, 0
            workers = 1

    if done < n:                       # sequenziale: PDF corto, un solo core o ripiego
        doc = fitz.open(path)
        try:
            for i in range(n):
                native += _pdf_process_page(doc, i, dest)
                if progress_cb:
                    progress_cb(i + 1, n)
        finally:
            doc.close()
        log.info(f"  PDF: estratto in sequenza in {fmt_duration(time.time() - t0)}")

    log.info(f"  PDF: {native}/{n} pagine estratte in qualità originale, "
             f"{n - native} renderizzate")
    return n
