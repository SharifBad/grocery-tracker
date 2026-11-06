import io

from PIL import Image
from receipts import render_receipt, simulate_photo

from grocery import imaging


def jpeg(img, **kw):
    buf = io.BytesIO()
    img.save(buf, "JPEG", **kw)
    return buf.getvalue()


def test_load_photo_applies_exif_rotation_and_downscales():
    img = Image.new("RGB", (400, 200), "red")
    exif = img.getexif()
    exif[0x0112] = 6  # phone held sideways: "rotate 90° clockwise to display"
    data = jpeg(img, exif=exif)
    assert imaging.load_photo(data).size == (200, 400)
    assert imaging.load_photo(data, max_short_side=100).size == (100, 200)


def test_rotate_is_clockwise_and_tilt_expands_with_white_corners():
    marked = Image.new("RGB", (40, 20), "white")
    marked.putpixel((0, 0), (0, 0, 0))
    assert imaging.rotate(marked, 1).getpixel((19, 0)) == (0, 0, 0)
    assert imaging.rotate(marked, -1).size == (20, 40)
    assert imaging.rotate(marked, 2).size == (40, 20)
    tilted = imaging.rotate(Image.new("RGB", (400, 200), "red"), 0, 10)
    assert tilted.width > 400 and tilted.getpixel((0, 0)) == (255, 255, 255)


def test_detects_receipt_in_photo():
    receipt, _ = render_receipt()
    photo = imaging.load_photo(simulate_photo(receipt))
    left, top, right, bottom = imaging.detect_receipt_box(photo)
    w, h = photo.size
    assert 0.1 * w < left < 0.4 * w and 0.6 * w < right < 0.9 * w
    assert top < 0.1 * h and bottom > 0.9 * h


def test_detect_falls_back_to_almost_whole_image():
    assert imaging.detect_receipt_box(Image.new("RGB", (300, 400), "white")) == (6, 8, 294, 392)


def test_prepare_for_gemini_shrinks_to_grayscale_jpeg_and_never_upscales():
    receipt, _ = render_receipt()
    photo = imaging.load_photo(simulate_photo(receipt))
    out = Image.open(io.BytesIO(imaging.prepare_for_gemini(photo, imaging.detect_receipt_box(photo))))
    assert min(out.size) == imaging.OCR_SHORT_SIDE and out.mode == "L" and out.format == "JPEG"
    small = imaging.prepare_for_gemini(Image.new("RGB", (300, 500), "white"))
    assert Image.open(io.BytesIO(small)).size == (300, 500)


def test_display_copy_fits_a_phone():
    small, scale = imaging.display_copy(Image.new("RGB", (2000, 3000)))
    assert small.width <= 340 and small.height <= 460
    assert abs(scale - 2000 / small.width) < 1e-9
