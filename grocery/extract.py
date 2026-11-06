"""Receipt -> structured data via Gemini, using a response schema so categories come back valid."""
import datetime
import time
from typing import Literal

import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from grocery.config import CATEGORIES, GEMINI_MODEL, MAX_ATTEMPTS, RETRY_DELAY_S
from grocery.utils import normalize_category

PROMPT = f"""
Read this grocery receipt and extract it.

- date: purchase date as YYYY-MM-DD, or null if not printed.
- store: the shop name.
- total: the final amount paid.
- items: one entry per purchased line.
  - name: readable product name in the receipt's language; expand obvious abbreviations.
  - price: final price paid for that line (quantity x unit price, after any line discount).
    If a discount can't be tied to an item, add it as its own item named "Discount" with a
    negative price and category Other.
  - category, one of {", ".join(CATEGORIES)}:
    Produce = fruit, vegetables, fresh herbs; Dairy = milk, cheese, yogurt, butter, eggs;
    Meat = meat, poultry, fish, seafood; Bakery = bread, rolls, pastries, cakes;
    Pantry = dry and canned goods, pasta, rice, spices, oils, snacks, sweets, drinks, frozen food;
    Household = cleaning products, toiletries, paper goods, other non-food;
    Other = bottle deposits, bags, anything else.
Skip subtotal, tax, payment, card and change lines.
"""


class ExtractedItem(BaseModel):
    name: str
    category: Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
    price: float


class ExtractedReceipt(BaseModel):
    date: str | None = Field(None, description="YYYY-MM-DD")
    store: str | None = None
    total: float | None = None
    items: list[ExtractedItem]


class ExtractionError(Exception):
    pass


@st.cache_resource
def _client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def _retryable(err):
    text = str(err)
    return getattr(err, "code", None) in (429, 503) or any(
        marker in text for marker in ("503", "429", "UNAVAILABLE")
    ) or "overloaded" in text.lower()


def _call_gemini(data, mime, on_retry):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Part.from_bytes(data=data, mime_type=mime), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractedReceipt,
                ),
            )
        except Exception as e:
            if not _retryable(e):
                raise ExtractionError(f"Gemini error: {e}") from e
            if attempt == MAX_ATTEMPTS:
                raise ExtractionError(f"Gemini is still busy after {MAX_ATTEMPTS} attempts. Try again in a minute.") from e
            if on_retry:
                on_retry(attempt, RETRY_DELAY_S)
            time.sleep(RETRY_DELAY_S)


def extract_receipt(data, mime, on_retry=None):
    """Return {date, date_guessed, store, total, items: [{name, category, price}]}.

    on_retry(attempt, wait_seconds) is called before each retry so the UI can show progress.
    Raises ExtractionError with a user-facing message.
    """
    response = _call_gemini(data, mime, on_retry)
    parsed = response.parsed
    if not isinstance(parsed, ExtractedReceipt):
        try:
            parsed = ExtractedReceipt.model_validate_json(response.text or "")
        except ValueError as e:
            raise ExtractionError("Gemini's answer couldn't be understood. Try again or enter it manually.") from e

    try:
        purchased_on, guessed = datetime.date.fromisoformat(parsed.date or ""), False
    except ValueError:
        purchased_on, guessed = datetime.date.today(), True

    return {
        "date": purchased_on,
        "date_guessed": guessed,
        "store": (parsed.store or "").strip(),
        "total": round(parsed.total, 2) if parsed.total is not None else None,
        "items": [
            {"name": i.name.strip(), "category": normalize_category(i.category), "price": round(i.price, 2)}
            for i in parsed.items
        ],
    }
