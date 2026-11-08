"""Price tracking page."""
import datetime

from helpers import make_app, no_exc, save_receipt_for_test

from grocery.utils import item_key, today

TODAY = today()
save = save_receipt_for_test


def prices_page():
    at = make_app(user="Bibi")
    at.run()
    at.switch_page("views/prices.py").run()
    return no_exc(at)


def test_price_changes_and_lookup(store):
    d1, d2 = TODAY - datetime.timedelta(days=30), TODAY - datetime.timedelta(days=2)
    save("REWE", [{"name": "BUTTER MILD", "category": "Dairy & Eggs", "price": 1.99}], day=d1)
    save("REWE", [{"name": "BUTTER MILD", "category": "Dairy & Eggs", "price": 2.29}], day=d2)
    save("Lidl", [{"name": "Butter mild", "category": "Dairy & Eggs", "price": 1.89}], day=d2)
    save("REWE", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.15}], day=d1)
    save("REWE", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.17}], day=d2)  # +2%: below threshold
    at = prices_page()
    changes = at.dataframe[0].value
    assert changes["item"].tolist() == ["BUTTER MILD"] and changes["store"].tolist() == ["REWE"]
    assert round(changes["change"].iloc[0]) == 15
    at.selectbox(key="prices_item").set_value(item_key("BUTTER MILD")).run()
    no_exc(at)
    assert any("Cheapest lately: **Lidl** at €1.89" in s.value for s in at.success)


def test_prices_page_explains_when_there_is_nothing_to_track(store):
    save("REWE", [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.15}])
    assert any("at least twice" in i.value for i in prices_page().info)


def test_buying_two_is_not_a_price_change_but_a_real_rise_still_is(store):
    d1, d2, d3 = (TODAY - datetime.timedelta(days=n) for n in (20, 10, 2))
    save("Lidl", [{"name": "JOGHURT NATUR", "category": "Dairy & Eggs", "price": 0.89, "quantity": 1}], day=d1)
    save("Lidl", [{"name": "JOGHURT NATUR", "category": "Dairy & Eggs", "price": 1.78, "quantity": 2}], day=d2)
    at = prices_page()
    assert not any(d.value is not None and "item" in d.value.columns and len(d.value) for d in at.dataframe), \
        "2 x 0.89 is the same price per unit"
    save("Lidl", [{"name": "JOGHURT NATUR", "category": "Dairy & Eggs", "price": 1.98, "quantity": 2}], day=d3)
    changes = prices_page().dataframe[0].value
    assert changes["item"].tolist() == ["JOGHURT NATUR"] and changes["now"].iloc[0] == 0.99
    assert round(changes["change"].iloc[0]) == 11
