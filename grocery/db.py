"""All Supabase access: receipts/items tables, the item_lines view, and receipt image storage."""
import datetime
import uuid

import pandas as pd
import streamlit as st
from supabase import create_client

from grocery.config import RECEIPT_BUCKET

PAGE_SIZE = 1000  # PostgREST's default max rows per request
ITEM_COLUMNS = ["item_id", "receipt_id", "purchased_on", "store", "uploaded_by", "name", "category", "price"]


@st.cache_resource
def client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


def _fetch_all(make_query):
    """Page through a query (built fresh by make_query each time) until all rows are read."""
    rows, start = [], 0
    while True:
        batch = make_query().range(start, start + PAGE_SIZE - 1).execute().data
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _invalidate():
    load_item_lines.clear()
    load_receipts.clear()
    find_duplicates.clear()


# --- Reads (cached; every write calls _invalidate) ---
@st.cache_data(ttl=60, show_spinner=False)
def load_item_lines():
    """Every item with its receipt's date/store/uploader, as a DataFrame."""
    rows = _fetch_all(
        lambda: client().table("item_lines").select(",".join(ITEM_COLUMNS)).order("purchased_on").order("item_id")
    )
    df = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    df["purchased_on"] = pd.to_datetime(df["purchased_on"]).dt.date
    df["price"] = pd.to_numeric(df["price"]).fillna(0.0)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_receipts(start, end):
    """Receipts with start <= purchased_on < end, newest first, each with its 'items' list."""
    return _fetch_all(
        lambda: client()
        .table("receipts")
        .select("*, items(id, name, category, price)")
        .gte("purchased_on", start.isoformat())
        .lt("purchased_on", end.isoformat())
        .order("purchased_on", desc=True)
        .order("created_at", desc=True)
    )


@st.cache_data(ttl=60, show_spinner=False)
def find_duplicates(purchased_on, store, total):
    """Receipts that look like the same shopping trip (same date, store and total)."""
    query = client().table("receipts").select("id, uploaded_by, created_at").eq("purchased_on", purchased_on.isoformat())
    query = query.eq("store", store)
    query = query.is_("total", "null") if total is None else query.eq("total", total)
    return query.execute().data


# --- Writes ---
def save_receipt(receipt, items, user, receipt_id=None):
    """Create (receipt_id None) or update a receipt and replace its items atomically. Returns its id.

    receipt: {purchased_on: date, store: str, total: float | None, image_path: str | None}
    items:   [{name, category, price}]
    """
    payload = {
        "p_receipt": {**receipt, "purchased_on": receipt["purchased_on"].isoformat()},
        "p_items": items,
        "p_user": user,
        "p_id": receipt_id,
    }
    rid = client().rpc("save_receipt", payload).execute().data
    _invalidate()
    return rid


def delete_receipt(receipt_id, image_path=None):
    client().table("receipts").delete().eq("id", receipt_id).execute()  # items cascade
    if image_path:
        remove_image(image_path)
    _invalidate()


# --- Receipt images ---
def upload_image(data, mime, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    path = f"{datetime.date.today():%Y/%m}/{uuid.uuid4()}.{ext}"
    client().storage.from_(RECEIPT_BUCKET).upload(path, data, {"content-type": mime})
    return path


def remove_image(path):
    try:
        client().storage.from_(RECEIPT_BUCKET).remove([path])
    except Exception:
        pass  # an orphaned image is harmless; don't fail the user's action over it


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def get_image(path):
    return client().storage.from_(RECEIPT_BUCKET).download(path)
