"""Browse receipts by month; view, edit or delete any of them."""
import pandas as pd
import streamlit as st

from grocery import db
from grocery.auth import current_user
from grocery.ui import euro, flash, month_picker, receipt_editor, show_receipt_file
from grocery.utils import month_bounds, pretty_month

st.title("🧾 Receipt history")
flash()

month = month_picker(db.load_item_lines(), key="history_month")
receipts = db.load_receipts(*month_bounds(month))
if not receipts:
    st.info(f"No receipts for {pretty_month(month)}.")
    st.stop()

table = pd.DataFrame(
    {
        "Date": [r["purchased_on"] for r in receipts],
        "Store": [r["store"] for r in receipts],
        "Total": [r["total"] if r["total"] is not None else sum(i["price"] for i in r["items"]) for r in receipts],
        "Items": [len(r["items"]) for r in receipts],
        "Added by": [r["uploaded_by"] for r in receipts],
    }
)
st.caption("Tap a row to view or edit that receipt.")
event = st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key=f"receipts_{month}_{st.session_state.get('history_rev', 0)}",
    column_config={"Total": st.column_config.NumberColumn("Total (€)", format="€%.2f")},
)
if not event.selection.rows:
    st.stop()

r = receipts[event.selection.rows[0]]
st.divider()
st.subheader(f"{r['store']} · {r['purchased_on']}")
meta = f"Added by {r['uploaded_by']}"
if r.get("updated_by"):
    meta += f" · last edited by {r['updated_by']}"
st.caption(meta)

if r.get("image_path"):
    with st.expander("🧾 Show receipt"):
        show_receipt_file(lambda: db.get_image(r["image_path"]), None, r["image_path"])

edited = receipt_editor(
    f"edit_{r['id']}_{st.session_state.get('history_rev', 0)}",
    purchased_on=pd.to_datetime(r["purchased_on"]).date(),
    store=r["store"],
    total=float(r["total"]) if r["total"] is not None else None,
    items=[{k: i[k] for k in ("name", "category", "price")} for i in r["items"]],
)


def done(message):
    st.session_state["history_rev"] = st.session_state.get("history_rev", 0) + 1  # reset table + editor
    flash(message)
    st.rerun()


c1, c2 = st.columns([2, 1])
if c1.button("💾 Save changes", type="primary", disabled=not edited["items"], width="stretch"):
    db.save_receipt(
        {k: edited[k] for k in ("purchased_on", "store", "total")},
        edited["items"],
        user=current_user(),
        receipt_id=r["id"],
    )
    done("Receipt updated.")
with c2.popover("🗑️ Delete", width="stretch"):
    st.write(f"Delete this {r['store']} receipt and its {len(r['items'])} items? This can't be undone.")
    if st.button("Yes, delete it", type="primary"):
        db.delete_receipt(r["id"], r.get("image_path"))
        done(f"Deleted the {r['store']} receipt.")
