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

EXPECTED_HEADERS = ["Date", "Store", "Item", "Category", "Price", "Week", "Month", "Receipt Total"]
current_headers = [h.strip() for h in sheet.row_values(1)[:8]]
if current_headers != EXPECTED_HEADERS:
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
                round(float(item.get("price", 0.0)), 2),
                week_str,
                month_str,
                round(float(data.get("receipt_total", 0.0)), 2)
            ]
            for item in data.get("items", [])
        ]
        sheet.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
        st.success(f"Saved {len(rows)} items from {data.get('store', 'receipt')}!")

# --- TAB 2: MANUAL ENTRY ---
with tab2:
    with st.form("manual_form"):
        m_date = st.date_input("Date", datetime.date.today())
        m_store = st.text_input("Store Name")
        m_item = st.text_input("Item Name")
        m_cat = st.selectbox("Category", ["Produce", "Dairy", "Meat", "Bakery", "Pantry", "Household", "Other"])
        m_price = st.number_input("Price (€)", min_value=0.0, step=0.01)
        if st.form_submit_button("Add Item"):
            d_str = m_date.strftime("%Y-%m-%d")
            w_str = f"{m_date.year}-W{m_date.isocalendar()[1]:02d}"
            mo_str = m_date.strftime("%Y-%m")
            sheet.append_row(
                [d_str, m_store, m_item, m_cat, round(float(m_price), 2), w_str, mo_str, round(float(m_price), 2)],
                value_input_option="USER_ENTERED",
                table_range="A1"
            )
            st.success("Item added to Google Sheet!")

# --- TAB 3: DASHBOARD (WEEKLY & MONTHLY TOTALS) ---
with tab3:
    all_values = sheet.get_all_values()
    
    # Tool buttons to repair shifted rows or clear test data
    col_fix, col_clear = st.columns(2)
    with col_fix:
        if st.button("🧹 Clean Up & Fix Shifted Rows", use_container_width=True):
            repaired_rows = [EXPECTED_HEADERS]
            for r in all_values[1:]:
                non_empty = [c.strip() for c in r if c.strip() != ""]
                if not non_empty or non_empty[0].lower() == "total":
                    continue
                # Find where the shifted row actually starts (first non-empty cell)
                first_idx = next((i for i, c in enumerate(r) if c.strip() != ""), 0)
                aligned = (r[first_idx:] + [""] * 8)[:8]
                repaired_rows.append(aligned)
            sheet.clear()
            sheet.update(range_name=f"A1:H{len(repaired_rows)}", values=repaired_rows, value_input_option="USER_ENTERED")
            st.success("Fixed shifted columns! Reloading...")
            st.rerun()
            
    with col_clear:
        if st.button("🗑️ Delete All Data (Start Fresh)", use_container_width=True):
            sheet.clear()
            sheet.update(range_name="A1:H1", values=[EXPECTED_HEADERS])
            st.success("Sheet cleared! Reloading...")
            st.rerun()

    if len(all_values) > 1:
        cleaned_rows = []
        for row in all_values[1:]:
            padded = (row + [""] * 8)[:8]
            # Skip empty rows or stray 'Total' rows
            if not padded[0].strip() or padded[2].strip().lower() == "total":
                continue
            cleaned_rows.append(padded)

        if cleaned_rows:
            df = pd.DataFrame(cleaned_rows, columns=EXPECTED_HEADERS)
            df["Price"] = pd.to_numeric(
                df["Price"].astype(str).str.replace("€", "").str.replace("$", "").str.replace(",", ".").str.strip(),
                errors="coerce"
            ).fillna(0.0)
            df["Receipt Total"] = pd.to_numeric(
                df["Receipt Total"].astype(str).str.replace("€", "").str.replace("$", "").str.replace(",", ".").str.strip(),
                errors="coerce"
            ).fillna(0.0)

            # Top Summary Metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Spent", f"€{df['Price'].sum():.2f}")
            m2.metric("Items Logged", len(df))
            m3.metric("Stores Visited", df["Store"].nunique())

            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📅 By Month")
                month_df = df.groupby("Month", as_index=False)["Price"].sum().sort_values("Month", ascending=False)
                st.dataframe(
                    month_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Price": st.column_config.NumberColumn("Total (€)", format="€%.2f")}
                )
            with col2:
                st.subheader("🗓️ By Week")
                week_df = df.groupby("Week", as_index=False)["Price"].sum().sort_values("Week", ascending=False)
                st.dataframe(
                    week_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Price": st.column_config.NumberColumn("Total (€)", format="€%.2f")}
                )

            st.subheader("🏷️ Spending by Category")
            cat_df = df.groupby("Category")["Price"].sum()
            st.bar_chart(cat_df)

            st.subheader("🧾 Recent Items")
            st.dataframe(
                df.tail(20).iloc[::-1],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Price": st.column_config.NumberColumn("Price (€)", format="€%.2f"),
                    "Receipt Total": st.column_config.NumberColumn("Receipt Total (€)", format="€%.2f")
                }
            )
        else:
            st.info("Your rows look shifted right now. Click **🧹 Clean Up & Fix Shifted Rows** above to align them automatically!")
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
