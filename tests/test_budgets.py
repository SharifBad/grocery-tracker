"""Monthly budgets on the dashboard."""
from unittest import mock

from conftest import receipts_fixture_extras as extras
from helpers import make_app, no_exc, save_receipt_for_test

from grocery import db as db_module

save = save_receipt_for_test


def dashboard(user="Bibi"):
    at = make_app(user=user)
    at.run()
    at.switch_page("views/dashboard.py").run()
    return no_exc(at)


def test_budget_progress_and_warnings(store):
    save("REWE", [{"name": "A", "category": "Snacks & Sweets", "price": 45.0}, {"name": "B", "category": "Pantry", "price": 315.0}])
    extras["budgets"].update({"TOTAL": 400.0, "Snacks & Sweets": 40.0})
    at = dashboard()
    texts = [str(p.proto) for p in at.get("progress")]
    assert any("€360.00 of €400.00 (90%)" in t for t in texts) and any("€45.00 of €40.00 (112%)" in t for t in texts)
    assert any("€40.00 left this month" in w.value for w in at.warning)
    assert any("Snacks & Sweets is over budget by €5.00" in e.value for e in at.error)


def test_budgets_can_be_set_from_the_dashboard(store):
    save("REWE", [{"name": "A", "category": "Pantry", "price": 10.0}])
    at = dashboard()
    at.number_input[0].set_value(450.0)
    next(b for b in at.button if b.label == "Save budgets").click().run()
    no_exc(at)
    assert extras["budgets"]["TOTAL"] == 450.0 and any("Budgets saved" in s.value for s in at.success)


def test_no_budget_table_is_not_an_error(store, monkeypatch):
    monkeypatch.setattr(db_module, "load_budgets", mock.Mock(side_effect=RuntimeError("relation budgets does not exist")))
    save("REWE", [{"name": "A", "category": "Pantry", "price": 10.0}])
    at = dashboard()
    assert not at.get("progress")
