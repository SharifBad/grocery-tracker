"""All Supabase access: receipts/items tables and the item_lines view."""
import csv
import io

import pandas as pd
import streamlit as st
from supabase import create_client

from grocery.utils import looks_like_duplicate, normalize_category

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
    df["category"] = df["category"].map(normalize_category)  # receipts saved with earlier category names
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
    """Saved receipts from the same date that look like this one (see utils.looks_like_duplicate)."""
    same_day = (
        client().table("receipts").select("id, store, total, uploaded_by, created_at")
        .eq("purchased_on", purchased_on.isoformat()).execute().data
    )
    return [r for r in same_day if looks_like_duplicate(r, store, total)]


def _csv_text(value):
    """Text cells starting with = + - @ would run as formulas in Excel; prefix them with '."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


EXPORT_COLUMNS = ["receipt_id", "date", "store", "receipt_total", "added_by", "added_at",
                  "edited_by", "edited_at", "item", "category", "price"]


def export_csv():
    """Every receipt and item as CSV bytes (one row per item), for backups. Always fresh, not cached."""
    receipts = _fetch_all(
        lambda: client().table("receipts").select("*, items(name, category, price)")
        .order("purchased_on").order("created_at").order("id")
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for r in receipts:
        receipt = [r["id"], r["purchased_on"], _csv_text(r["store"]), "" if r["total"] is None else r["total"],
                   _csv_text(r["uploaded_by"]), r["created_at"], _csv_text(r.get("updated_by")), r.get("updated_at") or ""]
        for item in r["items"] or [{"name": "", "category": "", "price": ""}]:
            writer.writerow(receipt + [_csv_text(item["name"]), _csv_text(item["category"]), item["price"]])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows umlauts correctly


# --- Writes ---
def save_receipt(receipt, items, user, receipt_id=None):
    """Create (receipt_id None) or update a receipt and replace its items atomically. Returns its id.

    receipt: {purchased_on: date, store: str, total: float | None}
    items:   [{name, category, price}]
    """
    payload = {
        "p_receipt": {**receipt, "purchased_on": receipt["purchased_on"].isoformat()},
        "p_items": items,
        "p_user": user,
        "p_id": receipt_id,
    }
    try:
        return client().rpc("save_receipt", payload).execute().data
    finally:
        _invalidate()  # even on error: the save may have gone through with the reply lost


def delete_receipt(receipt_id):
    try:
        client().table("receipts").delete().eq("id", receipt_id).execute()  # items cascade
    finally:
        _invalidate()
