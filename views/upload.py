"""Add a receipt: photo (turn, straighten, crop, resolution) -> Gemini -> review -> save. Or enter it by hand."""
import datetime

import streamlit as st

from grocery import db
from grocery.auth import current_user
from grocery.config import UPLOAD_TYPES
from grocery.extract import ExtractionError, extract_receipt
from grocery.photo_editor import clear_photo, photo_editor
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


def reset():
    """Forget the draft and the photo; a new uploader key empties the file uploader."""
    st.session_state.pop(DRAFT, None)
    clear_photo()
    st.session_state["upload_no"] = st.session_state.get("upload_no", 0) + 1


draft = st.session_state.get(DRAFT)

# --- Step 1: photo (upload, turn, straighten, crop, resolution) and read ---
# Once a draft exists the photo controls stay available, collapsed, so the receipt can be
# re-cropped or read again at a higher resolution without uploading it again.
with st.expander("📷 Receipt photo: adjust and read again", expanded=False) if draft else st.container():
    uploaded = st.file_uploader(
        "Receipt photo or PDF", type=UPLOAD_TYPES, key=f"upload_{st.session_state.get('upload_no', 0)}"
    )
    ready = photo_editor(uploaded) if uploaded else None
    c1, c2 = st.columns([2, 1])
    read_label = "🔄 Read again (replaces the items below)" if draft else "✨ Read receipt with Gemini"
    if c1.button(read_label, type="secondary" if draft else "primary", disabled=ready is None, width="stretch"):
        data, mime, filename = ready
        with st.status("Reading your receipt with Gemini…", expanded=True) as status:
            try:
                result = extract_receipt(data, mime, on_progress=status.write)
            except ExtractionError as e:
                status.update(label="❌ Couldn't read the receipt", state="error")
                st.error(str(e))
                st.stop()
            status.update(label=f"✅ Done ({result['tokens']:,} Gemini tokens)", state="complete", expanded=False)
        start_draft(**result, file=data, mime=mime, filename=filename)
        st.rerun()
    if not draft and c2.button("✍️ Enter manually", width="stretch"):
        start_draft()
        st.rerun()

if not draft:
    st.stop()

# --- Step 2: review & confirm ---
st.subheader("Check and fix, then save")
if draft["file"]:
    with st.expander("🧾 What Gemini read"):
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
    reset()
    flash(f"Saved {len(receipt['items'])} items from {receipt['store'] or 'the receipt'} 🎉")
    st.rerun()
if b2.button("Discard", width="stretch"):
    reset()
    st.rerun()
