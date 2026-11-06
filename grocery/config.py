"""App-wide constants. No Streamlit imports here so scripts can use it too."""
from pathlib import Path

# Cartoon of the family (sign-in page and header). The browser-tab icon is a round crop of
# cartoon Bibi, because a single face stays readable at 16-32 px.
LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
FAVICON = Path(__file__).resolve().parents[1] / "assets" / "favicon.png"
# Profile photos: assets/avatars/<name in lower case>.png (e.g. shiqing.png). Missing = 👤.
AVATARS = Path(__file__).resolve().parents[1] / "assets" / "avatars"

CATEGORIES = ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"]

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
