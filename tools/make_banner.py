"""
Genera il banner cyberpunk di ComicOptimizer (in alto nella finestra).
Uso, dalla cartella del progetto:

    venv/bin/python tools/make_banner.py comicoptimizer_banner.png

Usa i font DejaVu (presenti su Ubuntu/Mint); per cambiarli modifica FONT_TITLE/FONT_MONO.
"""
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 2000, 260            # doppia risoluzione: l'app lo riduce, resta nitido
HORIZON = 168
CYAN, MAGENTA, YELLOW = (0, 229, 255), (255, 0, 170), (255, 214, 0)
FONT_TITLE = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
rnd = random.Random(81)     # sempre la stessa immagine


def layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def glow(img, layer_img, radii=(18, 7, 2)):
    """Incolla `layer_img` con un alone al neon."""
    for r in radii:
        img.alpha_composite(layer_img.filter(ImageFilter.GaussianBlur(r)))
    img.alpha_composite(layer_img)


def background():
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(7 + 14 * t), int(6 + 4 * t), int(18 + 26 * t), 255))
    # skyline
    sky = layer()
    ds = ImageDraw.Draw(sky)
    x = 0
    while x < W:
        bw, bh = rnd.randint(28, 70), rnd.randint(30, 120)
        ds.rectangle([x, HORIZON - bh, x + bw, HORIZON], fill=(22, 16, 46, 255))
        for wy in range(HORIZON - bh + 8, HORIZON - 6, 11):
            for wx in range(x + 6, x + bw - 6, 10):
                if rnd.random() < 0.18:
                    c = rnd.choice([CYAN, MAGENTA, YELLOW])
                    ds.rectangle([wx, wy, wx + 3, wy + 4], fill=c + (rnd.randint(70, 160),))
        x += bw + rnd.randint(0, 8)
    img.alpha_composite(sky)
    # orizzonte e griglia in prospettiva
    grid = layer()
    dg = ImageDraw.Draw(grid)
    dg.line([(0, HORIZON), (W, HORIZON)], fill=MAGENTA + (230,), width=3)
    vx = W * 0.5
    for i in range(-40, 41):
        dg.line([(vx + i * 18, HORIZON), (vx + i * 260, H + 400)], fill=MAGENTA + (110,), width=2)
    y, step = HORIZON, 4
    while y < H:
        dg.line([(0, y), (W, y)], fill=MAGENTA + (120,), width=2)
        step *= 1.45
        y += step
    glow(img, grid, radii=(8, 3))
    return img


def comic_page(w, h, colors, tag, tag_top=False):
    page = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(page)
    d.rectangle([4, 4, w + 3, h + 3], fill=(236, 236, 244, 255), outline=(10, 10, 20, 255), width=3)
    m, g = 10, 6
    pw, ph = w - 2 * m, h - 2 * m
    panels = [(0, 0, 1, 0.42), (0, 0.42, 0.5, 0.72), (0.5, 0.42, 1, 0.72), (0, 0.72, 1, 1)]
    for (x0, y0, x1, y1), c in zip(panels, colors):
        box = [4 + m + x0 * pw + g / 2, 4 + m + y0 * ph + g / 2, 4 + m + x1 * pw - g / 2, 4 + m + y1 * ph - g / 2]
        d.rectangle(box, fill=c, outline=(10, 10, 20, 255), width=2)
        for yy in range(int(box[1]) + 4, int(box[3]) - 2, 7):          # retino
            for xx in range(int(box[0]) + 4 + (yy % 14) // 2, int(box[2]) - 2, 7):
                d.ellipse([xx, yy, xx + 2, yy + 2], fill=(0, 0, 0, 60))
    f = ImageFont.truetype(FONT_MONO, 22)
    tx, ty = (4, 4) if tag_top else (w - 58, h - 30)
    d.rectangle([tx, ty, tx + 60, ty + 32], fill=(10, 10, 20, 255))
    d.text((tx + 4, ty), tag, font=f, fill=YELLOW)
    return page


def emblem(img):
    """Pagine disordinate (PDF, CBR, ZIP) → raggio → cartuccia CBZ ordinata."""
    # dietro → davanti; aperte a ventaglio perché si leggano tutte le etichette
    pages = [((30, 90, 220), (250, 200, 20), (200, 30, 40), (60, 60, 70), "RAR", 10, (196, 26)),
             ((200, 30, 40), (30, 90, 220), (250, 200, 20), (40, 140, 230), "PDF", -14, (12, 44)),
             ((250, 200, 20), (200, 30, 40), (30, 90, 220), (200, 30, 40), "ZIP", -3, (104, 62))]
    for c1, c2, c3, c4, tag, ang, (px, py) in pages:
        p = comic_page(118, 160, [c + (255,) for c in (c1, c2, c3, c4)], tag, tag_top=tag == "PDF")
        p = p.rotate(ang, expand=True, resample=Image.BICUBIC)
        shadow = Image.new("RGBA", p.size, (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 150), mask=p.getchannel("A"))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)), (px + 6, py + 8))
        img.alpha_composite(p, (px, py))

    # raggio: chevron al neon + pixel che volano verso la cartuccia
    beam = layer()
    db = ImageDraw.Draw(beam)
    cy = 130
    for i, x in enumerate((362, 398, 434)):
        db.line([(x, cy - 30), (x + 26, cy), (x, cy + 30)], fill=CYAN + (120 + 60 * i,), width=9)
    for _ in range(40):
        x = rnd.randint(350, 480)
        y = cy + rnd.randint(-48, 48) * (1 - (x - 350) / 170)
        s = rnd.randint(3, 8)
        db.rectangle([x, y, x + s, y + s], fill=rnd.choice([CYAN, MAGENTA, YELLOW]) + (rnd.randint(120, 255),))
    glow(img, beam)

    # cartuccia CBZ
    chip = layer()
    dc = ImageDraw.Draw(chip)
    box = [495, 38, 650, 222]
    dc.rounded_rectangle(box, radius=18, fill=(8, 24, 36, 240), outline=CYAN + (255,), width=5)
    for k in range(4):                                        # contatti del chip
        dc.rectangle([510 + k * 34, 210, 530 + k * 34, 232], fill=YELLOW + (230,))
    for k in range(3):                                        # pagine in fila, ordinate
        x0 = 512 + k * 42
        dc.rectangle([x0, 58, x0 + 34, 106], fill=(236, 236, 244, 255), outline=CYAN + (255,), width=2)
        dc.rectangle([x0 + 5, 63, x0 + 29, 80], fill=(CYAN, MAGENTA, YELLOW)[k] + (255,))
        dc.rectangle([x0 + 5, 84, x0 + 29, 101], fill=(MAGENTA, YELLOW, CYAN)[k] + (255,))
    f = ImageFont.truetype(FONT_TITLE, 50)
    dc.text((572, 150), "CBZ", font=f, fill=CYAN + (255,), anchor="mm")
    f2 = ImageFont.truetype(FONT_MONO, 22)
    dc.text((572, 190), "WEBP", font=f2, fill=MAGENTA + (255,), anchor="mm")
    glow(img, chip, radii=(16, 5))


