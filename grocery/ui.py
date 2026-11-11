"""Streamlit widgets shared between pages."""
import base64
import io
import logging
import re
from contextlib import contextmanager
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from grocery.config import AVATARS, CATEGORIES, STORES
from grocery.utils import (
    canonical_store,
    month_label,
    normalize_category,
    parse_money,
    parse_quantity,
    pretty_month,
    today,
)

log = logging.getLogger(__name__)

ITEM_FIELDS = ["name", "category", "price", "quantity"]  # Qty last: price stays on screen on phones


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


@st.cache_data(show_spinner=False, max_entries=20)
def _data_uri(data):
    from PIL import Image

    fmt = (Image.open(io.BytesIO(data)).format or "PNG").lower()
    return f"data:image/{fmt};base64," + base64.b64encode(data).decode()


def crisp_image(image, width, caption=None, alt=""):
    """Show an image `width` CSS px wide, sharp on phones and Retina screens.

    st.image(width=N) resizes the picture on the server to exactly N pixels, which a 2-3x
    screen then stretches and blurs. Here the full-resolution file goes to the browser,
    which scales it down itself. `image` is a file path or bytes.
    """
    data = Path(image).read_bytes() if isinstance(image, (str, Path)) else image
    html = f'<img src="{_data_uri(data)}" width="{int(width)}" alt="{escape(alt)}" style="display:block;border-radius:0.5rem">'
    if caption:
        html += f'<div style="font-size:0.875rem;opacity:0.7;margin-top:0.25rem">{escape(caption)}</div>'
    st.markdown(html, unsafe_allow_html=True)


def brand_header(logo, title, logo_px=72):
    """Logo and page title on one line, vertically centred; on narrow phones the title wraps below.

    One HTML block instead of st.container + st.title, whose built-in spacing left the logo
    lower than the title and touching the content below it.
    """
    data = Path(logo).read_bytes()
    st.markdown(
        f'''<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem 1rem;margin:0 0 1.5rem">
          <img src="{_data_uri(data)}" width="{logo_px}" height="{logo_px}" alt=""
               style="display:block;flex:none;border-radius:0.75rem;object-fit:cover">
          <h1 style="margin:0;padding:0;line-height:1.15">{escape(title)}</h1>
        </div>''',
        unsafe_allow_html=True,
    )


def avatar(name):
    """Path of a family member's profile photo, or None (then show 👤)."""
    path = AVATARS / f"{str(name or '').strip().casefold()}.png"
    return str(path) if path.is_file() else None


@st.cache_data(show_spinner=False)
def avatar_data_uri(name, size=96):  # 96 px source for a ~32 px cell: sharp at 3x
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
    df["quantity"] = df["quantity"].fillna(1.0)  # items saved before quantities existed
    return df.astype({"name": "object", "quantity": "float64", "category": "object", "price": "float64"})


def store_options(used=()):
    """The known chains first (config.STORES), then other stores already used, for the store dropdown."""
    others = sorted({canonical_store(s) for s in used if s} - set(STORES) - {"", "Unknown Store"}, key=str.casefold)
    return list(STORES) + others


def payer_picker(key, values, user, family):
    """"I paid for this" (on by default); off means another family member paid. Returns the payer.

    With two people, off simply means the other one; with more, a dropdown asks who.
    """
    paid_by = values.get("paid_by") or user
    others = [n for n in family if n.casefold() != user.casefold()]
    if paid_by != user and paid_by not in others:
        others.insert(0, paid_by)  # e.g. someone no longer in FAMILY
    if not others:
        return user
    if not st.toggle("🙋 I paid for this", value=paid_by == user, key=f"{key}_paid_me"):
        if len(others) == 1:
            paid_by = others[0]
            st.caption(f"Paid by **{paid_by}**")
        else:
            paid_by = st.selectbox("Who paid?", others, index=others.index(paid_by) if paid_by in others else 0,
                                   key=f"{key}_paid_by")
    else:
        paid_by = user
    return paid_by


def _is_phone():
    """Best guess from the browser's User-Agent; False when unknown (e.g. in tests)."""
    try:
        agent = st.context.headers.get("User-Agent") or ""
    except Exception:
        return False
    return bool(re.search(r"Mobi|Android|iPhone|iPad", agent))


