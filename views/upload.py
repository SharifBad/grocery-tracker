"""Scan a receipt (or enter one by hand), review Gemini's result, then save."""
import datetime

import streamlit as st

from grocery import db
from grocery.auth import current_user
from grocery.config import MAX_ATTEMPTS, UPLOAD_TYPES
from grocery.extract import ExtractionError, extract_receipt
from grocery.ui import euro, flash, receipt_editor, show_receipt_file

DRAFT = "draft"

st.title("📸 Add a receipt")
flash()


def start_draft(**fields):
    st.session_state["draft_no"] = st.session_state.get("draft_no", 0) + 1  # fresh widget keys
    st.session_state[DRAFT] = {
        "date": datetime.date.today(),
        "date_guessed": False,
        "store": "",
        "total": None,
        "items": [],
        "file": None,
        "mime": None,
        "filename": None,
        **fields,
    }


# --- Step 1: upload ---
if DRAFT not in st.session_state:
    uploaded = st.file_uploader("Receipt photo or PDF", type=UPLOAD_TYPES)
    c1, c2 = st.columns([2, 1])
    if c1.button("✨ Read receipt with Gemini", type="primary", disabled=uploaded is None, width="stretch"):
        with st.status("Reading your receipt with Gemini…", expanded=True) as status:
            try:
                result = extract_receipt(
                    uploaded.getvalue(),
                    uploaded.type,
                    on_retry=lambda attempt, wait: status.write(
                        f"⚠️ Gemini is busy, retrying in {wait}s (attempt {attempt + 1}/{MAX_ATTEMPTS})"
                    ),
                )
            except ExtractionError as e:
                status.update(label="❌ Couldn't read the receipt", state="error")
                st.error(str(e))
                st.stop()
            status.update(label="✅ Done", state="complete", expanded=False)
        start_draft(**result, file=uploaded.getvalue(), mime=uploaded.type, filename=uploaded.name)
        st.rerun()
    if c2.button("✍️ Enter manually", width="stretch"):
        start_draft()
        st.rerun()
    st.stop()

# --- Step 2: review & confirm ---
draft = st.session_state[DRAFT]
st.subheader("Check and fix, then save")
if draft["file"]:
    with st.expander("🧾 Show receipt"):
        show_receipt_file(draft["file"], draft["mime"], draft["filename"])
if draft["date_guessed"]:
    st.warning("No date found on the receipt, so today's date is filled in. Please check it.")

receipt = receipt_editor(
    f"draft{st.session_state['draft_no']}",
    purchased_on=draft["date"],
    store=draft["store"],
    total=draft["total"],
    items=draft["items"],
)

if receipt["store"]:
    dups = db.find_duplicates(receipt["purchased_on"], receipt["store"], receipt["total"])
    if dups:
        who = ", ".join(sorted({d["uploaded_by"] for d in dups}))
        st.warning(
            f"⚠️ {who} already added a {receipt['store']} receipt from {receipt['purchased_on']:%d %b}"
            + (f" for {euro(receipt['total'])}" if receipt["total"] is not None else "")
            + ". Saving again will count it twice."
        )

b1, b2 = st.columns([2, 1])
if b1.button("💾 Save receipt", type="primary", disabled=not receipt["items"], width="stretch"):
    db.save_receipt(
        {k: receipt[k] for k in ("purchased_on", "store", "total")},
        receipt["items"],
        user=current_user(),
    )
    del st.session_state[DRAFT]
    flash(f"Saved {len(receipt['items'])} items from {receipt['store'] or 'the receipt'} 🎉")
    st.rerun()
if b2.button("Discard", width="stretch"):
    del st.session_state[DRAFT]
    st.rerun()
