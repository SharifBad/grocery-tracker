import streamlit as st
import pandas as pd
import json
import datetime
import time
import io
import qrcode
import gspread
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types

st.set_page_config(page_title="Grocery Tracker", page_icon="🛒", layout="centered")

# 1. Connect to Gemini & Google Sheets
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_url("https://docs.google.com/spreadsheets/d/1xTZYrQlT9lVTfv6IMMCSE5zViVq-O7PhYd4zFBX0scE/edit?gid=0#gid=0").sheet1

# Auto-check and set headers in Row 1 if missing
EXPECTED_HEADERS = ["Date", "Store", "Item", "Category", "Price", "Week", "Month", "Receipt Total"]
current_headers = [h.strip() for h in sheet.row_values(1)]
if current_headers != EXPECTED_HEADERS:
    if not current_headers:
        sheet.append_row(EXPECTED_HEADERS)
    else:
        sheet.update(range_name="A1:H1", values=[EXPECTED_HEADERS])

st.title("🛒 Bibi's Grocery Tracker")

tab1, tab2, tab3, tab4 = st.tabs(["📸 Scan Bill", "✍️ Manual", "📊 Dashboard", "📱 QR Code"])

# --- TAB 1: AI RECEIPT SCANNER ---
with tab1:
    uploaded_file = st.file_uploader("Upload receipt (Photo or PDF)", type=["jpg", "jpeg", "png", "pdf"])
    
    col_scan, col_stop = st.columns([2, 1])
    with col_scan:
        start_scan = st.button("Extract & Save with Gemini", type="primary", use_container_width=True)
    with col_stop:
        quit_scan = st.button("🛑 Quit Now", use_container_width=True)

    if quit_scan:
        st.warning("Scan cancelled.")
        st.stop()

    if uploaded_file and start_scan:
        prompt = f"""
        Extract this grocery receipt into strict JSON format:
        {{
          "date": "YYYY-MM-DD",
          "store": "Store Name",
          "receipt_total": 0.00,
          "items": [
            {{"name": "Item Name", "category": "Produce/Dairy/Meat/Bakery/Pantry/Household/Other", "price": 0.00}}
          ]
        }}
        If the date is missing, use today's date ({datetime.date.today().strftime('%Y-%m-%d')}). Return ONLY valid JSON.
        """
        file_bytes = uploaded_file.getvalue()
        file_part = types.Part.from_bytes(data=file_bytes, mime_type=uploaded_file.type)

        response = None
        attempt = 1

        with st.status("⏳ Reading your receipt with Gemini (click '🛑 Quit Now' above to cancel)...", expanded=True) as status_box:
            progress_text = st.empty()
            
            while response is None:
                progress_text.info(f"🔄 **Attempt #{attempt}:** Sending receipt to Gemini (`gemini-3.8-flash`)...")
                try:
                    response = client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=[file_part, prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    status_box.update(label=f"✅ Receipt extracted on Attempt #{attempt}!", state="complete", expanded=False)
                    break
                except Exception as e:
                    err_str = str(e)
                    # Retry automatically if the server is busy (503) or rate-limited (429)
                    if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "overloaded" in err_str.lower():
                        for sec in range(5, 0, -1):
                            progress_text.warning(
                                f"⚠️ **Attempt #{attempt}:** Gemini server is busy (503). "
                                f"Retrying automatically in **{sec}s**... *(Click **🛑 Quit Now** above to stop)*"
                            )
                            time.sleep(1)
                        attempt += 1
                    else:
                        status_box.update(label="❌ Non-retryable error occurred", state="error", expanded=True)
                        st.error(f"Error details: {err_str}")
                        st.stop()

        data = json.loads(response.text)
        try:
            dt = datetime.datetime.strptime(data.get("date", ""), "%Y-%m-%d")
        except ValueError:
            dt = datetime.datetime.today()
            data["date"] = dt.strftime("%Y-%m-%d")

        week_str = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        month_str = dt.strftime("%Y-%m")

        rows = [
            [
                data["date"],
                data.get("store", "Unknown Store"),
                item.get("name", "Item"),
                item.get("category", "Other"),
                float(item.get("price", 0.0)),
                week_str,
                month_str,
                float(data.get("receipt_total", 0.0))
            ]
            for item in data.get("items", [])
        ]
        sheet.append_rows(rows)
        st.success(f"Saved {len(rows)} items from {data.get('store', 'receipt')}!")

# --- TAB 2: MANUAL ENTRY ---
with tab2:
    with st.form("manual_form"):
        m_date = st.date_input("Date", datetime.date.today())
        m_store = st.text_input("Store Name")
        m_item = st.text_input("Item Name")
        m_cat = st.selectbox("Category", ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"])
        m_price = st.number_input("Price", min_value=0.0, step=0.01)
        if st.form_submit_button("Add Item"):
            d_str = m_date.strftime("%Y-%m-%d")
            w_str = f"{m_date.year}-W{m_date.isocalendar()[1]:02d}"
            mo_str = m_date.strftime("%Y-%m")
            sheet.append_row([d_str, m_store, m_item, m_cat, m_price, w_str, mo_str, m_price])
            st.success("Item added to Google Sheet!")

# --- TAB 3: DASHBOARD (WEEKLY & MONTHLY TOTALS) ---
with tab3:
    all_values = sheet.get_all_values()
    if len(all_values) > 1:
        headers = [h.strip() for h in all_values[0]]
        df = pd.DataFrame(all_values[1:], columns=headers)
        df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("By Month")
            st.dataframe(df.groupby("Month")["Price"].sum().reset_index())
        with col2:
            st.subheader("By Week")
            st.dataframe(df.groupby("Week")["Price"].sum().reset_index())

        st.subheader("By Category")
        st.bar_chart(df.groupby("Category")["Price"].sum())
        st.dataframe(df.tail(15))
    else:
        st.info("No groceries logged yet.")

# --- TAB 4: FRIDGE QR CODE ---
with tab4:
    app_url = st.text_input("Paste your public Streamlit URL here:", "https://cbecbczmjofch87t5gmwuf.streamlit.app/")
    if app_url:
        qr = qrcode.make(app_url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        st.image(buf.getvalue(), caption="Print & stick on your fridge!", width=250)
