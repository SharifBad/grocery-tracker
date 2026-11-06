"""Price tracking: how prices of things you buy regularly change, and where they were cheapest.

Items are recognised by their printed name (utils.item_key), so tracking works best within one
store: chains print the same product differently. Prices are per receipt line.
"""
import pandas as pd
import streamlit as st

from grocery import db
from grocery.ui import database_errors, euro
from grocery.utils import is_pfand, item_key

MIN_CHANGE = 0.05  # ignore price moves under 5%

st.title("🏷️ Prices")

with database_errors("load your receipts"):
    df = db.load_item_lines()
df = df[(df["price"] > 0) & ~df["name"].map(is_pfand)].copy()
df["key"] = df["name"].map(item_key)
df = df[~df["key"].isin({"", "discount", "rabatt"})]
counts = df.groupby("key")["receipt_id"].nunique()
repeat = df[df["key"].isin(counts[counts >= 2].index)].sort_values(["purchased_on", "item_id"])
if repeat.empty:
    st.info("Price tracking starts once you've bought the same item at least twice.")
    st.stop()
st.caption("Prices are per receipt line: if a line was 2 packs, it shows the price for both.")

# --- Recent changes: last two purchases of an item at the same store ---
st.subheader("📈 Recent price changes")
changes = []
for (_, store), g in repeat.groupby(["key", "store"]):
    if len(g) < 2:
        continue
    before, now = g.iloc[-2], g.iloc[-1]
    change = (now["price"] - before["price"]) / before["price"]
    if abs(change) >= MIN_CHANGE:
        changes.append({"item": now["name"], "store": store, "before": before["price"], "now": now["price"],
                        "change": change * 100, "since": before["purchased_on"]})
if changes:
    table = pd.DataFrame(changes).sort_values("change", key=abs, ascending=False).head(20)
    st.dataframe(
        table, hide_index=True, width="stretch",
        column_config={
            "item": "Item", "store": "Store", "since": "Previous purchase",
            "before": st.column_config.NumberColumn("Before", format="€%.2f"),
            "now": st.column_config.NumberColumn("Now", format="€%.2f"),
            "change": st.column_config.NumberColumn("Change", format="%+.0f%%"),
        },
    )
else:
    st.caption(f"No price moved by {MIN_CHANGE:.0%} or more between your last two purchases.")

# --- Look up one item ---
st.subheader("🔍 Look up an item")
names = repeat.groupby("key")["name"].last()
key = st.selectbox(
    "Item", sorted(names.index, key=lambda k: names[k].casefold()), format_func=names.get, index=None,
    placeholder="Type to search, e.g. Butter", key="prices_item",
)
if key:
    history = df[df["key"] == key].sort_values("purchased_on")
    latest = history.groupby("store").tail(1).sort_values("price")
    if len(latest) > 1:
        best = latest.iloc[0]
        st.success(f"Cheapest lately: **{best['store']}** at {euro(best['price'])} ({best['purchased_on']:%d %b %Y}).")
    chart = history.assign(date=pd.to_datetime(history["purchased_on"]))
    st.line_chart(chart, x="date", y="price", color="store", x_label="", y_label="€")
    st.dataframe(
        history[["purchased_on", "store", "name", "price", "uploaded_by"]].iloc[::-1],
        hide_index=True, width="stretch",
        column_config={"purchased_on": "Date", "store": "Store", "name": "Item",
                       "price": st.column_config.NumberColumn("Price", format="€%.2f"), "uploaded_by": "Added by"},
    )
