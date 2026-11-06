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
    assert any("adjust and read again" in e.label for e in at.expander)

    at.slider[0].set_value(2.0).run()
    button(at, "Read again").click().run()
    no_exc(at)
    assert gemini[-1][0] != gemini[-2][0] and at.session_state["draft"]["items"][0]["name"] == "Item read #2"

    button(at, "Save receipt").click().run()
    no_exc(at)
    assert len(store) == 1 and "draft" not in at.session_state and "photo" not in at.session_state
    assert at.file_uploader[0].value is None


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
