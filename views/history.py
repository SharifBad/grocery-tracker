"""Browse receipts by month; view, edit or delete any of them.

The selected receipt is remembered by id, not by table row: other family members can add or
delete receipts at any time, which shifts the rows, and acting on "row 3" could then hit a
different receipt.
"""
import hashlib
import logging

import pandas as pd
import streamlit as st

from grocery import db
from grocery.auth import current_user
from grocery.ui import database_errors, flash, month_picker, receipt_editor, store_options
from grocery.utils import item_key, month_bounds, pretty_month

log = logging.getLogger(__name__)
SELECTED = "history_selected"  # id of the receipt being viewed
REV = "history_rev"  # bumped after a save/delete to reset the table and editor

st.title("🧾 Receipt history")
flash()

with database_errors("load your receipts"):
    item_lines = db.load_item_lines()
    month = month_picker(item_lines, key="history_month")
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
# A new table key whenever the list of receipts changes, so a stale row selection is never reused.
ids_hash = hashlib.sha1("|".join(r["id"] for r in receipts).encode()).hexdigest()[:10]
table_key = f"receipts_{month}_{st.session_state.get(REV, 0)}_{ids_hash}"
st.caption("Tap a row to view or edit that receipt.")
event = st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key=table_key,
    column_config={"Total": st.column_config.NumberColumn("Total (€)", format="€%.2f")},
)
rows = [i for i in event.selection.rows if i < len(receipts)]
if rows:
    st.session_state[SELECTED] = receipts[rows[0]]["id"]
elif st.session_state.get("history_table") == table_key and not st.session_state.get("page_changed"):
    st.session_state.pop(SELECTED, None)  # same table, nothing selected: the user deselected
st.session_state["history_table"] = table_key

r = next((x for x in receipts if x["id"] == st.session_state.get(SELECTED)), None)
if r is None:
    st.stop()

st.divider()
st.subheader(f"{r['store']} · {r['purchased_on']}")
meta = f"Added by {r['uploaded_by']}"
if r.get("updated_by"):
    meta += f" · last edited by {r['updated_by']}"
st.caption(meta)

rid, rev = r["id"], st.session_state.get(REV, 0)
values_key = f"history_values_{rid}_{rev}"  # the form's values, kept across reruns and page visits
if values_key not in st.session_state:
    st.session_state[values_key] = {
        "purchased_on": pd.to_datetime(r["purchased_on"]).date(),
        "store": r["store"],
        "total": float(r["total"]) if r["total"] is not None else None,
        "items": [{k: i[k] for k in ("name", "category", "price")} for i in r["items"]],
    }
edited = receipt_editor(f"edit_{rid}_{rev}", st.session_state[values_key], stores=store_options(item_lines["store"].unique()))


def done(message):
    st.session_state[REV] = st.session_state.get(REV, 0) + 1
    st.session_state.pop(SELECTED, None)
    flash(message)
    st.rerun()


def failed(action):
    log.exception("History %s failed", action)
    st.error(f"Couldn't {action} this receipt. Someone else may have just deleted it, or the connection "
             "dropped. Reload the page to see the latest receipts.")
    st.stop()


c1, c2 = st.columns([2, 1])
if c1.button("💾 Save changes", key=f"save_{rid}", type="primary", disabled=not edited["items"], width="stretch"):
    try:
        db.save_receipt({k: edited[k] for k in ("purchased_on", "store", "total")}, edited["items"],
                        user=current_user(), receipt_id=rid)
    except Exception:
        failed("save")
    before = {item_key(i["name"]): i["category"] for i in r["items"]}
    corrections = {item_key(i["name"]): i["category"] for i in edited["items"] if before.get(item_key(i["name"])) != i["category"]}
    try:
        db.remember_categories(corrections, current_user())
    except Exception:  # never block saving over this
        log.warning("Couldn't remember category corrections", exc_info=True)
    done("Receipt updated.")
with c2.popover("🗑️ Delete", key=f"delete_menu_{rid}", width="stretch"):
    st.write(f"Delete this {r['store']} receipt and its {len(r['items'])} items? This can't be undone.")
    if st.button("Yes, delete it", key=f"delete_{rid}", type="primary"):
        try:
            db.delete_receipt(rid)
        except Exception:
            failed("delete")
        done(f"Deleted the {r['store']} receipt.")
