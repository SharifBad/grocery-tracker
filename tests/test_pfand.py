"""Pfand: deposits paid vs returned."""
import datetime

from helpers import make_app, no_exc, save_receipt_for_test

from grocery.utils import today

TODAY = today()
save = save_receipt_for_test


def dashboard(user="Bibi"):
    at = make_app(user=user)
    at.run()
    at.switch_page("views/dashboard.py").run()
    return no_exc(at)


def test_pfand_paid_returned_and_still_out(store):
    last_month = TODAY.replace(day=1) - datetime.timedelta(days=3)
    save("REWE", [{"name": "PFAND 0,25", "category": "Other", "price": 3.0}], day=last_month)
    save("REWE", [{"name": "PFAND 0,25", "category": "Other", "price": 1.5}, {"name": "WASSER", "category": "Drinks", "price": 2.0}])
    save("REWE", [{"name": "LEERGUT", "category": "Other", "price": -2.25}], total=-2.25)
    at = dashboard()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Paid this month"] == "€1.50" and metrics["Returned this month"] == "€2.25"
    assert metrics["Still out (all time)"] == "€2.25"


def test_no_pfand_section_without_deposits(store):
    save("REWE", [{"name": "WASSER", "category": "Drinks", "price": 2.0}])
    assert "Paid this month" not in {m.label for m in dashboard().metric}
