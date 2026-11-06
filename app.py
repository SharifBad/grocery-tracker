"""Entry point: page config, family sign-in gate, and navigation. Pages live in views/."""
import streamlit as st

from grocery import db
from grocery.auth import require_family_member, sign_out
from grocery.config import FAVICON
from grocery.ui import avatar, crisp_image
from grocery.utils import today

st.set_page_config(page_title="Grocery Tracker", page_icon=str(FAVICON), layout="centered")

user = require_family_member()

pages = [
    st.Page("views/upload.py", title="Add receipt", icon="📸", default=True),
    st.Page("views/dashboard.py", title="Dashboard", icon="📊"),
    st.Page("views/history.py", title="History", icon="🧾"),
    st.Page("views/qr.py", title="QR", icon="📱"),
]
page = st.navigation(pages, position="hidden")

# Pages use this to restore state after a visit elsewhere (Streamlit drops off-screen widget state).
previous = st.session_state.get("current_page")
st.session_state["page_changed"] = previous is not None and previous != page.title
st.session_state["current_page"] = page.title

# One row of links on every page instead of the sidebar: always visible on phones, one tap,
# nothing covering the page (the mobile sidebar stays open over the content after navigating).
with st.container(horizontal=True, gap="small", vertical_alignment="center"):
    for p in pages:
        st.page_link(p, label=p.title, icon=p.icon)
    photo = avatar(user)
    if photo:
        crisp_image(photo, 36, alt=user)
    with st.popover(user if photo else f"👤 {user}"):
        if photo:
            crisp_image(photo, 96, alt=user)
        st.download_button(
            "⬇️ Download backup (CSV)",
            data=db.export_csv,  # built only when clicked
            file_name=f"grocery-backup-{today()}.csv",
            mime="text/csv",
            on_click="ignore",
            help="Every receipt and item, for safekeeping. Opens in Excel or Google Sheets.",
        )
        st.button("Sign out", on_click=sign_out)

page.run()
