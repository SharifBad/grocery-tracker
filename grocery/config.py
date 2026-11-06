"""App-wide constants. No Streamlit imports here so scripts can use it too."""

CATEGORIES = ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"]

GEMINI_MODEL = "gemini-3.8-flash"
MAX_ATTEMPTS = 5      # Gemini calls, retried only on 429/503/overloaded
RETRY_DELAY_S = 5

RECEIPT_BUCKET = "receipts"   # Supabase Storage bucket (see supabase/schema.sql)
UPLOAD_TYPES = ["jpg", "jpeg", "png", "pdf"]

DEFAULT_APP_URL = "https://cbecbczmjofch87t5gmwuf.streamlit.app/"
