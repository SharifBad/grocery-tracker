"""App-wide constants. No Streamlit imports here so scripts can use it too."""
from pathlib import Path

# Cartoon of the family (sign-in page and header). The browser-tab icon is a round crop of
# cartoon Bibi, because a single face stays readable at 16-32 px.
LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
FAVICON = Path(__file__).resolve().parents[1] / "assets" / "favicon.png"
# Profile photos: assets/avatars/<name in lower case>.png (e.g. shiqing.png). Missing = 👤.
AVATARS = Path(__file__).resolve().parents[1] / "assets" / "avatars"

CATEGORIES = ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"]

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
