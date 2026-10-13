"""Thread di lavoro (importazione, analisi, elaborazione, miniature...)."""

import multiprocessing
import os
import shutil
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image
from PyQt6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, pyqtSignal

from .archives import (
    _format_mismatch_log,
    check_integrity,
    detect_real_format,
    extract_archive,
    get_archive_file_list,
    get_archive_signature,
)
from .cbz import CBZ_MARK, build_comicinfo, cbz_status, verify_cbz
from .config import WEBP_QUALITY
from .images import _prepare_page
from .logsetup import log
from .pdf import HAS_PDF, extract_pdf_pages, fitz
from .utils import (
    _ARCHIVE_EXTS,
    _trash_file_cross_platform,
    cbz_target,
    find_comicinfo,
    folder_comicinfo,
    folder_subdirs,
    fmt_size,
    get_natural_sort_key,
    is_comicinfo,
    is_image_folder,
    is_page_file,
    list_folder_pages,
    list_page_files,
    make_temp_dir,
    path_size,
    run_tool,
)


def _task_tmps(task):
    """Cartelle temporanee di un task (più di una se è un'unione di fumetti)."""
    return [t for t in [task.get('tmp')] + task.get('extra_tmps', []) if t]


class ImportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)

    def __init__(self, raw_paths):
        super().__init__()
        self.raw_paths = raw_paths

    def run(self):
        valid        = []
        all_to_check = []
        for p in self.raw_paths:
            p = os.path.normpath(p)
            if os.path.isdir(p) and is_image_folder(p):
                all_to_check.append(p)   # cartella di sole immagini: un unico fumetto
            elif os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    for f in fs:
                        if f.lower().endswith(_ARCHIVE_EXTS):
                            all_to_check.append(os.path.join(r, f))
            elif p.lower().endswith(_ARCHIVE_EXTS):
                all_to_check.append(p)
        total = len(all_to_check)
        for i, p in enumerate(all_to_check):
            flist = get_archive_file_list(p)
            if flist:
                valid.append((p, len(flist)))
            self.progress.emit(i + 1, total)
        valid.sort(key=lambda x: get_natural_sort_key(x[0]))
        self.finished.emit(valid)

class AnalysisWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict, int)

    def __init__(self, cards_paths):
        super().__init__()
        self.paths = cards_paths

    def run(self):
        results = {}
        groups  = {}     # stesso nome (es. fumetto.cbr + fumetto.cbz)
        by_sig  = {}     # stesso contenuto (pagine identiche) anche con nomi diversi
        total   = len(self.paths)
        for i, p in enumerate(self.paths):
            is_ok = check_integrity(p)
            if not is_ok:
                results[p] = 5
            else:
                target = cbz_target(p)
                groups.setdefault(target, []).append(p)
                sig = get_archive_signature(p)
                if sig:
                    by_sig.setdefault(sig, []).append(p)
            self.progress.emit(i + 1, total)

        def keep_first(x):
            # Tiene preferibilmente il .cbz che è davvero uno ZIP, poi l'ordine naturale
            # poi il nome più corto (le copie di solito sono "… (1)", "… - Copia")
            good_cbz = x.lower().endswith('.cbz') and detect_real_format(x) == 'zip'
            return (0 if good_cbz else 1, len(os.path.basename(x)), get_natural_sort_key(x))

        dupes_count = 0
        for ps in list(groups.values()) + list(by_sig.values()):
            if len(ps) > 1:
                ps = sorted(ps, key=keep_first)
                for loser in ps[1:]:
                    if loser not in results:
                        results[loser] = 4
                        dupes_count += 1
                        log.debug(f"  Duplicato: '{os.path.basename(loser)}' "
                                  f"= '{os.path.basename(ps[0])}'")

        # Assegna status a TUTTI i file integri usando il formato REALE
        for p in self.paths:
            if p not in results:
                real_fmt     = detect_real_format(p)
                declared_ext = os.path.splitext(p)[1].lower()
                if os.path.isdir(p):
                    results[p] = 0   # cartella di immagini: da trasformare in CBZ
                elif declared_ext == '.pdf' or real_fmt == 'pdf':
                    results[p] = 0   # PDF: da convertire
                elif real_fmt == 'rar' or (real_fmt is None and declared_ext in ('.cbr', '.rar')):
                    results[p] = 0   # RAR reale: da convertire in CBZ
                elif real_fmt == 'rar' and declared_ext in ('.cbz', '.zip'):
                    # CBZ che è in realtà un RAR → da sistemare
                    results[p] = 0
                elif real_fmt == 'zip' or (real_fmt is None and declared_ext in ('.cbz', '.zip')):
                    try:
                        results[p] = cbz_status(p)   # 3 = CONVERTITO, 1 = OK
                    except Exception:
                        results[p] = 0
                else:
                    results[p] = 1

        self.finished.emit(results, dupes_count)

