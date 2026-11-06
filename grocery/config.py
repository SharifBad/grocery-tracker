"""App-wide constants. No Streamlit imports here so scripts can use it too."""

CATEGORIES = ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"]

GEMINI_MODEL = "gemini-3.8-flash"
# Token-saving settings, measured in grocery/extract.py's docstring and CLAUDE.md.
GEMINI_THINKING_LEVEL = "LOW"               # MINIMAL isn't supported by gemini-3.8-flash
GEMINI_MEDIA_RESOLUTION = "LOW"             # first read
GEMINI_MEDIA_RESOLUTION_RECHECK = "MEDIUM"  # second read, only if items don't add up to the total
MAX_ATTEMPTS = 5      # Gemini calls, retried only on 429/503/overloaded
RETRY_DELAY_S = 5

UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp", "pdf"]

DEFAULT_APP_URL = "https://cbecbczmjofch87t5gmwuf.streamlit.app/"
