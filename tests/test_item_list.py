"""The phone-friendly item list: one line per item, ✏️ opens a form for it."""
from helpers import button, no_exc
from test_pages import history_app, select_history_row, with_draft

from grocery.utils import parse_quantity

ITEMS = [{"name": "MILCH", "category": "Dairy & Eggs", "price": 1.99, "quantity": 1},
         {"name": "BANANEN", "category": "Fruit", "price": 0.74, "quantity": 0.512}]


def list_view(at):
    at.button_group(key="items_view").set_value("list").run()
    return no_exc(at)


def edit_button(at, n):
    return [b for b in at.button if b.label == "✏️"][n]


def field(at, label):
    return next(t for t in at.text_input if t.label == label)


def test_parse_quantity_takes_commas_and_defaults_to_one():
    assert parse_quantity("0,512") == 0.512 and parse_quantity("2") == 2.0 and parse_quantity(" 1.5 ") == 1.5
    assert parse_quantity("") == 1.0 and parse_quantity(None) == 1.0
    assert parse_quantity("abc") is None and parse_quantity("0") is None


def test_list_shows_each_item_on_one_line(store):
    at = list_view(with_draft("Bibi", total=2.73, items=ITEMS).run())
    texts = [m.value for m in at.markdown]
    assert "**MILCH**  \n:gray[Dairy & Eggs]" in texts and "**€1.99**" in texts
    assert any("Fruit · ×0,512" in t for t in texts), "quantity shown when it isn't 1"
    assert not at.dataframe, "no table in the list view"


def test_edit_an_item_with_comma_decimals_then_save(store):
    at = list_view(with_draft("Bibi", total=2.73, items=ITEMS).run())
    edit_button(at, 0).click().run()
    assert field(at, "Price (€)").value == "1,99"
    field(at, "Item").set_value("H-MILCH")
    field(at, "Price (€)").set_value("3,98")
    field(at, "Qty").set_value("2")
    button(at, "Done").click().run()
    no_exc(at)
    assert at.session_state["draft"]["items"][0] == {"name": "H-MILCH", "category": "Dairy & Eggs", "price": 3.98, "quantity": 2.0}
    button(at, "Save receipt").click().run()
    no_exc(at)
    (saved,) = store.values()
    assert saved["items"][0]["name"] == "H-MILCH" and saved["items"][0]["quantity"] == 2.0 and len(saved["items"]) == 2


def test_add_and_remove_items(store):
    at = list_view(with_draft("Bibi", total=2.73, items=ITEMS).run())
    button(at, "Add item").click().run()
    field(at, "Item").set_value("PFAND")
    next(s for s in at.selectbox if s.label == "Category").set_value("Other")
    field(at, "Price (€)").set_value("-0,25").run()  # leaving the field updates the form, enabling Done
    button(at, "Done").click().run()
    no_exc(at)
    assert [i["name"] for i in at.session_state["draft"]["items"]] == ["MILCH", "BANANEN", "PFAND"]
    assert at.session_state["draft"]["items"][2]["price"] == -0.25, "discounts and Leergut can be negative"
    edit_button(at, 1).click().run()
    button(at, "Remove").click().run()
    no_exc(at)
    assert [i["name"] for i in at.session_state["draft"]["items"]] == ["MILCH", "PFAND"]


def test_bad_numbers_are_explained_and_not_saved(store):
    at = list_view(with_draft("Bibi", total=2.73, items=ITEMS).run())
    edit_button(at, 0).click().run()
    field(at, "Price (€)").set_value("abc")
    field(at, "Qty").set_value("0").run()
    errors = [e.value for e in at.error]
    assert any("price isn't a number" in e for e in errors) and any("quantity must be" in e for e in errors)
    assert button(at, "Done").disabled
    assert at.session_state["draft"]["items"][0]["price"] == 1.99


def test_table_shows_changes_made_in_the_list(store):
    at = list_view(with_draft("Bibi", total=2.73, items=ITEMS).run())
    edit_button(at, 1).click().run()
    field(at, "Price (€)").set_value("1,00")
    button(at, "Done").click().run()
    at.button_group(key="items_view").set_value("table").run()
    no_exc(at)
    assert at.dataframe[0].value["price"].tolist() == [1.99, 1.0]


def test_item_names_are_shown_as_plain_text(store):
    at = list_view(with_draft("Bibi", total=1.0, items=[{"name": "*SALE* [x](y)", "category": "Other", "price": 1.0}]).run())
    assert any(m.value.startswith(r"**\*SALE\* \[x\]\(y\)**") for m in at.markdown)


def test_phones_start_in_the_list_view(store, monkeypatch):
    from grocery import ui

    monkeypatch.setattr(ui, "_is_phone", lambda: True)
    at = no_exc(with_draft("Bibi", total=2.73, items=ITEMS).run())
    assert at.button_group(key="items_view").value == "list" and not at.dataframe


def test_history_can_be_edited_in_the_list_view(store):
    from helpers import save_receipt_for_test

    rid = save_receipt_for_test("REWE", [dict(i) for i in ITEMS], user="Bibi")
    at = select_history_row(history_app("Dad"), 0)
    list_view(at)
    edit_button(at, 0).click().run()
    field(at, "Price (€)").set_value("2,19")
    button(at, "Done").click().run()
    button(at, "Save changes").click().run()
    no_exc(at)
    assert store[rid]["items"][0]["price"] == 2.19 and store[rid]["updated_by"] == "Dad"
