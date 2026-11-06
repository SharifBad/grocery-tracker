"""Printable QR code that opens the app."""
import io

import qrcode
import streamlit as st

from grocery.config import DEFAULT_APP_URL

st.title("📱 Fridge QR code")
app_url = st.text_input("App URL", DEFAULT_APP_URL)
if app_url:
    buf = io.BytesIO()
    qrcode.make(app_url).save(buf, format="PNG")
    st.image(buf.getvalue(), caption="Print & stick on your fridge!", width=250)
