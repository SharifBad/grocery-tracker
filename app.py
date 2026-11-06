"""Entry point: page config, family sign-in gate, and navigation. Pages live in views/."""
import streamlit as st

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
    st.button("Sign out", on_click=sign_out)

page.run()
