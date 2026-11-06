"""Search all receipts from the History page."""
import datetime

from helpers import make_app, no_exc, save_receipt_for_test

from grocery.utils import month_label, today

TODAY = today()
save = save_receipt_for_test


def test_search_finds_items_across_months_and_opens_the_receipt(store):
    old = TODAY.replace(day=1) - datetime.timedelta(days=40)
    old_id = save("Rossmann", [{"name": "KATZENFUTTER NASS", "category": "Pet", "price": 6.99}], day=old)
    save("REWE", [{"name": "KATZENFUTTER TROCKEN", "category": "Pet", "price": 4.49}, {"name": "MILCH", "category": "Dairy & Eggs", "price": 1.0}])
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/history.py").run()
    at.text_input(key="history_search").input("katzenfutter").run()
    no_exc(at)
    results = at.dataframe[0].value
    assert sorted(results["name"]) == ["KATZENFUTTER NASS", "KATZENFUTTER TROCKEN"]
    assert any("2 items · €11.48" in c.value for c in at.caption)
    # A tap on a result runs open_from_search, which uses these (receipt, month) pairs...
    row = results["name"].tolist().index("KATZENFUTTER NASS")
    assert at.session_state["_history_search_hits"][row] == (old_id, month_label(old))
    # ...to switch to that month and open the receipt (the tap itself is tested in a real browser).
    at.session_state["history_month"] = month_label(old)
    at.session_state["history_selected"] = old_id
    at.session_state["history_table"] = None
    at.text_input(key="history_search").input("").run()
    no_exc(at)
    assert at.subheader[0].value.startswith("Rossmann")


def test_search_by_store_and_category(store):
    save("dm", [{"name": "ZAHNPASTA", "category": "Skin & Body Care", "price": 1.95}])
    save("REWE", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.0}])
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/history.py").run()
    for query, expected in (("dm-drogerie", ["ZAHNPASTA"]), ("skin", ["ZAHNPASTA"]), ("milch", ["MILCH"])):
        at.text_input(key="history_search").input(query).run()
        no_exc(at)
        assert at.dataframe[0].value["name"].tolist() == expected, query
