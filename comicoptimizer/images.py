"""Preparazione e conversione delle singole pagine (WebP, JPEG...)."""

import os
import shutil

from PIL import Image

from .config import WEBP_MAX_SIDE

# --- ELABORAZIONE PAGINE (eseguita in processi separati, su più core) ---

def _to_saveable_rgb(img):
    """Porta qualsiasi modalità (CMYK, 16 bit, palette, alpha...) in RGB/L a 8 bit."""
    mode = img.mode
    if mode in ("RGB", "L"):
        return img
    if mode == "1":
        return img.convert("L")
    if mode.startswith("I;16") or mode in ("I", "F"):
        # 16/32 bit: riscala a 8 bit invece di "tagliare" (altrimenti pagina bianca)
        img = img.convert("I") if mode != "F" else img
        hi = img.getextrema()[1] or 1
        # 16 bit → dividi per 256; valori già a 8 bit restano uguali
        scale = 1.0 if hi <= 255 else (1 / 256 if hi <= 65535 else 255.0 / hi)
        return img.point(lambda v: v * scale).convert("L")
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")   # CMYK, YCbCr, LAB, P, ...

def _prepare_page(job):
    """
    job = (sorgente, destinazione_senza_estensione, to_webp, qualità)
    Restituisce (file_scritto, nota). La nota spiega perché una pagina è stata
    lasciata nel formato originale (None se tutto normale).
    Una pagina problematica NON fa più fallire l'intero fumetto.
    """
    src, dst_base, to_webp, quality = job
    src_ext = os.path.splitext(src)[1].lower() or ".jpg"
    keep = dst_base + src_ext

    if not to_webp:
        shutil.copy2(src, keep)
        return keep, None
    if src_ext == ".webp":
        shutil.copy2(src, keep)            # già WebP: niente ricompressione
        return keep, None

    dst = dst_base + ".webp"
    try:
        with Image.open(src) as img:
            if max(img.size) > WEBP_MAX_SIDE:
                shutil.copy2(src, keep)
                return keep, "troppo grande per WebP"
            img.load()
            rgb = _to_saveable_rgb(img)
            rgb.save(dst, "WEBP", quality=quality, method=4)
        if os.path.getsize(dst) >= os.path.getsize(src):
            os.remove(dst)
            shutil.copy2(src, keep)
            return keep, "WebP più pesante dell'originale"
        return dst, None
    except Exception as e:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        shutil.copy2(src, keep)
        return keep, f"conversione fallita ({e})"
