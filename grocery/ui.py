"""Streamlit widgets shared between pages."""
import datetime

import pandas as pd
import streamlit as st

from grocery.config import CATEGORIES
from grocery.utils import month_label, normalize_category, pretty_month

ITEM_FIELDS = ["name", "category", "price"]


def euro(x, signed=False):
    sign = ("+" if x >= 0 else "-") if signed else ("-" if x < 0 else "")
    return f"{sign}€{abs(x):,.2f}"


def flash(message=None):
    """Store a success message to show after st.rerun(), or show (and clear) a stored one."""
    if message:
        st.session_state["_flash"] = message
    elif msg := st.session_state.pop("_flash", None):
        st.success(msg)


def month_picker(item_lines, key):
    """Selectbox of months that have data (plus the current month), newest first."""
    months = set(item_lines["purchased_on"].map(month_label)) if not item_lines.empty else set()
    months.add(month_label(datetime.date.today()))
    return st.selectbox("Month", sorted(months, reverse=True), format_func=pretty_month, key=key)


def items_frame(records):
    df = pd.DataFrame(records, columns=ITEM_FIELDS)
    return df.astype({"name": "object", "category": "object", "price": "float64"})


def receipt_editor(key, *, purchased_on, store, total, items):
    """Editable receipt header + items table. Returns the cleaned values.

    Widget keys are derived from `key`; pass a new key to reset the editor to new data.
    """
    c1, c2, c3 = st.columns(3)
    purchased_on = c1.date_input("Date", purchased_on, key=f"{key}_date", format="YYYY-MM-DD")
    store = c2.text_input("Store", store, key=f"{key}_store")
    total = c3.number_input(
        "Receipt total (€)", value=total, min_value=0.0, step=0.01, format="%.2f", key=f"{key}_total"
    )

    edited = st.data_editor(
        items_frame(items),
        key=f"{key}_items",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Item", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True, default="Other"),
            "price": st.column_config.NumberColumn("Price (€)", format="€%.2f", step=0.01, required=True),
        },
    )

    clean = []
    for row in edited.to_dict("records"):
        name = "" if pd.isna(row["name"]) else str(row["name"]).strip()
        if not name:
            continue
        price = 0.0 if pd.isna(row["price"]) else round(float(row["price"]), 2)
        clean.append({"name": name, "category": normalize_category(row["category"]), "price": price})

    items_sum = round(sum(i["price"] for i in clean), 2)
    st.caption(f"{len(clean)} items · add up to {euro(items_sum)}")
    if total is not None and abs(items_sum - total) > 0.05:
        st.warning(
            f"Items add up to **{euro(items_sum)}** but the receipt total is **{euro(total)}**. "
            "Check for missing items or discounts."
        )

    return {
        "purchased_on": purchased_on,
        "store": store.strip(),
        "total": None if total is None else round(total, 2),
        "items": clean,
    }


def show_receipt_file(data, mime, filename):
    """Preview the just-uploaded receipt while reviewing it. The file itself is never stored."""
    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        st.caption("No preview for PDFs.")
        return
    try:
        st.image(data)
    except Exception:
        st.caption("Couldn't preview this file.")
