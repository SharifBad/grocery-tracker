"""Monthly spending overview with comparison to the previous month and a 12-month trend."""
import streamlit as st

from grocery import db
from grocery.ui import euro, month_picker
from grocery.utils import month_label, pretty_month, shift_month, week_label

st.title("📊 Dashboard")

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

if cur.empty:
    st.info(f"Nothing logged for {pretty_month(month)} yet.")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🏷️ By category")
        st.bar_chart(cur.groupby("category")["price"].sum(), horizontal=True)
    with c2:
        st.subheader("🗓️ By week")
        st.bar_chart(cur.assign(week=cur["purchased_on"].map(week_label)).groupby("week")["price"].sum())

    st.subheader("👪 By family member")
    by_member = cur.groupby("uploaded_by", as_index=False)["price"].sum()
    st.dataframe(
        by_member.sort_values("price", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "uploaded_by": "Added by",
            "price": st.column_config.NumberColumn("Spent (€)", format="€%.2f"),
        },
    )

st.subheader("📈 Last 12 months")
window = [shift_month(month, -n) for n in range(11, -1, -1)]
trend = df[df["month"].isin(window)].groupby(["month", "category"], as_index=False)["price"].sum()
st.bar_chart(trend, x="month", y="price", color="category", x_label="", y_label="€")
