"""Add a receipt: photo (turn, straighten, crop) -> Gemini -> review -> save. Or enter it by hand.

Two modes on one page: the photo step, and the review step once a draft exists. They are never
on screen together, so the cropper is always created while visible (inside a collapsed section
it would size itself to 0 px). The draft and the photo live in session state, so both survive
switching modes or pages.
"""
import logging

import streamlit as st

from grocery import db
from grocery import photo_editor as photo
from grocery.auth import current_user
from grocery.config import UPLOAD_TYPES
from grocery.extract import ExtractionError, extract_receipt
from grocery.ui import euro, flash, receipt_editor, show_receipt_file
from grocery.utils import today

log = logging.getLogger(__name__)
DRAFT = "draft"
PHOTO_OPEN = "photo_open"  # True while revisiting the photo step for an existing draft

st.title("📸 Add a receipt")
flash()

page_changed = st.session_state.get("page_changed", False)
if page_changed:
    photo.remount()


def start_draft(**fields):
    st.session_state["draft_no"] = st.session_state.get("draft_no", 0) + 1  # fresh widget keys
    st.session_state[DRAFT] = {
        "purchased_on": today(), "date_guessed": False, "store": "", "total": None, "items": [],
        "file": None, "mime": None, "filename": None, **fields,
    }


def reset():
    """Forget the draft and the photo; a new uploader key empties the file uploader."""
    st.session_state.pop(DRAFT, None)
    st.session_state.pop(PHOTO_OPEN, None)
    photo.clear_photo()
    st.session_state["upload_no"] = st.session_state.get("upload_no", 0) + 1


def open_photo_step():
    st.session_state[PHOTO_OPEN] = True
    photo.remount()


draft = st.session_state.get(DRAFT)

# --- Photo step: upload, turn, straighten, crop, read ---
if draft is None or st.session_state.get(PHOTO_OPEN):
    if draft:
        st.info("Change the photo or crop, then read it again. Until you do, your items are kept.")
        st.button("← Back to the items", on_click=lambda: st.session_state.pop(PHOTO_OPEN, None))
    uploaded = st.file_uploader(
        "Receipt photo or PDF", type=UPLOAD_TYPES, key=f"upload_{st.session_state.get('upload_no', 0)}"
    )
    error = photo.sync_upload(uploaded, page_changed=page_changed)
    if error:
        st.error(error)
    if photo.has_photo() and uploaded is None:
        st.caption("Using the photo you added earlier. Upload another one to replace it.")
    ready = photo.photo_editor() if photo.has_photo() else None

    c1, c2 = st.columns([2, 1])
    read_label = "🔄 Read again (replaces your items)" if draft else "✨ Read receipt with Gemini"
    if c1.button(read_label, type="primary", disabled=ready is None, width="stretch"):
        data, mime, filename = ready
        with st.status("Reading your receipt with Gemini…", expanded=True) as status:
            try:
                result = extract_receipt(data, mime, on_progress=status.write)
            except ExtractionError as e:
                status.update(label="❌ Couldn't read the receipt", state="error")
                st.error(str(e))
                st.stop()
            status.update(label=f"✅ Done ({result['tokens']:,} Gemini tokens)", state="complete", expanded=False)
        result["purchased_on"] = result.pop("date")
        start_draft(**result, file=data, mime=mime, filename=filename)
        st.session_state.pop(PHOTO_OPEN, None)
        st.rerun()
    if not draft and c2.button("✍️ Enter manually", width="stretch"):
        start_draft()
        st.rerun()
    st.stop()

# --- Review step: check, fix, save ---
st.subheader("Check and fix, then save")
if photo.has_photo():
    st.button("📷 Change the crop or read again", on_click=open_photo_step)
if draft["file"]:
    with st.expander("🧾 What Gemini read"):
        show_receipt_file(draft["file"], draft["mime"], draft["filename"])
if draft["date_guessed"]:
    st.warning("No date found on the receipt, so today's date is filled in. Please check it.")
if draft["purchased_on"] > today():
    st.warning("This date is in the future. Please check it.")

receipt = receipt_editor(f"draft{st.session_state['draft_no']}", draft)

if receipt["store"] or receipt["total"] is not None:
    try:
        duplicates = db.find_duplicates(receipt["purchased_on"], receipt["store"], receipt["total"])
    except Exception:  # a warning-only check must never block saving
        log.exception("Duplicate check failed")
        duplicates = []
        st.caption("Couldn't check for duplicates right now.")
    for dup in duplicates:
        amount = f" for {euro(float(dup['total']))}" if dup.get("total") is not None else ""
        st.warning(
            f"⚠️ {dup['uploaded_by']} already added a {dup['store']} receipt from "
            f"{receipt['purchased_on']:%d %b}{amount}. If it's the same one, saving again will count it twice."
        )

b1, b2 = st.columns([2, 1])
if b1.button("💾 Save receipt", type="primary", disabled=not receipt["items"], width="stretch"):
    try:
        db.save_receipt(
            {k: receipt[k] for k in ("purchased_on", "store", "total")},
            receipt["items"],
            user=current_user(),
        )
    except Exception:
        log.exception("Saving a receipt failed")
        st.error("Couldn't save the receipt (the connection may have dropped). Your entries are kept, so try again.")
        st.stop()
    reset()
    flash(f"Saved {len(receipt['items'])} items from {receipt['store'] or 'the receipt'} 🎉")
    st.rerun()
if b2.button("Discard", width="stretch"):
    reset()
    st.rerun()
