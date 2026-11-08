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
from grocery.auth import current_user, family_members
from grocery.ui import database_errors, euro, flash, month_picker, receipt_editor, store_options
from grocery.utils import canonical_store, item_key, month_bounds, month_label, pretty_month

log = logging.getLogger(__name__)
SELECTED = "history_selected"  # id of the receipt being viewed
REV = "history_rev"  # bumped after a save/delete to reset the table and editor
SEARCH_HITS = "_history_search_hits"  # (receipt_id, month) per search result row

st.title("🧾 Receipt history")
flash()

def open_from_search():
    """A search result was tapped: show its month and open that receipt (runs before the rerun)."""
    rows = (st.session_state.get("history_search_results") or {}).get("selection", {}).get("rows", [])
    hits = st.session_state.get(SEARCH_HITS, [])
    if rows and rows[0] < len(hits):
        receipt_id, month = hits[rows[0]]
        st.session_state["history_month"] = month
        st.session_state[SELECTED] = receipt_id
        st.session_state["history_table"] = None  # a fresh table, not a deselection
        st.session_state["history_search"] = ""


def search(item_lines, query):
    """Every item whose name, store or category matches `query`, across all months."""
    q = item_key(query)
    store_q = canonical_store(query).casefold()
    hits = item_lines[
        item_lines["name"].map(lambda n: q in item_key(n))
        | item_lines["store"].map(lambda s: q in item_key(s) or store_q == str(s).casefold())
        | item_lines["category"].map(lambda c: q in item_key(c))
    ].sort_values("purchased_on", ascending=False)
    st.caption(f"{len(hits)} item{'s' if len(hits) != 1 else ''} · {euro(hits['price'].sum())} in total. "
               "Tap a row to open that receipt.")
    st.session_state[SEARCH_HITS] = [(r, month_label(d)) for r, d in zip(hits["receipt_id"], hits["purchased_on"])]
    st.dataframe(
        hits[["purchased_on", "store", "name", "category", "price", "paid_by"]],
        hide_index=True, width="stretch", on_select=open_from_search, selection_mode="single-row",
        key="history_search_results",
        column_config={"purchased_on": "Date", "store": "Store", "name": "Item", "category": "Category",
                       "price": st.column_config.NumberColumn("Price (€)", format="€%.2f"), "paid_by": "Paid by"},
    )


with database_errors("load your receipts"):
    item_lines = db.load_item_lines()
query = st.text_input("🔍 Search all receipts", key="history_search", placeholder="Item, store or category, e.g. Katzenfutter")
if query.strip():
    search(item_lines, query)
    st.stop()
with database_errors("load your receipts"):
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
        "Paid by": [db.paid_by(r) for r in receipts],
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
if db.paid_by(r) != r["uploaded_by"]:
    meta += f" · paid by {db.paid_by(r)}"
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
        "paid_by": db.paid_by(r),
        "items": [{"name": i["name"], "category": i["category"], "price": i["price"], "quantity": i.get("quantity") or 1}
                  for i in r["items"]],
    }
edited = receipt_editor(f"edit_{rid}_{rev}", st.session_state[values_key], stores=store_options(item_lines["store"].unique()),
                        user=current_user(), family=family_members())


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
        db.save_receipt({k: edited[k] for k in ("purchased_on", "store", "total", "paid_by")}, edited["items"],
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
