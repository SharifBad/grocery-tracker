"""Pure helpers (no Streamlit) for money, categories and month/week labels."""
import datetime

from grocery.config import CATEGORIES

_CATEGORY_LOOKUP = {c.lower(): c for c in CATEGORIES}


def to_money(value):
    """Parse '€1,99', '$2.50', 3, None, ... into a 2-decimal float (0.0 if unparseable)."""
    s = str(value).replace("€", "").replace("$", "").replace(",", ".").strip()
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def normalize_category(value):
    """Map any category string onto CATEGORIES (case-insensitive), defaulting to 'Other'."""
    return _CATEGORY_LOOKUP.get(str(value or "").strip().lower(), "Other")


def month_label(d):
    return f"{d:%Y-%m}"


def week_label(d):
    """ISO week, labelled with the ISO year so late-Dec/early-Jan dates land in the right week."""
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def shift_month(label, n):
    year, month = map(int, label.split("-"))
    idx = year * 12 + (month - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_bounds(label):
    """'2026-11' -> (date(2026, 11, 1), date(2026, 12, 1)), end exclusive."""
    start = datetime.date.fromisoformat(f"{label}-01")
    return start, datetime.date.fromisoformat(f"{shift_month(label, 1)}-01")


def pretty_month(label):
    return datetime.datetime.strptime(label, "%Y-%m").strftime("%B %Y")
