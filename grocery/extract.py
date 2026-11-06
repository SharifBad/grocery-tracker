"""Receipt -> structured data via Gemini, tuned for low token use.

Token budget (measured 2026-11-06, gemini-3.8-flash, 40-item receipt; details in CLAUDE.md):
- thinking_level LOW: hidden "thinking" was the biggest cost (up to ~9,000 output tokens per
  receipt at the default level); at LOW it is ~0 and reading is 2-8x faster, same accuracy.
- media_resolution LOW: the image costs ~550 input tokens instead of ~1,350 at the default.
- compact JSON: one-letter keys (pydantic aliases) and names copied as printed.
Together: ~1,400 billed tokens instead of ~11,400 for a 40-item receipt.

LOW image detail occasionally misreads a blurry photo. The receipt checks itself: if the items
don't add up to the printed total, it is read once more at MEDIUM image detail.
"""
import datetime
import logging
import time
from typing import Literal

import httpx
import streamlit as st
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field, field_validator

from grocery.config import (
    CATEGORIES,
    GEMINI_MEDIA_RESOLUTION,
    GEMINI_MEDIA_RESOLUTION_RECHECK,
    GEMINI_MODEL,
    GEMINI_THINKING_LEVEL,
    MAX_ATTEMPTS,
    RETRY_DELAY_S,
)
from grocery.utils import canonical_store, normalize_category, today

log = logging.getLogger(__name__)

ADDS_UP_TOLERANCE = 0.05  # euros; rounding on receipts

PROMPT = """
Read this grocery receipt and extract it.
- date: YYYY-MM-DD, or null if not printed. store: the shop name. total: the amount paid.
- items: one per purchased line. name: exactly as printed. price: what was paid for the line
  (after line discounts); a discount not tied to an item is its own item "Discount", negative, Other.
- category guide: Vegetables incl. salad, potatoes, herbs. Meat & Fish incl. sausage, cold cuts.
  Bakery: bread, toast, crispbread, cakes. Pantry: pasta, rice, flour, muesli, cans, oil, spices,
  sauces, coffee, tea. Snacks & Sweets: chips, nuts, chocolate, biscuits, ice cream. Frozen: not ice
  cream. Cleaning & Household: detergent, toilet paper, bin bags. Skin & Body Care: cosmetics,
  shampoo, toothpaste. Health: medicine, plasters. Other: Pfand (Leergut returns negative), bags.
Skip subtotal, tax, payment and change lines.
JSON keys: d=date, s=store, t=total, i=items; per item n=name, c=category, p=price.
"""


# Gemini writes the short aliases (n, c, p, ...); Python code uses the full names.
class ExtractedItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="n")
    category: Literal[tuple(CATEGORIES)] = Field(alias="c")  # type: ignore[valid-type]
    price: float = Field(alias="p")

    @field_validator("category", mode="before")
    @classmethod
    def _known_category(cls, value):
        # Gemini sees the exact list; if it still answers something else, don't fail the whole read.
        return normalize_category(value)


class ExtractedReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date: str | None = Field(None, alias="d", description="YYYY-MM-DD")
    store: str | None = Field(None, alias="s")
    total: float | None = Field(None, alias="t")
    items: list[ExtractedItem] = Field(alias="i")

    def gap(self):
        """How far the items' sum is from the printed total (0 if there is no total to check)."""
        return 0.0 if self.total is None else abs(sum(i.price for i in self.items) - self.total)

    def adds_up(self):
        return self.gap() <= ADDS_UP_TOLERANCE


class ExtractionError(Exception):
    pass


@st.cache_resource
def _client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}  # rate limit, timeouts, server-side trouble


def _retryable(err):
    if isinstance(err, errors.APIError):
        return err.code in RETRYABLE_CODES
    return isinstance(err, (httpx.TransportError, TimeoutError, ConnectionError))  # network hiccups


# Added only when a long receipt comes in several photos.
MULTI_PART_NOTE = "The images are parts of ONE long receipt, top to bottom; they may overlap. List each item once.\n"
MAX_PARTS = 3


def _read(parts, media_resolution, on_progress):
    """One extraction call (with busy-retries). Returns (parsed receipt, billed tokens)."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExtractedReceipt,
        media_resolution=getattr(types.MediaResolution, f"MEDIA_RESOLUTION_{media_resolution}"),
        thinking_config=types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, GEMINI_THINKING_LEVEL)),
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Part.from_bytes(data=d, mime_type=m) for d, m in parts]
                + [PROMPT + (MULTI_PART_NOTE if len(parts) > 1 else "")],
                config=config,
            )
            break
        except Exception as e:
            if not _retryable(e):
                log.exception("Gemini call failed")
                code = f" (error {e.code})" if isinstance(e, errors.APIError) else ""
                raise ExtractionError(f"Gemini couldn't read this file{code}. Try another photo, or enter it manually.") from e
            if attempt == MAX_ATTEMPTS:
                raise ExtractionError(f"Gemini is still busy after {MAX_ATTEMPTS} attempts. Try again in a minute.") from e
            if on_progress:
                on_progress(f"⚠️ Gemini is busy, retrying in {RETRY_DELAY_S}s (attempt {attempt + 1}/{MAX_ATTEMPTS})")
            time.sleep(RETRY_DELAY_S)

    parsed = response.parsed
    if not isinstance(parsed, ExtractedReceipt):
        try:
            parsed = ExtractedReceipt.model_validate_json(response.text or "")
        except ValueError as e:
            raise ExtractionError("Gemini's answer couldn't be understood. Try again or enter it manually.") from e
    usage = getattr(response, "usage_metadata", None)
    tokens = (usage.total_token_count or 0) if usage else 0
    return parsed, tokens


def extract_receipt(data, mime=None, on_progress=None):
    """Return {date, date_guessed, store, total, items: [{name, category, price}], tokens}.

    `data` is one file's bytes (with `mime`), or a list of (bytes, mime) for a long receipt
    photographed in up to MAX_PARTS parts, read together in one call.

    on_progress(message) is called with status updates (busy retries, double-checking).
    Raises ExtractionError with a user-facing message.
    """
    parts = list(data)[:MAX_PARTS] if isinstance(data, (list, tuple)) else [(data, mime)]
    parsed, tokens = _read(parts, GEMINI_MEDIA_RESOLUTION, on_progress)
    if not parsed.adds_up():
        if on_progress:
            on_progress("🔍 The items don't add up to the total, so reading it again in more detail…")
        try:
            second, more_tokens = _read(parts, GEMINI_MEDIA_RESOLUTION_RECHECK, on_progress)
        except ExtractionError:  # the first read is still usable; the review step flags the gap
            log.warning("Detailed re-read failed; keeping the first read", exc_info=True)
        else:
            tokens += more_tokens
            if second.gap() <= parsed.gap():  # keep whichever read is closer to adding up
                parsed = second

    try:
        purchased_on, guessed = datetime.date.fromisoformat(parsed.date or ""), False
    except ValueError:
        purchased_on, guessed = today(), True

    return {
        "date": purchased_on,
        "date_guessed": guessed,
        "store": canonical_store(parsed.store),
        "total": round(parsed.total, 2) if parsed.total is not None else None,
        "items": [
            {"name": i.name.strip(), "category": normalize_category(i.category), "price": round(i.price, 2)}
            for i in parsed.items
        ],
        "tokens": tokens,
    }