class ProcessingWorker(QThread):
    """
    Crea i nuovi CBZ. Sequenza sicura per ogni fumetto:
      1. pagine preparate in una cartella temporanea (WebP su più core)
      2. CBZ scritto come .tmp e VERIFICATO (integrità + numero di pagine)
      3. solo dopo: vecchio file nel cestino e .tmp rinominato nel file finale
    Le cartelle temporanee di TUTTI i task vengono eliminate anche in caso
    di interruzione o errore.
    """
    progress_val   = pyqtSignal(int)
    progress_max   = pyqtSignal(int)
    status_msg     = pyqtSignal(str)
    ask_permission = pyqtSignal(str, str, int, int)
    file_finished  = pyqtSignal(str, str, int)
    job_done       = pyqtSignal(dict)   # riepilogo (non si chiama "finished" per non
                                        # nascondere il segnale nativo di QThread)

    def __init__(self, tasks, to_webp=False):
        super().__init__()
        self.tasks   = tasks            # lista di dict: src, images, tmp, comicinfo, edited
                                        # (unione: anche extra_srcs, extra_tmps, dest, title)
        self.to_webp = to_webp
        self._is_running = True
        self._stop_after_current = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._permission_result = None

    def set_permission(self, res):
        with QMutexLocker(self._mutex):
            self._permission_result = res
            self._condition.wakeAll()

    def abort_now(self):
        self._is_running = False
        # sblocca un'eventuale attesa della scelta sul conflitto
        self.set_permission('skip')

    def stop_later(self):
        self._stop_after_current = True

    def run(self):
        summary = {
            'mode': 'webp' if self.to_webp else 'repair',
            'total': len(self.tasks), 'done': 0, 'skipped': 0,
            'errors': [], 'pages_kept': 0,
            'size_before': 0, 'size_after': 0,
            'aborted': False, 'start': time.time(),
        }
        pool = None
        try:
            if self.to_webp:
                workers = max(1, (os.cpu_count() or 2) - 1)   # un core libero per l'interfaccia
                pool = ProcessPoolExecutor(max_workers=workers,
                                           mp_context=multiprocessing.get_context("spawn"))
                log.info(f"Conversione WebP su {workers} processi paralleli")
            self._run_tasks(pool, summary)
        except Exception as e:
            log.error(f"ProcessingWorker: errore imprevisto: {e}", exc_info=True)
            summary['errors'].append(("(generale)", str(e)))
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
            for task in self.tasks:
                for tmp in _task_tmps(task):
                    shutil.rmtree(tmp, ignore_errors=True)
            summary['elapsed'] = time.time() - summary['start']
            log.info(f"ProcessingWorker completato: {summary['done']} ok, "
                     f"{summary['skipped']} saltati, {len(summary['errors'])} errori"
                     f"{' (INTERROTTO)' if summary['aborted'] else ''}.")
            self.job_done.emit(summary)

    def _run_tasks(self, pool, summary):
        processed = set()
        total_p = sum(len(t['images']) for t in self.tasks)
        self.progress_max.emit(total_p)
        curr_p = 0
        log.info(f"ProcessingWorker avviato: {len(self.tasks)} file, "
                 f"{total_p} immagini totali, webp={self.to_webp}")

        for task in self.tasks:
            if not self._is_running or self._stop_after_current:
                log.info("ProcessingWorker: interrotto dall'utente.")
                summary['aborted'] = True
                break
            orig_p   = task['src']
            srcs     = [orig_p] + task.get('extra_srcs', [])
            img_list = task['images']
            final_p  = task.get('dest') or cbz_target(orig_p)
            log.info(f"Elaborazione: '{os.path.basename(orig_p)}' "
                     f"({len(img_list)} immagini) → '{os.path.basename(final_p)}'")

            if (os.path.exists(final_p) and os.path.normpath(orig_p) != os.path.normpath(final_p)) \
                    or (final_p in processed):
                self._permission_result = None
                pages_on_disk = len(get_archive_file_list(final_p)) if os.path.exists(final_p) else 0
                log.warning(f"  Conflitto: '{os.path.basename(final_p)}' esiste già "
                            f"({pages_on_disk} pag. su disco vs {len(img_list)} nuove)")
                self.ask_permission.emit(orig_p, final_p, len(img_list), pages_on_disk)
                with QMutexLocker(self._mutex):
                    while self._permission_result is None:
                        self._condition.wait(self._mutex)
                log.info(f"  Scelta conflitto: {self._permission_result}")
                if not self._is_running:
                    summary['aborted'] = True
                    break
                if self._permission_result == 'skip':
                    curr_p += len(img_list)
                    self.progress_val.emit(curr_p)
                    summary['skipped'] += 1
                    self.file_finished.emit(orig_p, orig_p, 4)
                    continue
                if self._permission_result == 'rename':
                    base, ext = os.path.splitext(final_p)
                    c = 1
                    while os.path.exists(f"{base}_{c}{ext}") or f"{base}_{c}{ext}" in processed:
                        c += 1
                    final_p = f"{base}_{c}{ext}"
                    log.info(f"  Rinominato in: '{os.path.basename(final_p)}'")

            processed.add(final_p)
            out      = make_temp_dir()
            tmp_zip  = final_p + ".tmp"
            start_p  = curr_p
            size_before = sum(path_size(s) for s in srcs if os.path.exists(s))

            # rimuovi eventuali .tmp orfani prima di procedere
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                    log.debug(f"  Rimosso tmp orfano: '{tmp_zip}'")
                except Exception as e:
                    log.warning(f"Impossibile rimuovere tmp orfano '{tmp_zip}': {e}")

            try:
                pages = self._build_pages(pool, img_list, out, orig_p, start_p, summary)
                if pages is None:
                    log.info("ProcessingWorker: abort_now() ricevuto.")
                    summary['aborted'] = True
                    break

                with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_STORED) as z:
                    for i, fp in enumerate(pages):
                        z.write(fp, os.path.basename(fp))
                    ci = task.get('comicinfo')
                    if ci and os.path.exists(ci):
                        z.writestr("ComicInfo.xml",
                                   build_comicinfo(ci, len(pages), task.get('edited', False),
                                                   task.get('title')))
                        log.info("  ComicInfo.xml conservato")
                    mode = "webp" if self.to_webp else "repair"
                    z.comment = f"{CBZ_MARK} {mode}".encode()

                verify_cbz(tmp_zip, len(pages))
                self._commit(srcs, final_p, tmp_zip)

                size_after = os.path.getsize(final_p)
                summary['done'] += 1
                summary['size_before'] += size_before
                summary['size_after']  += size_after
                result_label = "CONVERTITO (WebP)" if self.to_webp else "RIPARATO"
                log.info(f"  ✓ {result_label}: '{os.path.basename(final_p)}' — "
                         f"{fmt_size(size_before)} → {fmt_size(size_after)}")
                for s in srcs:
                    self.file_finished.emit(s, final_p, 3 if self.to_webp else 2)

            except Exception as e:
                log.error(f"  ✗ Errore elaborazione '{os.path.basename(orig_p)}': {e} "
                          f"— originale NON modificato")
                summary['errors'].append((os.path.basename(orig_p), str(e)))
            finally:
                curr_p = start_p + len(img_list)
                self.progress_val.emit(curr_p)
                shutil.rmtree(out, ignore_errors=True)
                if os.path.exists(tmp_zip):
                    try:
                        os.remove(tmp_zip)
                    except Exception:
                        pass
                for tmp_src in _task_tmps(task):
                    shutil.rmtree(tmp_src, ignore_errors=True)

    def _build_pages(self, pool, img_list, out, orig_p, start_p, summary):
        """Prepara le pagine numerate 0001, 0002... Restituisce None se interrotto."""
        n    = len(img_list)
        name = os.path.basename(orig_p)
        jobs = [(src, os.path.join(out, f"{i + 1:04d}"), self.to_webp, WEBP_QUALITY)
                for i, src in enumerate(img_list)]
        results = [None] * n

        if pool is None:
            for i, job in enumerate(jobs):
                if not self._is_running:
                    return None
                results[i] = _prepare_page(job)
                self.status_msg.emit(f"Ottimizzazione: {name} ({i + 1}/{n})")
                self.progress_val.emit(start_p + i + 1)
        else:
            futures = {pool.submit(_prepare_page, job): i for i, job in enumerate(jobs)}
            done = 0
            for fut in as_completed(futures):
                if not self._is_running:
                    for f in futures:
                        f.cancel()
                    return None
                results[futures[fut]] = fut.result()
                done += 1
                self.status_msg.emit(f"Conversione WebP: {name} ({done}/{n})")
                self.progress_val.emit(start_p + done)

        notes = {}
        for dst, note in results:
            if note:
                key = note.split(" (")[0]
                notes[key] = notes.get(key, 0) + 1
        for note, count in notes.items():
            log.info(f"  {count} pagine lasciate nel formato originale: {note}")
            summary['pages_kept'] += count
        return [r[0] for r in results]

    def _commit(self, srcs, final_p, tmp_zip):
        """Il nuovo CBZ è già verificato: ora si possono toccare i file originali."""
        if os.path.exists(final_p):
            # file che verrà sostituito (originale .cbz o "Sovrascrivi"): nel cestino
            if not _trash_file_cross_platform(final_p):
                log.warning(f"  Cestino non disponibile: '{os.path.basename(final_p)}' "
                            f"verrà sovrascritto")
        os.replace(tmp_zip, final_p)
        for orig_p in srcs:
            if os.path.normpath(orig_p) == os.path.normpath(final_p) or not os.path.exists(orig_p):
                continue
            if _trash_file_cross_platform(orig_p):
                log.info(f"  Originale spostato nel cestino: '{os.path.basename(orig_p)}'")
            elif os.path.isdir(orig_p):
                # una cartella non si cancella mai definitivamente: resta dov'è
                log.warning(f"  Cestino non disponibile: cartella lasciata al suo posto "
                            f"'{os.path.basename(orig_p)}'")
            else:
                log.warning(f"  Cestino non disponibile: originale eliminato "
                            f"'{os.path.basename(orig_p)}'")
                os.remove(orig_p)

