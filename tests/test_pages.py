"""Review/save, duplicate warning, dashboard, history and the backup button, via AppTest."""
import datetime
import io

from helpers import button, make_app, no_exc
from PIL import Image

from grocery.utils import month_label

TODAY = datetime.date.today()
LAST_MONTH = TODAY.replace(day=1) - datetime.timedelta(days=1)


def png():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


def with_draft(user, **fields):
    at = make_app(user=user)
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {
        "date": TODAY, "date_guessed": False, "store": "REWE", "total": 5.0, "file": None, "mime": None,
        "filename": None, "items": [{"name": "MILCH", "category": "Dairy", "price": 5.0}], **fields,
    }
    return at


def test_manual_entry_cannot_save_without_items(store):
    at = no_exc(make_app(user="Bibi").run())
    button(at, "Enter manually").click().run()
    no_exc(at)
    assert button(at, "Save receipt").disabled


def test_review_warns_then_saves_tagged_with_name(store):
    at = with_draft(
        "Bibi", date_guessed=True, total=5.0, file=png(), mime="image/png", filename="r.png",
        items=[{"name": "MILCH", "category": "Dairy", "price": 1.99}, {"name": "AEPFEL", "category": "Produce", "price": 2.5}],
    )
    no_exc(at.run())
    warnings = " ".join(w.value for w in at.warning)
    assert "No date found" in warnings and "add up to **€4.49**" in warnings
    button(at, "Save receipt").click().run()
    no_exc(at)
    (saved,) = store.values()
    assert saved["uploaded_by"] == "Bibi" and len(saved["items"]) == 2
    assert any("Saved 2 items from REWE" in s.value for s in at.success)
    assert "draft" not in at.session_state


def test_duplicate_warning_matches_same_total_despite_different_store_spelling(store):
    first = no_exc(with_draft("Bibi", store="REWE Markt GmbH").run())
    button(first, "Save receipt").click().run()

    at = no_exc(with_draft("Dad", store="Rewe City").run())
    assert any("Bibi already added a REWE Markt GmbH receipt" in w.value for w in at.warning), [w.value for w in at.warning]
    other_total = no_exc(with_draft("Dad", store="Rewe City", total=7.0, items=[{"name": "X", "category": "Other", "price": 7.0}]).run())
    assert not any("already added" in w.value for w in other_total.warning)


def seed(store_fixture):
    from grocery import db

    db.save_receipt({"purchased_on": TODAY, "store": "REWE", "total": 4.49},
                    [{"name": "MILCH", "category": "Dairy", "price": 1.99}, {"name": "AEPFEL", "category": "Produce", "price": 2.5}], "Bibi")
    db.save_receipt({"purchased_on": LAST_MONTH, "store": "Aldi", "total": 10.0},
                    [{"name": "SEIFE", "category": "Household", "price": 10.0}], "Dad")


def test_dashboard_and_month_picker(store):
    seed(store)
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/dashboard.py").run()
    no_exc(at)
    metrics = {m.label: (m.value, m.delta) for m in at.metric}
    assert metrics["Spent"][0] == "€4.49" and "-€5.51 vs" in metrics["Spent"][1]
    assert metrics["Receipts"][0] == "1" and metrics["Items"][0] == "2"
    at.selectbox[0].select(month_label(LAST_MONTH)).run()
    assert {m.label: m.value for m in at.metric}["Spent"] == "€10.00"


def test_history_edit_and_delete(store):
    seed(store)
    rid = next(k for k, r in store.items() if r["store"] == "REWE")
    at = make_app(user="Dad")
    at.run()
    at.switch_page("views/history.py").run()
    no_exc(at)
    assert at.dataframe[0].value["Store"].tolist() == ["REWE"]

    at.session_state[f"receipts_{month_label(TODAY)}_0"] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run()
    at.text_input[0].input("REWE City").run()
    button(at, "Save changes").click().run()
    no_exc(at)
    assert store[rid]["store"] == "REWE City" and store[rid]["updated_by"] == "Dad" and store[rid]["uploaded_by"] == "Bibi"

    at.session_state[f"receipts_{month_label(TODAY)}_1"] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run()
    button(at, "Yes, delete it").click().run()
    no_exc(at)
    assert rid not in store


def test_sidebar_has_backup_button_and_qr_page_works(store):
    at = no_exc(make_app(user="Bibi").run())
    assert any("Download backup" in str(getattr(e, "proto", "")) for e in at.sidebar)
    at.switch_page("views/qr.py").run()
    no_exc(at)
    assert at.title[0].value == "📱 Fridge QR code"
