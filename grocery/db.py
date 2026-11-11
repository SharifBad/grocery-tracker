"""All Supabase access: receipts/items tables and the item_lines view."""
import csv
import io

import pandas as pd
import streamlit as st
from supabase import create_client

from grocery.utils import looks_like_duplicate, normalize_category

PAGE_SIZE = 1000  # PostgREST's default max rows per request
ITEM_COLUMNS = ["item_id", "receipt_id", "purchased_on", "store", "uploaded_by", "name", "category", "price",
                "quantity", "paid_by", "personal"]


@st.cache_resource(ttl=600)
def _has_column(table, column):
    """Does the database have this column yet? (Columns added later need supabase/schema.sql re-run.)

    Checked at most every 10 minutes, so the app works before the schema is updated (quantity 1,
    the uploader paid) and picks the column up soon after.
    """
    try:
        client().table(table).select(column).limit(1).execute()
        return True
    except Exception:
        return False


def _has_quantity():
    return _has_column("items", "quantity")


def _has_paid_by():
    return _has_column("receipts", "paid_by")


def _has_personal():
    return _has_column("receipts", "personal")


def _item_fields(*fields):
    return ", ".join([*fields, "quantity"] if _has_quantity() else fields)


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
    load_category_memory.clear()


# --- Reads (cached; every write calls _invalidate) ---
@st.cache_data(ttl=60, show_spinner=False)
def load_item_lines():
    """Every item with its receipt's date/store/uploader/payer, as a DataFrame."""
    missing = {"quantity": not _has_quantity(), "paid_by": not _has_paid_by(), "personal": not _has_personal()}
    columns = [c for c in ITEM_COLUMNS if not missing.get(c)]
    rows = _fetch_all(
        lambda: client().table("item_lines").select(",".join(columns)).order("purchased_on").order("item_id")
    )
    df = pd.DataFrame(rows, columns=ITEM_COLUMNS)
    df["purchased_on"] = pd.to_datetime(df["purchased_on"]).dt.date
    df["price"] = pd.to_numeric(df["price"]).fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"]).fillna(1.0)
    df["paid_by"] = df["paid_by"].fillna(df["uploaded_by"])
    df["personal"] = df["personal"].fillna(False).astype(bool)
    df["category"] = df["category"].map(normalize_category)  # receipts saved with earlier category names
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_receipts(start, end):
    """Receipts with start <= purchased_on < end, newest first, each with its 'items' list."""
    return _fetch_all(
        lambda: client()
        .table("receipts")
        .select(f"*, items({_item_fields('id', 'name', 'category', 'price')})")
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


EXPORT_COLUMNS = ["receipt_id", "date", "store", "receipt_total", "paid_by", "just_for_payer", "added_by", "added_at",
                  "edited_by", "edited_at", "item", "category", "price", "quantity"]


def export_csv():
    """Every receipt and item as CSV bytes (one row per item), for backups. Always fresh, not cached."""
    receipts = _fetch_all(
        lambda: client().table("receipts").select(f"*, items({_item_fields('name', 'category', 'price')})")
        .order("purchased_on").order("created_at").order("id")
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for r in receipts:
        receipt = [r["id"], r["purchased_on"], _csv_text(r["store"]), "" if r["total"] is None else r["total"],
                   _csv_text(paid_by(r)), "yes" if is_personal(r) else "", _csv_text(r["uploaded_by"]), r["created_at"], _csv_text(r.get("updated_by")), r.get("updated_at") or ""]
        for item in r["items"] or [{"name": "", "category": "", "price": "", "quantity": ""}]:
            writer.writerow(receipt + [_csv_text(item["name"]), _csv_text(item["category"]), item["price"],
                                       item.get("quantity", 1)])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows umlauts correctly


def paid_by(receipt):
    """Who paid for a receipt from load_receipts: the uploader unless someone logged it for another."""
    return receipt.get("paid_by") or receipt["uploaded_by"]


def is_personal(receipt):
    """Was it bought just for the person who paid (not for the family)? False before schema.sql is re-run."""
    return bool(receipt.get("personal"))


# --- Writes ---
def save_receipt(receipt, items, user, receipt_id=None):
    """Create (receipt_id None) or update a receipt and replace its items atomically. Returns its id.

    receipt: {purchased_on: date, store: str, total: float | None, paid_by: str | None (default: user),
              personal: bool (just for the payer; default False)}
    items:   [{name, category, price, quantity}]
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


# --- Remembered category corrections (table category_memory) ---
@st.cache_data(ttl=60, show_spinner=False)
def load_category_memory():
    """{item_key: category} for items someone re-categorised before."""
    rows = _fetch_all(lambda: client().table("category_memory").select("name_key, category").order("name_key"))
    return {r["name_key"]: r["category"] for r in rows}


def remember_categories(corrections, user):
    """Store {item_key: category} so those items get that category automatically next time."""
    if not corrections:
        return
    rows = [{"name_key": k, "category": c, "updated_by": user} for k, c in corrections.items() if k]
    try:
        client().table("category_memory").upsert(rows, on_conflict="name_key").execute()
    finally:
        load_category_memory.clear()


# --- Monthly budgets (table budgets; 'TOTAL' is the overall budget) ---
@st.cache_data(ttl=60, show_spinner=False)
def load_budgets():
    rows = client().table("budgets").select("category, amount").execute().data
    return {r["category"]: float(r["amount"]) for r in rows if float(r["amount"]) > 0}


def save_budgets(amounts, user):
    """{category or 'TOTAL': amount}; 0 or empty removes that budget."""
    keep = [{"category": c, "amount": round(float(a), 2), "updated_by": user} for c, a in amounts.items() if a and a > 0]
    drop = [c for c, a in amounts.items() if not a or a <= 0]
    try:
        if keep:
            client().table("budgets").upsert(keep, on_conflict="category").execute()
        if drop:
            client().table("budgets").delete().in_("category", drop).execute()
    finally:
        load_budgets.clear()
