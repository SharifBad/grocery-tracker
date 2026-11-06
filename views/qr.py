"""Printable QR code that opens the app."""
import io

import qrcode
import streamlit as st

from grocery.config import DEFAULT_APP_URL
from grocery.ui import crisp_image

st.title("📱 Fridge QR code")
app_url = st.text_input("App URL", DEFAULT_APP_URL)
if app_url:
    buf = io.BytesIO()
    qrcode.make(app_url, box_size=20).save(buf, format="PNG")  # ~800 px: sharp at 3x, crisp when printed
    crisp_image(buf.getvalue(), 250, caption="Print & stick on your fridge!", alt="QR code")