class ThumbWorker(QThread):
    # Emette i byte raw dell'immagine invece di QPixmap
    # (QPixmap NON può essere creato fuori dal main thread in Qt6)
    done = pyqtSignal(str, bytes)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        imgs = get_archive_file_list(self.path)
        if not imgs:
            log.debug(f"ThumbWorker: nessuna immagine trovata in '{self.path}'")
            return
        if os.path.isdir(self.path):
            try:
                with open(imgs[0], 'rb') as fh:
                    self.done.emit(self.path, fh.read())
            except Exception as e:
                log.warning(f"ThumbWorker lettura '{imgs[0]}': {e}")
            return
        with tempfile.TemporaryDirectory() as tmp:
            real_fmt = detect_real_format(self.path)
            lower    = self.path.lower()

            if lower.endswith('.pdf') or real_fmt == 'pdf':
                try:
                    doc   = fitz.open(self.path)
                    page  = doc.load_page(0)
                    pix   = page.get_pixmap(alpha=False)
                    img_p = os.path.join(tmp, "t.png")
                    pix.save(img_p)
                    doc.close()
                except Exception as e:
                    log.warning(f"ThumbWorker PDF error '{self.path}': {e}")
                    return
            elif real_fmt == 'zip' or (real_fmt is None and lower.endswith(('.cbz', '.zip'))):
                # ZIP reale: estrazione nativa Python
                try:
                    first = imgs[0]
                    with zipfile.ZipFile(self.path, 'r') as z:
                        z.extract(first, tmp)
                except zipfile.BadZipFile:
                    log.warning(f"ThumbWorker: '{os.path.basename(self.path)}' non è un ZIP "
                                f"(real={real_fmt}), provo unrar/7z")
                    real_fmt = 'rar'   # forza il ramo RAR
                except Exception as e:
                    log.warning(f"ThumbWorker ZIP error '{self.path}': {e}")
                    return

            if real_fmt in ('rar', '7z') or \
               (real_fmt is None and not lower.endswith(('.cbz', '.zip', '.pdf'))):
                # RAR/CBR o formato sconosciuto: unrar e poi 7z e
                first     = imgs[0]
                extracted = False
                try:
                    res = run_tool(
                        ['unrar', 'e', '-y', self.path, first, tmp + os.sep],
                        capture_output=True, timeout=15
                    )
                    extracted = bool(os.listdir(tmp))
                    if not extracted:
                        log.debug(f"ThumbWorker unrar non ha estratto '{first}'")
                except Exception as e:
                    log.debug(f"ThumbWorker unrar error: {e}")
                if not extracted:
                    try:
                        res = run_tool(
                            ['7z', 'e', '-y', f'-o{tmp}', self.path, first],
                            capture_output=True, timeout=15
                        )
                        extracted = bool(os.listdir(tmp))
                        if not extracted:
                            log.warning(f"ThumbWorker 7z: nessun file estratto "
                                        f"(rc={res.returncode})")
                    except Exception as e:
                        log.warning(f"ThumbWorker 7z error '{self.path}': {e}")

            # Leggi bytes del file immagine (sicuro da thread non-GUI)
            for root_dir, _, files in os.walk(tmp):
                for f in sorted(files):
                    full = os.path.join(root_dir, f)
                    if is_page_file(full):
                        try:
                            with open(full, 'rb') as fh:
                                data = fh.read()
                            if data:
                                self.done.emit(self.path, data)
                                return
                        except Exception as e:
                            log.warning(f"ThumbWorker lettura bytes '{full}': {e}")

class LoadingWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, str, list)
    error    = pyqtSignal(str)

    def __init__(self, path, loose_last=False):
        super().__init__()
        self.path       = path
        self.loose_last = loose_last

    def run(self):
        if os.path.isdir(self.path):
            # cartella di immagini: l'editor lavora sugli originali, nella cartella
            # temporanea vanno solo ComicInfo.xml e le pagine aggiunte
            tmp = make_temp_dir()
            ci  = folder_comicinfo(self.path)
            if ci:
                shutil.copy2(ci, tmp)
            self.finished.emit(self.path, tmp, list_folder_pages(self.path, self.loose_last))
            return
        tmp      = make_temp_dir()
        ext      = os.path.splitext(self.path)[1].lower()
        real_fmt = detect_real_format(self.path)
        success  = False
        img_list = get_archive_file_list(self.path)
        total    = len(img_list)

        if not img_list:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Archivio vuoto.")
            return

        if ext == '.pdf' or real_fmt == 'pdf':
            if HAS_PDF:
                try:
                    extract_pdf_pages(self.path, tmp,
                                      lambda v, t: self.progress.emit(v, t))
                    success = True
                except Exception as e:
                    log.error(f"LoadingWorker PDF '{self.path}': {e}")
                    success = False
        else:
            # Usa formato reale per decidere il tool
            use_zip = (real_fmt == 'zip') or (real_fmt is None and ext in ('.cbz', '.zip'))
            try:
                if use_zip:
                    try:
                        with zipfile.ZipFile(self.path, 'r') as z:
                            for i, img_name in enumerate(img_list):
                                z.extract(img_name, tmp)
                                self.progress.emit(i + 1, total)
                            # conserva i metadati
                            for n in z.namelist():
                                if is_comicinfo(n):
                                    z.extract(n, tmp)
                                    break
                        success = True
                        log.info(f"LoadingWorker ZIP OK: '{os.path.basename(self.path)}'")
                    except zipfile.BadZipFile:
                        log.warning(f"LoadingWorker: '{os.path.basename(self.path)}' "
                                    f"non è un ZIP valido (real={real_fmt}), provo unrar/7z")
                        use_zip = False  # ricade nel ramo RAR/7z sotto

                if not use_zip:
                    if real_fmt and real_fmt != ext.lstrip('.'):
                        _format_mismatch_log(self.path, ext, real_fmt)
                    extracted_ok = False
                    try:
                        res = run_tool(
                            ['unrar', 'x', '-y', self.path, tmp + os.sep],
                            capture_output=True, timeout=600
                        )
                        if res.returncode == 0:
                            extracted_ok = True
                            log.info(f"LoadingWorker unrar x OK: '{os.path.basename(self.path)}'")
                        else:
                            log.warning(f"LoadingWorker unrar x rc={res.returncode}: "
                                        f"{res.stderr.decode(errors='replace')[:200]}")
                    except FileNotFoundError:
                        log.warning("LoadingWorker: unrar non trovato, uso 7z x")
                    except Exception as e:
                        log.warning(f"LoadingWorker unrar x eccezione: {e}")

                    if not extracted_ok:
                        res = run_tool(
                            ['7z', 'x', '-y', f'-o{tmp}', self.path],
                            capture_output=True, timeout=600
                        )
                        if res.returncode == 0:
                            extracted_ok = True
                            log.info(f"LoadingWorker 7z x OK: '{os.path.basename(self.path)}'")
                        else:
                            log.error(f"LoadingWorker 7z x rc={res.returncode}: "
                                      f"{res.stderr.decode(errors='replace')[:200]}")

                    for i in range(total):
                        self.progress.emit(i + 1, total)
                    success = extracted_ok

            except Exception as e:
                log.error(f"LoadingWorker archive '{self.path}': {e}")
                success = False

        if success:
            extracted = list_page_files(tmp)
            self.finished.emit(self.path, tmp, extracted)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            self.error.emit("Errore durante l'estrazione.")

