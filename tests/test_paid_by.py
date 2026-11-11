"""Logging a receipt someone else paid for: "I paid for this" (on by default) on the review form."""
from helpers import button, make_app, no_exc, save_receipt_for_test
from test_pages import TODAY, history_app, select_history_row, with_draft


def toggle(at):
    return next(t for t in at.toggle if "I paid for this" in t.label)


def test_upload_defaults_to_i_paid(store):
    at = no_exc(with_draft("Bibi").run())
    assert toggle(at).value is True
    button(at, "Save receipt").click().run()
    (saved,) = store.values()
    assert saved["paid_by"] == "Bibi" and saved["uploaded_by"] == "Bibi"


def test_turning_it_off_logs_it_for_the_other_person(store):
    at = no_exc(with_draft("Bibi").run())
    toggle(at).set_value(False).run()
    assert any("Paid by **Dad**" in c.value for c in at.caption)
    assert not [s for s in at.selectbox if s.label == "Who paid?"], "two people: no need to ask who"
    button(at, "Save receipt").click().run()
    no_exc(at)
    (saved,) = store.values()
    assert saved["paid_by"] == "Dad" and saved["uploaded_by"] == "Bibi"
    assert any("paid by Dad" in s.value for s in at.success)


def test_choice_survives_a_visit_to_another_page(store):
    at = no_exc(with_draft("Bibi").run())
    toggle(at).set_value(False).run()
    at.switch_page("views/dashboard.py").run()
    at.switch_page("views/upload.py").run()
    no_exc(at)
    assert toggle(at).value is False
    button(at, "Save receipt").click().run()
    assert next(iter(store.values()))["paid_by"] == "Dad"


def test_with_more_people_it_asks_who_paid(store):
    at = make_app(user="Bibi", family=["Bibi", "Dad", "Mum"])
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {"purchased_on": TODAY, "date_guessed": False, "store": "REWE", "total": 5.0,
                                 "files": [], "suggested": {}, "remembered": 0,
                                 "items": [{"name": "MILCH", "category": "Dairy & Eggs", "price": 5.0}]}
    no_exc(at.run())
    toggle(at).set_value(False).run()
    who = next(s for s in at.selectbox if s.label == "Who paid?")
    assert who.options == ["Dad", "Mum"]
    who.set_value("Mum").run()
    button(at, "Save receipt").click().run()
    assert next(iter(store.values()))["paid_by"] == "Mum"


def test_a_family_of_one_sees_no_toggle(store):
    at = make_app(user="Bibi", family=["Bibi"])
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {"purchased_on": TODAY, "date_guessed": False, "store": "REWE", "total": 5.0,
                                 "files": [], "suggested": {}, "remembered": 0,
                                 "items": [{"name": "MILCH", "category": "Dairy & Eggs", "price": 5.0}]}
    no_exc(at.run())
    assert not [t for t in at.toggle if "I paid" in t.label]
    button(at, "Save receipt").click().run()
    assert next(iter(store.values()))["paid_by"] == "Bibi"


def test_history_shows_and_changes_who_paid(store):
    rid = save_receipt_for_test("REWE", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 2.0}], user="Bibi")
    at = history_app("Dad")
    assert at.dataframe[0].value["Paid by"].tolist() == ["Bibi"]
    select_history_row(at, 0)
    no_exc(at)
    assert toggle(at).value is False, "Dad is looking at a receipt Bibi paid for"
    assert any("Paid by **Bibi**" in c.value for c in at.caption)
    toggle(at).set_value(True).run()
    button(at, "Save changes").click().run()
    no_exc(at)
    assert store[rid]["paid_by"] == "Dad" and store[rid]["uploaded_by"] == "Bibi" and store[rid]["updated_by"] == "Dad"


def test_dashboard_counts_spending_for_whoever_paid(store):
    from grocery import db

    db.save_receipt({"purchased_on": TODAY, "store": "REWE", "total": 30.0, "paid_by": "Dad"},
                    [{"name": "WEIN", "category": "Drinks", "price": 30.0}], "Bibi")
    save_receipt_for_test("Lidl", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 2.0}], user="Bibi")
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/dashboard.py").run()
    no_exc(at)
    by_member = next(d.value for d in at.dataframe if "paid_by" in d.value.columns)
    assert dict(zip(by_member["paid_by"], by_member["price"])) == {"Dad": 30.0, "Bibi": 2.0}


# --- "👤 Just for me": bought for the payer themselves, not for the family ---

def personal_toggle(at):
    return next(t for t in at.toggle if "Just for" in t.label)


def test_just_for_me_is_off_by_default(store):
    at = no_exc(with_draft("Bibi").run())
    assert personal_toggle(at).label == "👤 Just for me" and personal_toggle(at).value is False
    button(at, "Save receipt").click().run()
    assert next(iter(store.values()))["personal"] is False, "by default a receipt is for the family"


