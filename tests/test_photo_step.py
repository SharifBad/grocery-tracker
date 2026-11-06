"""Photo step via AppTest: upload, turn, tilt, read, read again, save; PDFs and broken files."""
import datetime
import io

import pytest
from helpers import button, make_app, no_exc
from PIL import Image
from receipts import render_receipt, simulate_photo

from grocery import extract


@pytest.fixture
def gemini(monkeypatch):
    """Fake extract_receipt; returns the list of (data, mime) it was called with."""
    calls = []

    def fake(data, mime, on_progress=None):
        calls.append((data, mime))
        return {"date": datetime.date(2026, 11, 3), "date_guessed": False, "store": "REWE", "total": 9.99,
                "items": [{"name": f"Item read #{len(calls)}", "category": "Dairy", "price": 9.99}], "tokens": 1416}

    monkeypatch.setattr(extract, "extract_receipt", fake)
    return calls


@pytest.fixture(scope="module")
def photo():
    receipt, _ = render_receipt()
    return simulate_photo(receipt)


def preview_label(at):
    return next(e.label for e in at.expander if "What Gemini will see" in e.label)


def test_full_photo_flow(store, gemini, photo):
    at = no_exc(make_app(user="Bibi").run())
    assert button(at, "Read receipt").disabled

    at.file_uploader[0].set_value(("receipt.jpg", photo, "image/jpeg")).run()
    no_exc(at)
    assert [s.label for s in at.slider] == ["Tilt"], "no resolution slider"
    assert "What Gemini will see: 700 ×" in preview_label(at)

    fid = at.session_state["photo"]["file_id"]
    at.button(key=f"right_{fid}").click().run()
    w, h = (int(x) for x in preview_label(at).split(": ")[1].split(" px")[0].split(" × "))
    assert w > h, "portrait receipt is landscape after turning right"
    at.button(key=f"left_{fid}").click().run()
    at.slider[0].set_value(3.5).run()
    assert at.session_state["photo"]["view"] == (0, 3.5)
    at.slider[0].set_value(0.0).run()

    button(at, "Read receipt").click().run()
    no_exc(at)
    data, mime = gemini[-1]
    sent = Image.open(io.BytesIO(data))
    assert mime == "image/jpeg" and min(sent.size) == 700 and sent.mode == "L"
    assert at.session_state["draft"]["items"][0]["name"] == "Item read #1"
    assert not at.slider, "review step: the photo controls are off screen (no hidden 0-px cropper)"

    # Back to the photo step: controls are visible again, the photo and tilt are kept.
    button(at, "Change the crop or read again").click().run()
    no_exc(at)
    assert [s.label for s in at.slider] == ["Tilt"] and button(at, "Read again")
    at.slider[0].set_value(2.0).run()
    button(at, "Back to the items").click().run()
    assert not at.slider and at.session_state["draft"]["items"][0]["name"] == "Item read #1", "items kept"
    button(at, "Change the crop or read again").click().run()
    assert at.slider[0].value == 2.0, "tilt remembered"
    button(at, "Read again").click().run()
    no_exc(at)
    assert gemini[-1][0] != gemini[-2][0] and at.session_state["draft"]["items"][0]["name"] == "Item read #2"
    assert not at.slider, "back on the review step after reading again"

    button(at, "Save receipt").click().run()
    no_exc(at)
    assert len(store) == 1 and "draft" not in at.session_state and "photo" not in at.session_state
    assert at.file_uploader[0].value is None and not at.slider


def test_photo_and_adjustments_survive_a_visit_to_another_page(store, gemini, photo):
    at = no_exc(make_app(user="Bibi").run())
    at.file_uploader[0].set_value(("receipt.jpg", photo, "image/jpeg")).run()
    at.slider[0].set_value(2.5).run()
    at.switch_page("views/dashboard.py").run()
    at.switch_page("views/upload.py").run()
    no_exc(at)
    assert at.slider[0].value == 2.5 and any("photo you added earlier" in c.value for c in at.caption)
    assert not button(at, "Read receipt").disabled
    button(at, "Read receipt").click().run()
    assert len(gemini) == 1


def test_removing_the_file_forgets_the_photo(store, gemini, photo):
    at = no_exc(make_app(user="Bibi").run())
    at.file_uploader[0].set_value(("receipt.jpg", photo, "image/jpeg")).run()
    assert "photo" in at.session_state
    at.file_uploader[0].set_value(None).run()
    no_exc(at)
    assert "photo" not in at.session_state and not at.slider and button(at, "Read receipt").disabled


def test_pdf_is_sent_as_is(store, gemini):
    at = no_exc(make_app(user="Bibi").run())
    at.file_uploader[0].set_value(("e-receipt.pdf", b"%PDF-1.4 fake", "application/pdf")).run()
    no_exc(at)
    assert not at.slider
    button(at, "Read receipt").click().run()
    assert gemini[-1] == (b"%PDF-1.4 fake", "application/pdf")


def test_broken_image_is_explained(store, gemini):
    at = no_exc(make_app(user="Bibi").run())
    at.file_uploader[0].set_value(("broken.jpg", b"not an image", "image/jpeg")).run()
    no_exc(at)
    assert any("Couldn't open that image" in e.value for e in at.error)
    assert button(at, "Read receipt").disabled
