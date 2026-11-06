"""Receipt photo handling: fix orientation, guess the crop box, and shrink the crop for Gemini.

No Streamlit imports, so this can be tested and used from scripts.
"""
import io

import numpy as np
from PIL import Image, ImageOps

# How small we make the cropped receipt before sending it to Gemini: its SHORT side (the
# receipt's width) is scaled down to OCR_SHORT_SIDE px. Never upscaled.
#
# Measured 2026-11-06 with gemini-3.8-flash on simulated phone photos of 80 mm thermal receipts
# (576 printer dots/line; 25 items normal print and 40 items small print, tilted, blurred,
# uneven light): every price, the total and the date were read correctly at every size from
# 250 px up, including a soft-focus photo at 300 px. Gemini bills the same ~1,370 prompt tokens
# at every size, so shrinking saves upload size and time, not Gemini cost.
# Real receipts are worse than synthetic ones (faded thermal ink, creases, glare), so we keep a
# ~2.5x margin over the failure-free floor. (A user-facing resolution slider was removed because
# size doesn't change token cost; Gemini's media_resolution setting does, see config.py.)
OCR_SHORT_SIDE = 700          # ~110 KB per receipt
JPEG_QUALITY = 80
WORKING_SHORT_SIDE = 2000     # uploads are downscaled to this on load so editing stays fast


MIN_SIDE = 50  # smaller than this can't be a readable receipt


class UnusableImage(ValueError):
    pass


def _to_rgb(img):
    """RGB for any input mode: transparency goes onto white paper; 16-bit/float images are rescaled."""
    if img.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N", "F"):
        a = np.asarray(img, dtype=float)
        span = float(a.max() - a.min()) or 1.0
        img = Image.fromarray(((a - a.min()) / span * 255).astype("uint8"), "L")
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        paper = Image.new("RGB", rgba.size, "white")
        paper.paste(rgba, mask=rgba.getchannel("A"))
        return paper
    return img.convert("RGB")


def load_photo(data, max_short_side=None):
    """Decode an uploaded photo, applying the phone's EXIF rotation; optionally downscale.

    Raises UnusableImage for files that aren't images or are too small to read.
    """
    try:
        img = Image.open(io.BytesIO(data))
        if max_short_side and img.format == "JPEG":
            img.draft("RGB", (max_short_side, max_short_side))  # decode big JPEGs at reduced size
        img = _to_rgb(ImageOps.exif_transpose(img))
    except Exception as e:  # not an image, truncated, decompression bomb, ...
        raise UnusableImage("Couldn't open that image. Try a JPG or PNG photo.") from e
    if min(img.size) < MIN_SIDE:
        raise UnusableImage(f"That image is only {img.width} × {img.height} px, too small to read.")
    if max_short_side and min(img.size) > max_short_side:
        scale = max_short_side / min(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    return img


def rotate(img, quarter_turns=0, tilt=0.0):
    """Rotate by quarter_turns x 90 degrees, then by `tilt` degrees (both clockwise when positive).

    Tilting expands the canvas; the exposed corners are filled white like receipt paper.
    """
    turns = quarter_turns % 4
    if turns:
        img = img.transpose({1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180, 3: Image.Transpose.ROTATE_90}[turns])
    if tilt:
        img = img.rotate(-tilt, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    return img


def _otsu_threshold(gray):
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = hist.sum()
    levels = np.arange(256)
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    mean_bg = np.cumsum(hist * levels) / np.maximum(weight_bg, 1)
    mean_fg = ((hist * levels).sum() - np.cumsum(hist * levels)) / np.maximum(weight_fg, 1)
    between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    return int(np.argmax(between))


def detect_receipt_box(img):
    """Best guess at the receipt's bounds as (left, top, right, bottom) in img pixels.

    Looks for the bright paper against a darker background. If that doesn't stand out
    (e.g. a white table), returns nearly the whole image.
    """
    w, h = img.size
    fallback = (round(w * 0.02), round(h * 0.02), round(w * 0.98), round(h * 0.98))

    small = img.convert("L")
    small.thumbnail((300, 300))
    gray = np.asarray(small)
    mask = gray > _otsu_threshold(gray)
    rows = np.flatnonzero(mask.mean(axis=1) > 0.25)
    cols = np.flatnonzero(mask.mean(axis=0) > 0.25)
    if rows.size == 0 or cols.size == 0:
        return fallback

    sx, sy = w / gray.shape[1], h / gray.shape[0]
    left, right = cols[0] * sx, (cols[-1] + 1) * sx
    top, bottom = rows[0] * sy, (rows[-1] + 1) * sy
    area = (right - left) * (bottom - top) / (w * h)
    if not 0.05 < area < 0.95:
        return fallback

    pad_x, pad_y = (right - left) * 0.03, (bottom - top) * 0.02
    return (
        max(0, round(left - pad_x)),
        max(0, round(top - pad_y)),
        min(w, round(right + pad_x)),
        min(h, round(bottom + pad_y)),
    )


def clamp_box(box, size, min_side=10):
    """Fit a (left, top, right, bottom) box inside an image of `size`; None if too little is left."""
    w, h = size
    left, top, right, bottom = (round(v) for v in box)
    left, right = max(0, min(left, w)), max(0, min(right, w))
    top, bottom = max(0, min(top, h)), max(0, min(bottom, h))
    if right - left < min_side or bottom - top < min_side:
        return None
    return (left, top, right, bottom)


def prepare_for_gemini(img, box=None, short_side=OCR_SHORT_SIDE):
    """Crop, convert to grayscale, shrink and JPEG-encode. Returns the JPEG bytes."""
    box = clamp_box(box, img.size) if box else None
    if box:
        img = img.crop(box)
    img = ImageOps.grayscale(img)
    if min(img.size) > short_side:
        scale = short_side / min(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def display_copy(img, max_width=340, max_height=460):
    """A small copy that fits a phone screen, plus the factor to scale its coordinates back up."""
    small = img.copy()
    small.thumbnail((max_width, max_height))
    return small, img.width / small.width