def test_just_for_me_is_saved_and_follows_the_payer(store):
    at = no_exc(with_draft("Bibi").run())
    personal_toggle(at).set_value(True).run()
    toggle(at).set_value(False).run()  # Dad paid
    assert personal_toggle(at).label == "👤 Just for Dad" and personal_toggle(at).value is True
    button(at, "Save receipt").click().run()
    no_exc(at)
    saved = next(iter(store.values()))
    assert saved["personal"] is True and saved["paid_by"] == "Dad"
    assert any("just for Dad" in s.value for s in at.success)


def test_history_marks_and_keeps_personal_receipts(store):
    from grocery import db

    rid = db.save_receipt({"purchased_on": TODAY, "store": "H&M", "total": 30.0, "personal": True},
                          [{"name": "SHIRT", "category": "Clothes & Shoes", "price": 30.0}], "Bibi")
    at = history_app("Dad")
    assert at.dataframe[0].value["Paid by"].tolist() == ["Bibi 👤"]
    select_history_row(at, 0)
    assert personal_toggle(at).value is True and personal_toggle(at).label == "👤 Just for Bibi"
    assert any("just for Bibi" in c.value for c in at.caption)
    button(at, "Save changes").click().run()
    no_exc(at)
    assert store[rid]["personal"] is True


def test_dashboard_splits_family_and_personal_spending(store):
    from grocery import db

    db.save_receipt({"purchased_on": TODAY, "store": "REWE", "total": 50.0},
                    [{"name": "EINKAUF", "category": "Pantry", "price": 50.0}], "Bibi")
    db.save_receipt({"purchased_on": TODAY, "store": "H&M", "total": 30.0, "personal": True},
                    [{"name": "SHIRT", "category": "Clothes & Shoes", "price": 30.0}], "Bibi")
    db.save_receipt({"purchased_on": TODAY, "store": "Lidl", "total": 20.0, "paid_by": "Dad"},
                    [{"name": "MILCH", "category": "Dairy & Eggs", "price": 20.0}], "Bibi")
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/dashboard.py").run()
    no_exc(at)
    t = next(d.value for d in at.dataframe if "own" in d.value.columns).set_index("paid_by")
    assert t.loc["Bibi", ["price", "shared", "own"]].tolist() == [80.0, 50.0, 30.0]
    assert t.loc["Dad", ["price", "shared", "own"]].tolist() == [20.0, 20.0, 0.0]


def test_person_label_merges_spellings_and_labels_imports():
    from grocery.utils import person_label

    family = ["Shiqing", "Charif"]
    assert [person_label(n, family) for n in ("Shiqing", "shiqing ", "SHIQING", "Charif")] == ["Shiqing"] * 3 + ["Charif"]
    assert person_label("sheet-import", family) == "📄 Imported" and person_label("Oma", family) == "Oma"
    assert person_label(None, family) == "Unknown"


def test_by_family_member_has_one_row_per_person_and_imports_last(store):
    from grocery import db

    for user, price, personal in [("sheet-import", 500.0, False), ("Bibi", 10.0, False), ("bibi", 20.0, True), ("Dad", 25.0, False)]:
        db.save_receipt({"purchased_on": TODAY, "store": "REWE", "total": price, "personal": personal},
                        [{"name": "X", "category": "Pantry", "price": price}], user)
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/dashboard.py").run()
    no_exc(at)
    t = next(d.value for d in at.dataframe if "own" in d.value.columns)
    assert t["paid_by"].tolist() == ["Bibi", "Dad", "📄 Imported"], "family by total, imports last even though biggest"
    assert t.set_index("paid_by").loc["Bibi", ["shared", "own", "price"]].tolist() == [10.0, 20.0, 30.0]


def test_reading_again_keeps_who_paid_and_just_for_me(store, monkeypatch):
    from unittest import mock

    from grocery import extract

    fake = {"date": TODAY, "date_guessed": False, "store": "REWE", "total": 1.0, "tokens": 900,
            "items": [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.0, "quantity": 1}]}
    monkeypatch.setattr(extract, "extract_receipt", mock.Mock(return_value=dict(fake)))
    at = make_app(user="Bibi")
    at.run()
    at.file_uploader[0].set_value([("r.pdf", b"%PDF-1.4", "application/pdf")]).run()
    button(at, "Read receipt").click().run()
    no_exc(at)
    toggle(at).set_value(False).run()
    personal_toggle(at).set_value(True).run()
    button(at, "Change the crop or read again").click().run()
    monkeypatch.setattr(extract, "extract_receipt", mock.Mock(return_value=dict(fake)))
    button(at, "Read again").click().run()
    no_exc(at)
    assert at.session_state["draft"]["paid_by"] == "Dad" and at.session_state["draft"]["personal"] is True
    assert toggle(at).value is False and personal_toggle(at).value is True


def test_people_without_a_profile_photo_get_an_empty_cell_not_none():
    from grocery.ui import avatar_data_uri

    assert avatar_data_uri("📄 Imported").startswith("data:image/png;base64,")
