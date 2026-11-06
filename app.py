"""Entry point: page config, family sign-in gate, and navigation. Pages live in views/."""
import datetime

import streamlit as st

from grocery import db
from grocery.auth import require_family_member, sign_out

st.set_page_config(page_title="Grocery Tracker", page_icon="🛒", layout="centered")

user = require_family_member()

page = st.navigation(
    [
        st.Page("views/upload.py", title="Add receipt", icon="📸", default=True),
        st.Page("views/dashboard.py", title="Dashboard", icon="📊"),
        st.Page("views/history.py", title="History", icon="🧾"),
        st.Page("views/qr.py", title="Fridge QR", icon="📱"),
    ]
)

with st.sidebar:
    st.caption(f"Signed in as **{user}**")
    st.download_button(
        "⬇️ Download backup (CSV)",
        data=db.export_csv,  # built only when clicked
        file_name=f"grocery-backup-{datetime.date.today()}.csv",
        mime="text/csv",
        on_click="ignore",
        help="Every receipt and item, for safekeeping. Opens in Excel or Google Sheets.",
    )
    st.button("Sign out", on_click=sign_out)

page.run()