class BatchPrepWorker(QThread):
    """Estrae gli archivi e prepara i task per ProcessingWorker."""
    progress      = pyqtSignal(int, int)
    page_progress = pyqtSignal(str, int, int, int)   # nome file, pagina, pagine totali, n. file nel lotto
    ready         = pyqtSignal(list, bool)

    def __init__(self, paths, to_webp, loose_last=()):
        super().__init__()
        self.paths      = paths
        self.to_webp    = to_webp
        self.loose_last = loose_last   # cartelle con le immagini sciolte in fondo

    def run(self):
        tasks = []
        total = len(self.paths)
        for i, p in enumerate(self.paths):
            if os.path.isdir(p):
                tasks += self._folder_task(p)
                self.progress.emit(i + 1, total)
                continue
            tmp = make_temp_dir()
            log.info(f"BatchPrep: estrazione '{os.path.basename(p)}' → '{tmp}'")
            ok = False
            try:
                name = os.path.basename(p)
                ok = extract_archive(
                    p, tmp,
                    lambda v, t, name=name: self.page_progress.emit(name, v, t, total))
            except Exception as e:
                log.error(f"BatchPrepWorker eccezione su '{p}': {e}")

            extracted = list_page_files(tmp)
            expected  = len(get_archive_file_list(p))

            # Controllo: TUTTE le pagine devono essere state estratte.
            # (Sostituisce il vecchio filtro "< 5 KB" che scartava in silenzio
            #  pagine bianche o pagine WebP leggere.)
            if not ok or not extracted:
                log.error(f"  ✗ Nessuna immagine estratta da '{os.path.basename(p)}' — file saltato")
                shutil.rmtree(tmp, ignore_errors=True)
            elif len(extracted) < expected:
                log.error(f"  ✗ Estratte solo {len(extracted)} pagine su {expected} da "
                          f"'{os.path.basename(p)}' — file saltato, originale intatto")
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                unreadable = []
                for fp in extracted:
                    try:
                        with Image.open(fp) as im:
                            im.size
                    except Exception:
                        unreadable.append(os.path.basename(fp))
                if unreadable:
                    log.warning(f"  {len(unreadable)} pagine non leggibili (conservate "
                                f"comunque così come sono): {', '.join(unreadable[:5])}")
                comicinfo = find_comicinfo(tmp)
                log.info(f"  ✓ {len(extracted)} immagini estratte correttamente"
                         f"{' + ComicInfo.xml' if comicinfo else ''}")
                tasks.append({'src': p, 'images': extracted, 'tmp': tmp,
                              'comicinfo': comicinfo, 'edited': False})

            self.progress.emit(i + 1, total)

        log.info(f"BatchPrep completato: {len(tasks)}/{total} file pronti per l'elaborazione")
        self.ready.emit(tasks, self.to_webp)

    def _folder_task(self, p):
        """Cartella di sole immagini: le pagine si leggono direttamente, senza estrazione."""
        pages = list_folder_pages(p, p in self.loose_last)
        if not pages:
            log.error(f"  ✗ Nessuna immagine in '{os.path.basename(p)}' — cartella saltata")
            return []
        subs = folder_subdirs(p, pages)
        log.info(f"BatchPrep: cartella '{os.path.basename(p)}', {len(pages)} immagini"
                 + (f", sottocartelle in ordine: {', '.join(subs)}" if subs else ""))
        return [{'src': p, 'images': pages, 'tmp': None,
                 'comicinfo': folder_comicinfo(p), 'edited': False}]