def title(img):
    x0, right = 700, W - 50
    size = 150
    while True:
        f = ImageFont.truetype(FONT_TITLE, size)
        if f.getlength("COMICOPTIMIZER") <= right - x0:
            break
        size -= 2
    y = 18
    comic_w = f.getlength("COMIC")

    def text_layer(fill_comic, fill_opt, dx=0, dy=0):
        t = layer()
        d = ImageDraw.Draw(t)
        d.text((x0 + dx, y + dy), "COMIC", font=f, fill=fill_comic)
        d.text((x0 + comic_w + dx, y + dy), "OPTIMIZER", font=f, fill=fill_opt)
        return t

    # aberrazione cromatica (magenta / ciano spostati) + testo bianco con alone
    img.alpha_composite(text_layer(MAGENTA + (200,), MAGENTA + (200,), -6, 2))
    img.alpha_composite(text_layer(CYAN + (200,), CYAN + (200,), 6, -2))
    core = text_layer((235, 255, 255, 255), (255, 235, 250, 255))
    glow_l = text_layer(CYAN + (255,), MAGENTA + (255,))
    for r in (22, 9):
        img.alpha_composite(glow_l.filter(ImageFilter.GaussianBlur(r)))
    img.alpha_composite(core)

    # strisce "glitch": fette del titolo spostate di lato
    for _ in range(5):
        sy = rnd.randint(y + 20, y + size - 10)
        sh = rnd.randint(4, 12)
        strip = img.crop((x0 - 20, sy, right + 20, sy + sh))
        img.paste(strip, (x0 - 20 + rnd.choice([-1, 1]) * rnd.randint(8, 26), sy))

    # sottotitolo
    fm = ImageFont.truetype(FONT_MONO, 34)
    sub = layer()
    d = ImageDraw.Draw(sub)
    yb = y + size + 22
    d.text((x0 + 4, yb), "// BY SHUREN", font=fm, fill=MAGENTA + (255,))
    tag = "REPAIR · CONVERT · OPTIMIZE"
    fs = ImageFont.truetype(FONT_MONO, 28)
    d.text((right - fs.getlength(tag), yb + 4), tag, font=fs, fill=YELLOW + (255,))
    glow(img, sub, radii=(8, 3))


def scanlines(img):
    s = layer()
    d = ImageDraw.Draw(s)
    for yy in range(0, H, 4):
        d.line([(0, yy), (W, yy)], fill=(0, 0, 0, 55))
    img.alpha_composite(s)


def main(out):
    img = background()
    emblem(img)
    title(img)
    scanlines(img)
    # bordo inferiore al neon, come la vecchia scritta
    b = layer()
    ImageDraw.Draw(b).line([(0, H - 3), (W, H - 3)], fill=CYAN + (255,), width=5)
    glow(img, b, radii=(6,))
    img.convert("RGB").save(out, optimize=True)


if __name__ == "__main__":
    main(sys.argv[1])
