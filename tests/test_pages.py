"""Review/save, duplicate warning, dashboard, history and the backup button, via AppTest."""
import datetime
import io

from helpers import button, make_app, no_exc
from PIL import Image

from grocery.utils import month_label, today

TODAY = today()
LAST_MONTH = TODAY.replace(day=1) - datetime.timedelta(days=1)


def png():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


def with_draft(user, **fields):
    at = make_app(user=user)
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {
        "purchased_on": TODAY, "date_guessed": False, "store": "REWE", "total": 5.0, "file": None, "mime": None,
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
    assert any("Bibi already added a REWE receipt" in w.value for w in at.warning), [w.value for w in at.warning]
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

    select_history_row(at, 0)
    at.selectbox(key=f"edit_{rid}_0_store").set_value("Edeka").run()
    button(at, "Save changes").click().run()
    no_exc(at)
    assert store[rid]["store"] == "Edeka" and store[rid]["updated_by"] == "Dad" and store[rid]["uploaded_by"] == "Bibi"
    assert any("Receipt updated" in x.value for x in at.success)

    select_history_row(at, 0)
    button(at, "Yes, delete it").click().run()
    no_exc(at)
    assert rid not in store


def test_account_menu_has_backup_and_qr_page_works(store):
    at = no_exc(make_app(user="Bibi").run())
    assert not at.sidebar.children, "navigation is a link row, not the sidebar"
    assert "Download backup" in str(at.get("download_button")[0].proto)
    assert button(at, "Sign out")
    at.switch_page("views/qr.py").run()
    no_exc(at)
    assert at.title[0].value == "📱 Fridge QR code"


# --- Regression tests for bugs found in review ---------------------------------------------

import hashlib  # noqa: E402

from grocery import db as db_module  # noqa: E402
from grocery.utils import month_bounds  # noqa: E402


def select_history_row(at, row, month=None):
    """Select a row in the History table the way a tap would (the table key depends on its contents)."""
    month = month or month_label(TODAY)
    receipts = db_module.load_receipts(*month_bounds(month))
    ids_hash = hashlib.sha1("|".join(r["id"] for r in receipts).encode()).hexdigest()[:10]
    key = f"receipts_{month}_{at.session_state['history_rev'] if 'history_rev' in at.session_state else 0}_{ids_hash}"
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    return at.run()


def history_app(user):
    at = make_app(user=user)
    at.run()
    at.switch_page("views/history.py").run()
    return no_exc(at)


def test_refund_receipt_with_negative_total_can_be_saved(store):
    at = with_draft("Bibi", total=-4.99, items=[{"name": "RETOURE", "category": "Other", "price": -4.99}])
    no_exc(at.run())
    button(at, "Save receipt").click().run()
    no_exc(at)
    (saved,) = store.values()
    assert saved["total"] == -4.99


def test_history_opens_a_receipt_with_negative_total(store):
    db_module.save_receipt({"purchased_on": TODAY, "store": "Pfandautomat", "total": -2.0},
                           [{"name": "PFAND", "category": "Other", "price": -2.0}], "Bibi")
    at = select_history_row(history_app("Dad"), 0)
    no_exc(at)
    assert at.subheader[0].value.startswith("Pfandautomat")


def test_history_keeps_the_receipt_you_opened_when_someone_else_adds_one(store):
    db_module.save_receipt({"purchased_on": TODAY.replace(day=1), "store": "Aldi", "total": 1.0},
                           [{"name": "A", "category": "Other", "price": 1.0}], "Dad")
    at = select_history_row(history_app("Bibi"), 0)
    assert at.subheader[0].value.startswith("Aldi")
    db_module.save_receipt({"purchased_on": TODAY, "store": "Edeka", "total": 9.0},  # sorts first now
                           [{"name": "B", "category": "Other", "price": 9.0}], "Dad")
    no_exc(at.run())
    assert at.subheader[0].value.startswith("Aldi")


def test_delete_hits_the_receipt_you_chose_even_if_the_list_changed(store):
    db_module.save_receipt({"purchased_on": TODAY.replace(day=1), "store": "Aldi", "total": 1.0},
                           [{"name": "A", "category": "Other", "price": 1.0}], "Dad")
    aldi = next(iter(store))
    at = select_history_row(history_app("Dad"), 0)
    db_module.save_receipt({"purchased_on": TODAY, "store": "Edeka", "total": 9.0},
                           [{"name": "B", "category": "Other", "price": 9.0}], "Bibi")
    at.button(key=f"delete_{aldi}").click().run()
    no_exc(at)
    assert aldi not in store and [r["store"] for r in store.values()] == ["Edeka"]


def test_history_survives_the_open_receipt_being_deleted_elsewhere(store, monkeypatch):
    for day, name in ((1, "Aldi"), (2, "Lidl")):
        db_module.save_receipt({"purchased_on": TODAY.replace(day=day), "store": name, "total": float(day)},
                               [{"name": "X", "category": "Other", "price": float(day)}], "Dad")
    at = select_history_row(history_app("Bibi"), 1)  # last row
    opened = at.subheader[0].value
    del store[next(k for k, r in store.items() if opened.startswith(r["store"]))]
    no_exc(at.run())  # used to raise IndexError
    assert not at.subheader, "editor closes when its receipt is gone"

    at = select_history_row(history_app("Bibi"), 0)
    monkeypatch.setattr(db_module, "save_receipt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("receipt not found")))
    button(at, "Save changes").click().run()
    no_exc(at)
    assert any("Someone else may have just deleted it" in e.value for e in at.error)


def test_review_corrections_survive_a_visit_to_another_page(store):
    at = no_exc(with_draft("Bibi").run())
    at.selectbox(key="draft1_store").set_value("Edeka")
    at.number_input(key="draft1_total").set_value(7.25).run()
    at.switch_page("views/dashboard.py").run()
    at.switch_page("views/upload.py").run()
    no_exc(at)
    assert at.selectbox(key="draft1_store").value == "Edeka" and at.number_input(key="draft1_total").value == 7.25
    button(at, "Save receipt").click().run()
    (saved,) = store.values()
    assert saved["store"] == "Edeka" and saved["total"] == 7.25


def test_future_date_is_flagged(store):
    at = no_exc(with_draft("Bibi", purchased_on=TODAY + datetime.timedelta(days=30)).run())
    assert any("in the future" in w.value for w in at.warning)


def test_database_down_shows_a_message_not_a_traceback(store, monkeypatch):
    def down(*a, **k):
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(db_module, "load_item_lines", down)
    at = make_app(user="Bibi")
    at.run()
    for page in ("views/dashboard.py", "views/history.py"):
        at.switch_page(page).run()
        no_exc(at)
        assert any("database may be waking up" in e.value for e in at.error), page


def test_duplicate_check_failure_does_not_block_saving(store, monkeypatch):
    monkeypatch.setattr(db_module, "find_duplicates", lambda *a: (_ for _ in ()).throw(ConnectionError()))
    at = no_exc(with_draft("Bibi").run())
    assert any("Couldn't check for duplicates" in c.value for c in at.caption)
    button(at, "Save receipt").click().run()
    assert len(store) == 1


def test_failed_save_keeps_the_draft(store, monkeypatch):
    monkeypatch.setattr(db_module, "save_receipt", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    at = no_exc(with_draft("Bibi").run())
    button(at, "Save receipt").click().run()
    no_exc(at)
    assert any("Couldn't save the receipt" in e.value for e in at.error) and "draft" in at.session_state


# --- Stores ---------------------------------------------------------------------------------

def test_store_dropdown_lists_chains_and_maps_raw_names(store):
    from grocery.config import STORES

    at = no_exc(with_draft("Bibi", store="").run())
    box = at.selectbox(key="draft1_store")
    assert box.options[: len(STORES)] == list(STORES) and box.value is None

    at = no_exc(with_draft("Bibi", store="rewe city gmbh").run())  # raw name as on the receipt
    assert at.selectbox(key="draft1_store").value == "REWE"
    button(at, "Save receipt").click().run()
    assert [r["store"] for r in store.values()] == ["REWE"]


def test_store_that_is_not_a_chain_is_kept_as_printed(store):
    at = no_exc(with_draft("Bibi", store="Bäckerei Schmidt").run())
    assert at.selectbox(key="draft1_store").value == "Bäckerei Schmidt"
    button(at, "Save receipt").click().run()
    assert [r["store"] for r in store.values()] == ["Bäckerei Schmidt"]


def test_store_dropdown_offers_stores_used_before(store):
    db_module.save_receipt({"purchased_on": TODAY, "store": "Bäckerei Schmidt", "total": 3.0},
                           [{"name": "BROT", "category": "Bakery", "price": 3.0}], "Dad")
    at = no_exc(with_draft("Bibi", store="").run())
    assert "Bäckerei Schmidt" in at.selectbox(key="draft1_store").options


def test_dashboard_spending_by_store(store):
    for name, total in (("REWE", 30.0), ("Lidl", 10.0), ("REWE", 20.0)):
        db_module.save_receipt({"purchased_on": TODAY, "store": name, "total": total},
                               [{"name": "X", "category": "Other", "price": total}], "Bibi")
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/dashboard.py").run()
    no_exc(at)
    by_store = next(d.value for d in at.dataframe if "store" in d.value.columns)
    assert by_store["store"].tolist() == ["REWE", "Lidl"]
    assert by_store["spent"].tolist() == [50.0, 10.0] and by_store["receipts"].tolist() == [2, 1]
    assert abs(by_store["share"].iloc[0] - 50 / 60) < 1e-9
