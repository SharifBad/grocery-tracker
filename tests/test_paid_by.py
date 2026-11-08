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
