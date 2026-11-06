"""Pure helpers (no Streamlit) for money, categories, month/week labels and duplicate matching."""
import datetime
import difflib
import re
from zoneinfo import ZoneInfo

from grocery.config import CATEGORIES, CATEGORY_ALIASES, STORES, TIMEZONE

_CATEGORY_LOOKUP = {**CATEGORY_ALIASES, **{c.lower(): c for c in CATEGORIES}}


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
    """Map a category (any case, an alias, or an earlier name like 'Dairy') onto CATEGORIES; else 'Other'."""
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


_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_LEGAL = {"gmbh", "mbh", "ag", "kg", "ohg", "co", "ek", "e k", "ug", "se", "kgaa"}


def _plain(text):
    """'dm-drogerie markt GmbH' -> 'dm drogerie markt': lower case, no umlauts/punctuation/legal suffixes."""
    words = re.findall(r"[0-9a-z]+", str(text or "").casefold().translate(_UMLAUTS))
    return " ".join(w for w in words if w not in _LEGAL)


_STORE_PHRASES = [(_plain(p), name) for name, (phrases, _) in STORES.items() for p in phrases]
_STORE_PHRASES.sort(key=lambda pair: -len(pair[0]))  # longest phrase wins
_STORE_EXACT = {_plain(w): name for name, (_, exact) in STORES.items() for w in exact}
_STORE_WORDS = {p: name for p, name in _STORE_PHRASES if " " not in p and len(p) >= 6}


def canonical_store(name):
    """The chain's standard name if `name` is one of config.STORES, else the name as given (tidied).

    'REWE Markt GmbH', 'Rewe City' -> 'REWE'; 'Lidl Dienstleistung GmbH & Co. KG' -> 'Lidl';
    'Kaufiand' (misread) -> 'Kaufland'; 'Bäckerei Schmidt' -> 'Bäckerei Schmidt'.
    """
    raw = " ".join(str(name or "").split())
    plain = _plain(raw)
    if not plain:
        return raw
    if plain in _STORE_EXACT:
        return _STORE_EXACT[plain]
    padded = f" {plain} "
    for phrase, store in _STORE_PHRASES:
        if f" {phrase} " in padded:
            return store
    for word in plain.split():  # one misread letter, e.g. 'Kaufiand', 'Rossmamn' (not 'Normal' -> Norma)
        for chain_word, store in _STORE_WORDS.items():
            if len(word) == len(chain_word) >= 6 and sum(a != b for a, b in zip(word, chain_word)) == 1:
                return store
    return raw


# Words that don't identify a shop ("REWE Markt GmbH" and "REWE" are the same store).
_STORE_FILLER = {"gmbh", "mbh", "ag", "kg", "ohg", "co", "ek", "e", "k", "markt", "supermarkt", "filiale", "und", "the"}


def store_key(name):
    words = re.findall(r"[0-9a-zäöüß]+", str(name or "").casefold())
    return " ".join(w for w in words if w not in _STORE_FILLER)


def same_store(a, b):
    """Loose store-name match: same chain, same first significant word, or very similar names."""
    if canonical_store(a) and canonical_store(a) == canonical_store(b):
        return True
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
