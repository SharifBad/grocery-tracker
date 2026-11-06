"""Streamlit widgets shared between pages."""
import base64
import io
import logging
from contextlib import contextmanager

import pandas as pd
import streamlit as st

from grocery.config import AVATARS, CATEGORIES
from grocery.utils import month_label, normalize_category, pretty_month, today

log = logging.getLogger(__name__)

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


@contextmanager
def database_errors(action):
    """Show a friendly message instead of a traceback if the database can't be reached, then stop."""
    try:
        yield
    except Exception:  # st.stop / st.rerun are BaseException, so they pass through
        log.exception("Database error while trying to %s", action)
        st.error(f"Couldn't {action}. The database may be waking up or unreachable. Wait a moment and reload the page.")
        st.stop()


def avatar(name):
    """Path of a family member's profile photo, or None (then show 👤)."""
    path = AVATARS / f"{str(name or '').strip().casefold()}.png"
    return str(path) if path.is_file() else None


@st.cache_data(show_spinner=False)
def avatar_data_uri(name, size=48):
    """Small inline copy of the profile photo for table image columns (None if there is none)."""
    from PIL import Image

    path = avatar(name)
    if not path:
        return None
    buf = io.BytesIO()
    Image.open(path).resize((size, size), Image.Resampling.LANCZOS).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def month_picker(item_lines, key):
    """Selectbox of months that have data (plus the current month), newest first."""
    months = set(item_lines["purchased_on"].map(month_label)) if not item_lines.empty else set()
    months.add(month_label(today()))
    return st.selectbox("Month", sorted(months, reverse=True), format_func=pretty_month, key=key)


def items_frame(records):
    df = pd.DataFrame(records, columns=ITEM_FIELDS)
    return df.astype({"name": "object", "category": "object", "price": "float64"})


def receipt_editor(key, values):
    """Editable receipt header + items table. Returns the cleaned values.

    `values` ({purchased_on, store, total, items}) is updated in place with every edit. Keep it in
    session state (like the upload draft) and edits survive the form going off screen, e.g. a
    visit to another page: Streamlit drops widget state then, and the form restarts from `values`.
    Widget keys are derived from `key`; pass a new key to reset the form to new data.
    """
    c1, c2, c3 = st.columns(3)
    # These widgets keep their identity by key, so passing the latest values here never resets them.
    purchased_on = c1.date_input("Date", values["purchased_on"], key=f"{key}_date", format="YYYY-MM-DD")
    store = c2.text_input("Store", values["store"], key=f"{key}_store")
    # No minimum: refund receipts can have a negative total.
    total = c3.number_input("Receipt total (€)", value=values["total"], step=0.01, format="%.2f", key=f"{key}_total")

    # The data editor resets whenever its input data changes, so its input stays fixed while it is
    # on screen and is refreshed from `values` only when the editor is created anew.
    items_key, base_key = f"{key}_items", f"{key}_items_base"
    if items_key not in st.session_state or base_key not in st.session_state:
        st.session_state[base_key] = list(values["items"])
    edited = st.data_editor(
        items_frame(st.session_state[base_key]),
        key=items_key,
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

    values.update(purchased_on=purchased_on, store=store, total=total, items=clean)
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