def _md(text):
    """Item names as plain text inside markdown (receipts print things like *, _ and #)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~:$])", r"\\\1", str(text))


def _amount_text(price):
    return f"{price:.2f}".replace(".", ",")


def _quantity_text(quantity):
    return format(float(quantity), "g").replace(".", ",")


def _changed_items(key, items):
    """Store items edited outside the table; the table rebuilds from them next time it is shown."""
    st.session_state[f"{key}_values"]["items"] = items
    st.session_state[f"{key}_items_rev"] = st.session_state.get(f"{key}_items_rev", 0) + 1


ITEM_DIALOG = "item_dialog"  # (editor key, item index or None for a new item) while the item form is open


def _close_item():
    st.session_state.pop(ITEM_DIALOG, None)


@st.dialog("Item", on_dismiss=_close_item)
def _item_dialog(key, index):
    """One item in a phone-sized form: big fields, a normal dropdown, comma decimals.

    Whether it is open lives in session state (ITEM_DIALOG), so it survives full reruns.
    """
    values = st.session_state[f"{key}_values"]
    items = list(values["items"])
    item = items[index] if index is not None and index < len(items) else None
    k = f"{key}_dlg{st.session_state.get(f'{key}_dlg_no', 0)}"
    name = st.text_input("Item", item["name"] if item else "", key=f"{k}_name", placeholder="e.g. MILCH")
    category = normalize_category(item["category"]) if item else "Other"
    category = st.selectbox("Category", CATEGORIES, index=CATEGORIES.index(category), key=f"{k}_category")
    row = st.container(horizontal=True)
    price_text = row.text_input("Price (€)", _amount_text(item["price"]) if item else "", key=f"{k}_price",
                                placeholder="1,99", help="What the whole line cost. Minus for discounts or Leergut.")
    quantity_text = row.text_input("Qty", _quantity_text(item.get("quantity") or 1) if item else "1", key=f"{k}_qty",
                                   help="How many, or kg for weighed items (0,512).")
    price, quantity = parse_money(price_text), parse_quantity(quantity_text)
    if price_text.strip() and price is None:
        st.error("The price isn't a number. Write it like 1,99.")
    if quantity is None:
        st.error("The quantity must be a number above 0, like 2 or 0,512.")
    ready = bool(name.strip()) and price is not None and quantity is not None
    buttons = st.container(horizontal=True)
    if buttons.button("✅ Done", type="primary", disabled=not ready, key=f"{k}_done"):
        new = {"name": name.strip(), "category": category, "price": price, "quantity": quantity}
        if item is None:
            items.append(new)
        else:
            items[index] = new
        _changed_items(key, items)
        _close_item()
        st.rerun()
    if item is not None and buttons.button("🗑️ Remove", key=f"{k}_remove"):
        del items[index]
        _changed_items(key, items)
        _close_item()
        st.rerun()


def _open_item(key, index):
    st.session_state[f"{key}_dlg_no"] = st.session_state.get(f"{key}_dlg_no", 0) + 1  # fresh form fields
    st.session_state[ITEM_DIALOG] = (key, index)


def _items_list(key, items):
    """Phone-friendly view of the items: one line each, ✏️ opens a form for that item."""
    rev = st.session_state.get(f"{key}_items_rev", 0)
    for i, item in enumerate(items):
        row = st.container(horizontal=True, vertical_alignment="center", border=True, gap="small")
        detail = item["category"] + (f" · ×{_quantity_text(item['quantity'])}" if item.get("quantity", 1) != 1 else "")
        row.markdown(f"**{_md(item['name'])}**  \n:gray[{_md(detail)}]", width="stretch")
        row.markdown(f"**{euro(item['price'])}**", width="content")
        row.button("✏️", key=f"{key}_edit_{rev}_{i}", help="Edit or remove", on_click=_open_item, args=(key, i))
    st.button("➕ Add item", key=f"{key}_add_{rev}", width="stretch", on_click=_open_item, args=(key, None))
    if st.session_state.get("page_changed"):
        _close_item()  # don't pop the form up again after a visit to another page
    open_key, index = st.session_state.get(ITEM_DIALOG) or (None, None)
    if open_key == key:
        _item_dialog(key, index)


def _items_table(key, values):
    """The spreadsheet-style editor (best with a mouse). Returns the rows as dicts."""
    # The data editor resets whenever its input data changes, so its input stays fixed while it is
    # on screen and is refreshed from `values` only when the editor is created anew, or after the
    # items were changed in the list view (a new rev, so a new key).
    rev = st.session_state.get(f"{key}_items_rev", 0)
    suffix = f"_{rev}" if rev else ""
    items_key, base_key = f"{key}_items{suffix}", f"{key}_items_base{suffix}"
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
            "quantity": st.column_config.NumberColumn(
                "Qty", min_value=0.001, step=0.001, default=1, format="plain", width="small",
                help="How many (or kg for weighed items). The price is for the whole line.",
            ),
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True, default="Other"),
            "price": st.column_config.NumberColumn("Price (€)", format="€%.2f", step=0.01, required=True,
                                                   help="What the whole line cost."),
        },
    )
    return edited.to_dict("records")


def receipt_editor(key, values, stores=None, user=None, family=()):
    """Editable receipt header + items table. Returns the cleaned values.

    `values` ({purchased_on, store, total, paid_by, personal, items}) is updated in place with every edit. Keep it in
    session state (like the upload draft) and edits survive the form going off screen, e.g. a
    visit to another page: Streamlit drops widget state then, and the form restarts from `values`.
    Widget keys are derived from `key`; pass a new key to reset the form to new data.
    """
    c1, c2, c3 = st.columns(3)
    # These widgets keep their identity by key, so passing the latest values here never resets them.
    purchased_on = c1.date_input("Date", values["purchased_on"], key=f"{key}_date", format="YYYY-MM-DD")
    # Pick a chain from the list or type any other shop; typed names are matched to the list too.
    options = list(stores or store_options())
    current = canonical_store(values["store"])
    if current and current not in options:
        options.append(current)
    chosen = c2.selectbox(
        "Store", options, index=options.index(current) if current else None, key=f"{key}_store",
        accept_new_options=True, placeholder="Choose or type",
    )
    store = canonical_store(chosen)
    if chosen and store != chosen.strip():
        c2.caption(f"Saved as **{store}**")
    # No minimum: refund receipts can have a negative total.
    total = c3.number_input("Receipt total (€)", value=values["total"], step=0.01, format="%.2f", key=f"{key}_total")
    paid_by = payer_picker(key, values, user, family) if user else values.get("paid_by")
    personal = bool(values.get("personal"))
    if user:
        personal = st.toggle(
            f"🔒 Just for {'me' if paid_by == user else paid_by}", value=personal, key=f"{key}_personal",
            help="Bought for themselves, not for the family. The dashboard shows it separately for each person.",
        )

    # Items: a list with a form per item (easy on phones) or the table (quick with a mouse).
    st.session_state[f"{key}_values"] = values  # the same dict, for the item form
    default_view = "list" if _is_phone() else "table"
    view = st.segmented_control(
        "Items", ["list", "table"], default=default_view, key="items_view",
        format_func={"list": "📝 List", "table": "📊 Table"}.get,
    ) or default_view
    rows = _items_table(key, values) if view == "table" else values["items"]
    if view == "list":
        _items_list(key, values["items"])

    clean = []
    for row in rows:
        name = "" if pd.isna(row.get("name")) else str(row["name"]).strip()
        if not name:
            continue
        price = 0.0 if pd.isna(row.get("price")) else round(float(row["price"]), 2)
        quantity = row.get("quantity")
        quantity = 1.0 if pd.isna(quantity) or float(quantity) <= 0 else round(float(quantity), 3)
        clean.append({"name": name, "category": normalize_category(row.get("category")), "price": price, "quantity": quantity})

    values.update(purchased_on=purchased_on, store=store, total=total, paid_by=paid_by, personal=personal, items=clean)
    items_sum = round(sum(i["price"] for i in clean), 2)
    st.caption(f"{len(clean)} items · add up to {euro(items_sum)}")
    if total is not None and abs(items_sum - total) > 0.05:
        st.warning(
            f"Items add up to **{euro(items_sum)}** but the receipt total is **{euro(total)}**. "
            "Check for missing items or discounts."
        )

    return {
        "purchased_on": purchased_on,
        "store": store,
        "total": None if total is None else round(total, 2),
        "paid_by": paid_by,
        "personal": personal,
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
