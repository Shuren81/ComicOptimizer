"""
Genera il disegno al neon (solo contorni, sfondo trasparente) che sta dietro alla
scritta "TRASCINA QUI I FILE" quando la lista è vuota. Uso, dalla cartella del progetto:

    venv/bin/python tools/make_drop_art.py comicoptimizer_drop.png

Il centro resta libero: lì l'app scrive il testo.
"""
import sys

from PIL import Image, ImageDraw, ImageFilter

W, H = 1600, 800    # largo: il 57% centrale resta libero per la scritta
CYAN, MAGENTA, YELLOW = (0, 229, 255), (255, 0, 170), (255, 214, 0)
ALPHA = 150          # linee poco opache: la scritta resta in primo piano
LINE = 4


def layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def neon(img, lay):
    """Incolla le linee con un alone al neon."""
    for r in (10, 4):
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(r)))
    img.alpha_composite(lay)


def page(w, h, color, seed):
    """Pagina di fumetto: contorno e vignette, niente riempimento."""
    p = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(p)
    c = color + (ALPHA,)
    d.rectangle([10, 10, w + 10, h + 10], outline=c, width=LINE)
    m, g = 22, 12
    rows = [(0, 0.38), (0.38, 0.68), (0.68, 1)]
    for i, (y0, y1) in enumerate(rows):
        top, bot = 10 + m + y0 * (h - 2 * m) + g / 2, 10 + m + y1 * (h - 2 * m) - g / 2
        if (i + seed) % 2:
            mid = 10 + m + (w - 2 * m) * (0.45 if seed else 0.58)
            d.rectangle([10 + m, top, mid - g / 2, bot], outline=c, width=LINE - 1)
            d.rectangle([mid + g / 2, top, w + 10 - m, bot], outline=c, width=LINE - 1)
        else:
            d.rectangle([10 + m, top, w + 10 - m, bot], outline=c, width=LINE - 1)
    return p


def main(out):
    img = layer()

    # in basso: griglia in prospettiva
    grid = layer()
    dg = ImageDraw.Draw(grid)
    hz = 640
    dg.line([(40, hz), (W - 40, hz)], fill=MAGENTA + (ALPHA,), width=LINE)
    for i in range(-12, 13):
        dg.line([(W / 2 + i * 40, hz), (W / 2 + i * 190, H + 200)], fill=MAGENTA + (70,), width=2)
    y, step = hz, 10
    while y < H:
        dg.line([(0, y), (W, y)], fill=MAGENTA + (70,), width=2)
        step *= 1.5
        y += step
    neon(img, grid)

    # a sinistra: pagine sparse e un balloon
    left = layer()
    for (w, h, col, ang, x, y, seed) in ((170, 250, CYAN, 14, 10, 270, 0),
                                         (170, 250, MAGENTA, -9, 105, 320, 1)):
        left.alpha_composite(page(w, h, col, seed).rotate(ang, expand=True, resample=Image.BICUBIC), (x, y))
    dl = ImageDraw.Draw(left)
    dl.ellipse([60, 80, 280, 200], outline=YELLOW + (ALPHA,), width=LINE)
    dl.polygon([(120, 190), (105, 240), (165, 195)], outline=YELLOW + (ALPHA,), width=LINE)
    dl.line([(170, 110), (170, 152)], fill=YELLOW + (ALPHA,), width=8)       # "!"
    dl.ellipse([165, 164, 175, 174], fill=YELLOW + (ALPHA,))
    neon(img, left)

    # in alto al centro: frecce "butta qui"
    arrows = layer()
    da = ImageDraw.Draw(arrows)
    for i, y in enumerate((40, 95, 150)):
        da.line([(W / 2 - 40, y), (W / 2, y + 40), (W / 2 + 40, y)], fill=CYAN + (90 + 50 * i,), width=LINE + 2,
                joint="curve")
    neon(img, arrows)

    # a destra: fumetto aperto
    book = layer()
    db = ImageDraw.Draw(book)
    c = CYAN + (ALPHA,)
    spine_top, spine_bot = (1435, 300), (1435, 560)
    db.polygon([(1290, 270), spine_top, spine_bot, (1290, 590)], outline=c, width=LINE)
    db.polygon([spine_top, (1580, 270), (1580, 590), spine_bot], outline=c, width=LINE)
    for (x0, x1) in ((1308, 1417), (1453, 1562)):            # vignette
        db.rectangle([x0, 320, x1, 410], outline=MAGENTA + (ALPHA,), width=LINE - 1)
        db.rectangle([x0, 425, (x0 + x1) / 2 - 6, 540], outline=MAGENTA + (ALPHA,), width=LINE - 1)
        db.rectangle([(x0 + x1) / 2 + 6, 425, x1, 540], outline=MAGENTA + (ALPHA,), width=LINE - 1)
    neon(img, book)

    # qualche pixel sparso
    px = layer()
    dp = ImageDraw.Draw(px)
    for x, y, col in ((560, 170, MAGENTA), (1010, 120, YELLOW), (1100, 590, CYAN), (420, 610, CYAN),
                      (930, 220, CYAN), (640, 100, YELLOW), (1180, 190, MAGENTA), (330, 140, CYAN)):
        dp.rectangle([x, y, x + 8, y + 8], fill=col + (ALPHA,))
    neon(img, px)

    img.save(out, optimize=True)


if __name__ == "__main__":
    main(sys.argv[1])
