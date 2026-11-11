"""App-wide constants. No Streamlit imports here so scripts can use it too."""
from pathlib import Path

# Cartoon of the family (sign-in page and header). The browser-tab icon is a round crop of
# cartoon Bibi, because a single face stays readable at 16-32 px.
LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
FAVICON = Path(__file__).resolve().parents[1] / "assets" / "favicon.png"
# Profile photos: assets/avatars/<name in lower case>.png (e.g. shiqing.png). Missing = 👤.
AVATARS = Path(__file__).resolve().parents[1] / "assets" / "avatars"

CATEGORIES = [
    "Fruit", "Vegetables", "Meat & Fish", "Dairy & Eggs", "Bakery", "Pantry", "Snacks & Sweets", "Drinks",
    "Frozen", "Cleaning & Household", "Skin & Body Care", "Health", "Pet", "Clothes & Shoes", "Other",
]
# Other spellings (and the app's earlier category names) mapped onto CATEGORIES by
# utils.normalize_category. "Produce" can't be split, so it goes to Vegetables.
CATEGORY_ALIASES = {
    "produce": "Vegetables", "dairy": "Dairy & Eggs", "meat": "Meat & Fish", "household": "Cleaning & Household",
    "fruits": "Fruit", "veggie": "Vegetables", "veggies": "Vegetables", "vegetable": "Vegetables",
    "fish": "Meat & Fish", "eggs": "Dairy & Eggs", "snacks": "Snacks & Sweets", "sweets": "Snacks & Sweets",
    "drink": "Drinks", "beverages": "Drinks", "cleaning": "Cleaning & Household",
    "skin care": "Skin & Body Care", "skincare": "Skin & Body Care", "personal care": "Skin & Body Care",
    "toiletries": "Skin & Body Care", "hygiene": "Skin & Body Care", "cosmetics": "Skin & Body Care",
    "medicine": "Health", "pharmacy": "Health", "pets": "Pet", "clothes": "Clothes & Shoes",
    "shoes": "Clothes & Shoes", "clothing": "Clothes & Shoes",
}

# Common German chains. Store names from receipts or typed in the form are mapped onto these
# names (see utils.canonical_store), so spending per store adds up correctly. Anything that
# matches none of them is kept as printed on the Kassenbon.
#   name: (phrases that identify it anywhere in the store name,
#          words that only count when they are the whole name)
# Matching ignores case, umlauts (ü = ue), punctuation and legal suffixes like GmbH.
STORES = {
    "REWE": (["rewe"], []),
    "Lidl": (["lidl"], []),
    "Aldi": (["aldi"], []),
    "Edeka": (["edeka", "e center", "ecenter", "e aktiv markt"], []),
    "Kaufland": (["kaufland"], []),
    "Netto": (["netto"], []),
    "Penny": (["penny"], []),
    "Norma": (["norma"], []),
    "Globus": (["globus"], []),
    "Marktkauf": (["marktkauf"], []),
    "HIT": (["hit markt", "hit ullrich"], ["hit"]),
    "tegut": (["tegut"], []),
    "Famila": (["famila"], []),
    "nahkauf": (["nahkauf"], []),
    "Alnatura": (["alnatura"], []),
    "denn's Biomarkt": (["denns", "denn s biomarkt"], []),
    "Bio Company": (["bio company", "biocompany"], []),
    "Rossmann": (["rossmann", "rossman"], []),
    "dm": (["dm drogerie"], ["dm"]),
    "Müller": (["mueller drogerie", "drogerie mueller", "mueller ltd", "mueller handels"], ["mueller"]),
    "Metro": (["metro cash", "metro markt"], ["metro"]),
    "Picnic": (["picnic"], []),
    "Flink": (["flink"], []),
    "Go Asia": (["go asia", "goasia"], []),
    "Normal": ([], ["normal"]),
}

GEMINI_MODEL = "gemini-3.8-flash"
# Token-saving settings, measured in grocery/extract.py's docstring and CLAUDE.md.
GEMINI_THINKING_LEVEL = "LOW"               # MINIMAL isn't supported by gemini-3.8-flash
GEMINI_MEDIA_RESOLUTION = "LOW"             # first read
GEMINI_MEDIA_RESOLUTION_RECHECK = "MEDIUM"  # second read, only if items don't add up to the total
MAX_ATTEMPTS = 5      # Gemini calls, retried only on rate-limit/server/network errors
RETRY_DELAY_S = 5

UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp", "pdf"]

DEFAULT_APP_URL = "https://cbecbczmjofch87t5gmwuf.streamlit.app/"

# The family's time zone. Streamlit Cloud servers run on UTC, so "today" (default receipt date,
# current month) must come from here, not from the server clock. See utils.today().
TIMEZONE = "Europe/Berlin"

# uploaded_by (and so paid_by) of receipts imported from the old Google Sheet by scripts/import_sheet.py
IMPORT_USER = "sheet-import"
IMPORTED_LABEL = "📄 Imported"
