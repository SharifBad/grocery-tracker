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
from grocery.extract import MAX_PARTS, ExtractionError, extract_receipt
from grocery.ui import euro, flash, receipt_editor, show_receipt_file, store_options
from grocery.utils import item_key, today

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
        "files": [], "suggested": {}, "remembered": 0, **fields,
    }


def apply_remembered_categories(items):
    """Use categories the family corrected before for these item names. Returns how many changed."""
    try:
        memory = db.load_category_memory()
    except Exception:  # e.g. table not created yet: just use Gemini's categories
        log.warning("Couldn't load category memory", exc_info=True)
        return 0
    changed = 0
    for item in items:
        remembered = memory.get(item_key(item["name"]))
        if remembered and remembered != item["category"]:
            item["category"] = remembered
            changed += 1
    return changed


def remember_corrections(suggested, items):
    """Remember categories the user set themselves: changed ones, and items they added by hand."""
    corrections = {item_key(i["name"]): i["category"] for i in items if suggested.get(item_key(i["name"])) != i["category"]}
    try:
        db.remember_categories(corrections, current_user())
    except Exception:  # never block saving over this
        log.warning("Couldn't remember category corrections", exc_info=True)


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
        "Receipt photo or PDF", type=UPLOAD_TYPES, accept_multiple_files=True,
        key=f"upload_{st.session_state.get('upload_no', 0)}",
        help=f"Long receipt? Add up to {MAX_PARTS} photos, top to bottom.",
    )
    for message in photo.sync_upload(uploaded, page_changed=page_changed):
        st.warning(message)
    if photo.has_photo() and not uploaded:
        st.caption("Using the photo you added earlier. Upload another one to replace it.")
    ready = photo.photo_editor() if photo.has_photo() else None

    c1, c2 = st.columns([2, 1])
    read_label = "🔄 Read again (replaces your items)" if draft else "✨ Read receipt with Gemini"
    if c1.button(read_label, type="primary", disabled=ready is None, width="stretch"):
        parts = [(data, mime) for data, mime, _ in ready]
        with st.status("Reading your receipt with Gemini…", expanded=True) as status:
            try:
                result = extract_receipt(parts, on_progress=status.write)
            except ExtractionError as e:
                status.update(label="❌ Couldn't read the receipt", state="error")
                st.error(str(e))
                st.stop()
            status.update(label=f"✅ Done ({result['tokens']:,} Gemini tokens)", state="complete", expanded=False)
        result["purchased_on"] = result.pop("date")
        result["remembered"] = apply_remembered_categories(result["items"])
        result["suggested"] = {item_key(i["name"]): i["category"] for i in result["items"]}
        start_draft(**result, files=ready)
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
if draft["files"]:
    with st.expander("🧾 What Gemini read"):
        for data, mime, name in draft["files"]:
            show_receipt_file(data, mime, name)
if draft["remembered"]:
    st.caption(f"🧠 {draft['remembered']} categor{'y' if draft['remembered'] == 1 else 'ies'} set from your earlier corrections.")
if draft["date_guessed"]:
    st.warning("No date found on the receipt, so today's date is filled in. Please check it.")
if draft["purchased_on"] > today():
    st.warning("This date is in the future. Please check it.")

try:
    used_stores = db.load_item_lines()["store"].unique()
except Exception:  # the dropdown still has the chain list
    used_stores = []
receipt = receipt_editor(f"draft{st.session_state['draft_no']}", draft, stores=store_options(used_stores))

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
    remember_corrections(draft["suggested"], receipt["items"])
    reset()
    flash(f"Saved {len(receipt['items'])} items from {receipt['store'] or 'the receipt'} 🎉")
    st.rerun()
if b2.button("Discard", width="stretch"):
    reset()
    st.rerun()
