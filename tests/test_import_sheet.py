import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_sheet.py"
spec = importlib.util.spec_from_file_location("import_sheet", SCRIPT)
import_sheet = importlib.util.module_from_spec(spec)
sys.modules["import_sheet"] = import_sheet
spec.loader.exec_module(import_sheet)

HEADERS = ["Date", "Store", "Item", "Category", "Price", "Week", "Month", "Receipt Total"]


def test_parses_realigns_and_groups_old_sheet_rows():
    values = [
        HEADERS,
        ["2026-11-01", "Lidl", "Milk", "dairy", "€1,99", "2026-W44", "2026-11", "5,49"],
        ["2026-11-01", "Lidl", "Bread", "Bakery", "3.50", "2026-W44", "2026-11", "5,49"],
        ["", "", "2026-11-02", "Aldi", "Soap", "Household", "2", "2026-W45", "2026-11", "2"],  # shifted right
        ["", "", "", "", "", "", "", ""],
        ["Total", "", "", "", "10", "", "", ""],
        ["oops", "X", "Y", "Other", "1", "", "", "1"],  # bad date
        ["2026-11-02", "Aldi", "Soap", "Weird", "2", "2026-W45", "2026-11", "2"],
    ]
    receipts = import_sheet.group_receipts(import_sheet.parse_rows(values))
    assert len(receipts) == 2
    (lidl, lidl_items), (aldi, aldi_items) = receipts
    assert lidl["total"] == 5.49 and [i["category"] for i in lidl_items] == ["Dairy", "Bakery"]
    assert lidl_items[0]["price"] == 1.99
    assert aldi["store"] == "Aldi" and len(aldi_items) == 2 and aldi_items[1]["category"] == "Other"
    assert import_sheet.parse_rows([HEADERS, ["2026-11-01", "REWE Markt GmbH", "Milk", "Dairy", "1", "", "", "1"]])[0]["store"] == "REWE"


def test_unreadable_money_is_reported_not_silently_zeroed(capsys):
    rows = import_sheet.parse_rows([
        HEADERS,
        ["2026-11-01", "Lidl", "Milk", "Dairy", "1.234,56", "", "", "EUR 1.234,56"],
        ["2026-11-02", "Lidl", "Bread", "Bakery", "n/a", "", "", "??"],
    ])
    assert rows[0]["item"]["price"] == 1234.56 and rows[0]["total"] == 1234.56
    assert rows[1]["item"]["price"] == 0.0 and rows[1]["total"] is None
    out = capsys.readouterr().out
    assert "unreadable price 'n/a'" in out and "unreadable receipt total '??'" in out


def test_already_imported_receipts_are_recognised_for_resuming():
    receipt = {"purchased_on": __import__("datetime").date(2026, 11, 1), "store": "Lidl", "total": 5.49,
               "items": [{"name": "Milk"}, {"name": "Bread"}]}
    from_db = {"purchased_on": "2026-11-01", "store": "Lidl", "total": 5.49, "items": [{"id": 1}, {"id": 2}]}
    assert import_sheet.fingerprint(receipt) == import_sheet.fingerprint(from_db)
    assert import_sheet.fingerprint({**from_db, "items": [{"id": 1}]}) != import_sheet.fingerprint(receipt)
