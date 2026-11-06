"""Synthetic thermal receipts and simulated phone photos for tests. Deterministic, no network."""
import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

NAMES = ["BIO VOLLMILCH 3,8%", "ROGGENMISCHBROT", "BANANEN", "GOUDA JUNG SCHEIBE", "HAEHNCHENBRUSTFILET",
         "SPAGHETTI NO.5", "TOMATEN PASSIERT", "EIER FREILAND 10ST", "BUTTER MILD GES.", "APFEL ELSTAR",
         "PAPRIKA ROT", "JOGHURT NATUR 3,5", "HAFERFLOCKEN ZART", "MINERALW. MEDIUM", "PFAND 0,25",
         "SPUELMITTEL ORANGE", "TOILETTENPAPIER 8R", "KAFFEE CREMA BOHNE", "ZWIEBELN 1KG", "KAROTTEN BUND",
         "MOZZARELLA 125G", "LACHSFILET TK", "BASMATIREIS", "OLIVENOEL EXTRA", "SCHOKOLADE ZARTB."]

_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc"]


def _font(px):
    for path in _FONTS:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def render_receipt(n_items=40, font_px=19, cols=48, seed=7):
    """An 80 mm thermal receipt (576 px wide). Returns (grayscale image, {"items": prices, "total": total})."""
    rng = random.Random(seed)
    font = _font(font_px)
    line_h = round(font_px * 1.25)
    prices, lines = [], ["REWE Markt GmbH".center(cols), "", "EUR".rjust(cols)]
    for name in rng.choices(NAMES, k=n_items):
        price = round(rng.uniform(0.25, 9.99), 2)
        p = f"{price:.2f}".replace(".", ",")
        lines.append(name[: cols - 10].ljust(cols - len(p) - 2) + p + " A")
        prices.append(price)
    total = round(sum(prices), 2)
    t = f"{total:.2f}".replace(".", ",")
    lines += ["-" * cols, "SUMME".ljust(cols - len(t) - 4) + "EUR " + t, "", "Datum: 03.11.2026  18:42"]
    img = Image.new("L", (576, line_h * len(lines) + 60), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((10, 30 + i * line_h), line, font=font, fill=0)
    return img, {"items": prices, "total": total}


def simulate_photo(receipt, blur=2.2, seed=7, size=(1500, 2000)):
    """The receipt photographed: on a dark background, tilted, blurred, noisy. Returns JPEG bytes."""
    rng = np.random.default_rng(seed)
    pw, ph = size
    scale = 0.9 * ph / receipt.height
    r = receipt.resize((round(receipt.width * scale), round(receipt.height * scale))).convert("RGB")
    bg = Image.fromarray(np.clip(rng.normal(95, 18, (ph, pw, 3)), 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(4))
    bg.paste(r, ((pw - r.width) // 2, (ph - r.height) // 2))
    img = bg.rotate(1.8, fillcolor=(90, 90, 90)).filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(img).astype(float) + rng.normal(0, 5, (ph, pw, 3))
    buf = io.BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype("uint8")).save(buf, "JPEG", quality=88)
    return buf.getvalue()
