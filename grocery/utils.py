"""Pure helpers (no Streamlit) for money, categories, month/week labels and duplicate matching."""
import datetime
import difflib
import re
from zoneinfo import ZoneInfo

from grocery.config import CATEGORIES, TIMEZONE

_CATEGORY_LOOKUP = {c.lower(): c for c in CATEGORIES}


def today():
    """Today's date in the family's time zone (the server runs on UTC)."""
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).date()


def parse_money(value):
    """Parse money text into a 2-decimal float, or None if it isn't a number.

    Handles '€1,99', '1.234,56' (German), '1,234.56', 'EUR 2,50', '-1,50' and '−1,50' (Unicode minus).
    With both separators present, the last one is the decimal point.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = re.sub(r"[^0-9,.\-]", "", str(value).replace("\u2212", "-"))
    if "," in s and "." in s:
        thousands = "." if s.rfind(",") > s.rfind(".") else ","
        s = s.replace(thousands, "")
    s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def to_money(value):
    """Like parse_money, but 0.0 when the value isn't a number."""
    parsed = parse_money(value)
    return 0.0 if parsed is None else parsed


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


# Words that don't identify a shop ("REWE Markt GmbH" and "REWE" are the same store).
_STORE_FILLER = {"gmbh", "mbh", "ag", "kg", "ohg", "co", "ek", "e", "k", "markt", "supermarkt", "filiale", "und", "the"}


def store_key(name):
    words = re.findall(r"[0-9a-zäöüß]+", str(name or "").casefold())
    return " ".join(w for w in words if w not in _STORE_FILLER)


def same_store(a, b):
    """Loose store-name match: same first significant word, or very similar names."""
    ka, kb = store_key(a), store_key(b)
    if not ka or not kb:
        return False
    return ka.split()[0] == kb.split()[0] or difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.8


def looks_like_duplicate(existing, store, total):
    """Is `existing` (a saved receipt from the same date) probably the receipt being added?

    Same date and same total is enough, however Gemini spelled the store. Without a total on
    either side, fall back to a loose store-name match.
    """
    if total is not None and existing.get("total") is not None:
        return abs(float(existing["total"]) - float(total)) < 0.005
    return same_store(existing.get("store"), store)
