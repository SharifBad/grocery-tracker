"""Remembered category corrections."""
from unittest import mock

from conftest import receipts_fixture_extras as extras
from helpers import button, make_app, no_exc, save_receipt_for_test

from grocery import db as db_module
from grocery import extract
from grocery.utils import today

TODAY = today()
save = save_receipt_for_test


def draft_app(user="Bibi", **fields):
    at = make_app(user=user)
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {
        "purchased_on": TODAY, "date_guessed": False, "store": "REWE", "total": 3.0, "files": [], "remembered": 0,
        "items": [{"name": "HAFERFL. ZART", "category": "Snacks & Sweets", "price": 3.0}],
        "suggested": {"haferfl zart": "Snacks & Sweets"}, **fields,
    }
    return at


def test_a_corrected_category_is_remembered_on_save(store):
    # Gemini suggested Snacks & Sweets; the user changed it to Pantry in the review table.
    at = no_exc(draft_app(items=[{"name": "HAFERFL. ZART", "category": "Pantry", "price": 3.0}]).run())
    button(at, "Save receipt").click().run()
    assert extras["memory"] == {"haferfl zart": "Pantry"}


def test_unchanged_categories_are_not_remembered(store):
    at = no_exc(draft_app().run())
    button(at, "Save receipt").click().run()
    assert extras["memory"] == {}


def test_remembered_categories_are_applied_after_reading(store, monkeypatch):
    extras["memory"]["haferfl zart"] = "Pantry"
    monkeypatch.setattr(extract, "extract_receipt", lambda data, mime=None, on_progress=None: {
        "date": TODAY, "date_guessed": False, "store": "REWE", "total": 3.0, "tokens": 900,
        "items": [{"name": "Haferfl. Zart", "category": "Snacks & Sweets", "price": 3.0}]})
    at = no_exc(make_app(user="Bibi").run())
    at.file_uploader[0].set_value([("e.pdf", b"%PDF-1.4", "application/pdf")]).run()
    button(at, "Read receipt").click().run()
    no_exc(at)
    assert at.session_state["draft"]["items"][0]["category"] == "Pantry"
    assert any("1 category set from your earlier corrections" in c.value for c in at.caption)


def test_history_edit_remembers_the_new_category(store):
    from test_pages import history_app, select_history_row

    rid = save("REWE", [{"name": "KNAECKEBROT", "category": "Snacks & Sweets", "price": 1.5}])
    at = select_history_row(history_app("Dad"), 0)
    # Change the category the way the editor would hold it after a tap in the table.
    values = at.session_state[f"history_values_{rid}_0"]
    values["items"][0]["category"] = "Bakery"
    at.session_state[f"edit_{rid}_0_items_base"] = values["items"]
    at.run()
    button(at, "Save changes").click().run()
    no_exc(at)
    assert extras["memory"].get("knaeckebrot") == "Bakery"


def test_memory_failure_never_blocks_saving(store, monkeypatch):
    monkeypatch.setattr(db_module, "remember_categories", mock.Mock(side_effect=ConnectionError))
    at = no_exc(draft_app(items=[{"name": "X", "category": "Pantry", "price": 3.0}]).run())
    button(at, "Save receipt").click().run()
    no_exc(at)
    assert len(store) == 1
