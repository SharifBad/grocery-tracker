"""Monthly spending overview: budget, comparison to the previous month, breakdowns, Pfand, 12-month trend."""
import logging

import pandas as pd
import streamlit as st

from grocery import db
from grocery.auth import current_user
from grocery.config import CATEGORIES
from grocery.ui import avatar_data_uri, database_errors, euro, flash, month_picker
from grocery.utils import is_pfand, month_label, pretty_month, shift_month, spending_by_week, today

log = logging.getLogger(__name__)
TOTAL = "TOTAL"  # budgets key for the overall monthly budget


def budget_section(cur):
    """Progress against this month's budgets, and a menu to change them."""
    try:
        budgets = db.load_budgets()
    except Exception:  # e.g. the budgets table isn't created yet
        log.warning("Couldn't load budgets", exc_info=True)
        return
    by_category = cur.groupby("category")["price"].sum()
    rows = [(TOTAL, cur["price"].sum())] + [(c, by_category.get(c, 0.0)) for c in CATEGORIES if c in budgets]
    for name, used in rows:
        limit = budgets.get(name)
        if not limit:
            continue
        ratio = used / limit
        label = "Total" if name == TOTAL else name
        text = f"**{label}**: {euro(used)} of {euro(limit)} ({ratio:.0%})"
        st.progress(min(max(ratio, 0.0), 1.0), text=text)
        if ratio >= 1:
            st.error(f"{label} is over budget by {euro(used - limit)}.", icon="🚨")
        elif ratio >= 0.8:
            st.warning(f"{label} has {euro(limit - used)} left this month.", icon="⚠️")

    with st.popover("🎯 Set monthly budgets" if not budgets else "🎯 Change budgets"):
        with st.form("budgets"):
            st.caption("Shared by the whole family. Leave 0 for no budget.")
            amounts = {TOTAL: st.number_input("Total per month (€)", min_value=0.0, step=10.0, value=budgets.get(TOTAL, 0.0))}
            for c in CATEGORIES:
                amounts[c] = st.number_input(f"{c} (€)", min_value=0.0, step=5.0, value=budgets.get(c, 0.0))
            if st.form_submit_button("Save budgets", type="primary"):
                try:
                    db.save_budgets(amounts, current_user())
                except Exception:
                    log.exception("Saving budgets failed")
                    st.error("Couldn't save the budgets. Try again in a moment.")
                    st.stop()
                flash("Budgets saved.")
                st.rerun()


def pfand_section(df, cur):
    """Bottle deposits paid vs returned (Leergut slips are negative)."""
    pfand_all = df[df["name"].map(is_pfand)]
    if pfand_all.empty:
        return
    pfand_now = cur[cur["name"].map(is_pfand)]
    paid = pfand_now.loc[pfand_now["price"] > 0, "price"].sum()
    returned = -pfand_now.loc[pfand_now["price"] < 0, "price"].sum()
    outstanding = pfand_all["price"].sum()
    st.subheader("♻️ Pfand")
    p1, p2, p3 = st.columns(3)
    p1.metric("Paid this month", euro(paid))
    p2.metric("Returned this month", euro(returned))
    p3.metric("Still out (all time)", euro(outstanding), help="Deposits paid minus returned, since the first receipt.")

st.title("📊 Dashboard")
flash()

with database_errors("load your spending"):
    df = db.load_item_lines()
if df.empty:
    st.info("No receipts yet. Add one on the **Add receipt** page.")
    st.stop()

df["month"] = df["purchased_on"].map(month_label)
month = month_picker(df, key="dashboard_month")
prev_month = shift_month(month, -1)
cur = df[df["month"] == month]
spent, prev_spent = cur["price"].sum(), df.loc[df["month"] == prev_month, "price"].sum()

m1, m2, m3 = st.columns(3)
m1.metric(
    "Spent",
    euro(spent),
    delta=f"{euro(spent - prev_spent, signed=True)} vs {pretty_month(prev_month)}" if prev_spent else None,
    delta_color="inverse",
)
m2.metric("Receipts", cur["receipt_id"].nunique())
m3.metric("Items", len(cur))
budget_section(cur)

if cur.empty:
    st.info(f"Nothing logged for {pretty_month(month)} yet.")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🏷️ By category")
        st.bar_chart(cur.groupby("category")["price"].sum(), horizontal=True)
    with c2:
        st.subheader("🗓️ By week")
        weeks = pd.DataFrame(spending_by_week(month, zip(cur["purchased_on"], cur["price"]), until=today()),
                             columns=["week", "spent"])
        st.bar_chart(weeks, x="week", y="spent", sort=False, x_label="", y_label="€")

    st.subheader("🏪 By store")
    by_store = (
        cur.groupby("store")
        .agg(spent=("price", "sum"), receipts=("receipt_id", "nunique"))
        .reset_index()
        .sort_values("spent", ascending=False)
    )
    by_store["share"] = by_store["spent"] / by_store["spent"].sum() if by_store["spent"].sum() else 0.0
    st.dataframe(
        by_store,
        hide_index=True,
        width="stretch",
        column_config={
            "store": "Store",
            "spent": st.column_config.NumberColumn("Spent (€)", format="€%.2f"),
            "receipts": st.column_config.NumberColumn("Receipts"),
            "share": st.column_config.ProgressColumn("Share", format="percent", min_value=0.0, max_value=1.0),
        },
    )

    st.subheader("👪 By family member")
    by_member = cur.groupby("paid_by", as_index=False)["price"].sum()
    by_member.insert(0, "photo", by_member["paid_by"].map(avatar_data_uri))
    st.dataframe(
        by_member.sort_values("price", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "photo": st.column_config.ImageColumn("", width="small"),
            "paid_by": "Paid by",
            "price": st.column_config.NumberColumn("Spent (€)", format="€%.2f"),
        },
    )

pfand_section(df, cur)

st.subheader("📈 Last 12 months")
window = [shift_month(month, -n) for n in range(11, -1, -1)]
trend = df[df["month"].isin(window)].groupby(["month", "category"], as_index=False)["price"].sum()
st.bar_chart(trend, x="month", y="price", color="category", x_label="", y_label="€")
