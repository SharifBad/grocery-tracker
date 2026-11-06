import datetime

import pytest

from grocery.utils import (
    looks_like_duplicate,
    month_bounds,
    normalize_category,
    pretty_month,
    same_store,
    shift_month,
    store_key,
    to_money,
    week_label,
)


@pytest.mark.parametrize("raw, expected", [("€1,99", 1.99), ("$2.50", 2.5), (3, 3.0), (None, 0.0), ("abc", 0.0), (" 4,2 ", 4.2)])
def test_to_money(raw, expected):
    assert to_money(raw) == expected


def test_normalize_category():
    assert normalize_category("dairy") == "Dairy"
    assert normalize_category(" Produce ") == "Produce"
    assert normalize_category("Snacks") == "Other"
    assert normalize_category(None) == "Other"


def test_week_label_uses_iso_year():
    assert week_label(datetime.date(2027, 1, 1)) == "2026-W53"
    assert week_label(datetime.date(2024, 12, 30)) == "2025-W01"


def test_month_helpers():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert month_bounds("2026-12") == (datetime.date(2026, 12, 1), datetime.date(2027, 1, 1))
    assert pretty_month("2026-11") == "November 2026"


def test_store_names():
    assert store_key("REWE Markt GmbH") == "rewe"
    assert same_store("REWE Markt GmbH", "REWE")
    assert same_store("Lidl Dienstleistung", "LIDL")
    assert same_store("Edeka Müller", "EDEKA Center Müller")
    assert not same_store("Aldi Süd", "Lidl")
    assert not same_store("", "Lidl")


def test_duplicate_rule():
    saved = {"store": "REWE Markt GmbH", "total": 12.34}
    assert looks_like_duplicate(saved, "REWE", 12.34)
    assert looks_like_duplicate(saved, "Rewe City", 12.34)
    assert looks_like_duplicate(saved, "something Gemini misread", 12.34), "same date + total is enough"
    assert not looks_like_duplicate(saved, "REWE", 12.35), "different total: a second shop that day"
    assert looks_like_duplicate({"store": "REWE", "total": None}, "Rewe Markt", 5.0), "no saved total: compare stores"
    assert looks_like_duplicate(saved, "REWE", None), "no new total: compare stores"
    assert not looks_like_duplicate({"store": "Aldi", "total": None}, "Lidl", None)


@pytest.mark.parametrize("raw, expected", [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("EUR 2,50", 2.5), ("−1,50", -1.5), ("-0,30", -0.3),
    ("5,49 A", 5.49), ("", None), ("abc", None), (None, None), (True, None),
])
def test_parse_money_formats(raw, expected):
    from grocery.utils import parse_money
    assert parse_money(raw) == expected


def test_today_uses_family_time_zone():
    from zoneinfo import ZoneInfo

    from grocery.config import TIMEZONE
    from grocery.utils import today
    assert today() == datetime.datetime.now(ZoneInfo(TIMEZONE)).date()



@pytest.mark.parametrize("raw, expected", [
    ("REWE Markt GmbH", "REWE"), ("Rewe City", "REWE"), ("Lidl Dienstleistung GmbH & Co. KG", "Lidl"),
    ("ALDI SÜD", "Aldi"), ("EDEKA Center Müller", "Edeka"), ("E center", "Edeka"),
    ("Kaufland Warenhandel GmbH", "Kaufland"), ("Netto Marken-Discount", "Netto"), ("PENNY Markt GmbH", "Penny"),
    ("dm-drogerie markt GmbH + Co. KG", "dm"), ("Dirk Rossmann GmbH", "Rossmann"), ("Rossman", "Rossmann"),
    ("Müller Ltd. & Co. KG", "Müller"), ("Mueller", "Müller"), ("denns BioMarkt", "denn's Biomarkt"),
    ("Kaufiand", "Kaufland"), ("Rossmamn", "Rossmann"),  # one misread letter
    ("Bäckerei Müller", "Bäckerei Müller"), ("Hitzler Bäckerei", "Hitzler Bäckerei"), ("Normal GmbH", "Normal"),
    ("Asia Markt  Nguyen ", "Asia Markt Nguyen"), ("", ""), (None, ""),
])
def test_canonical_store(raw, expected):
    from grocery.utils import canonical_store
    assert canonical_store(raw) == expected


def test_same_chain_counts_as_same_store():
    assert same_store("Lidl Dienstleistung GmbH", "LIDL") and same_store("E center", "Edeka")
    assert not same_store("Aldi", "Lidl")
