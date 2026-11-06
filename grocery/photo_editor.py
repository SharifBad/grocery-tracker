"""Receipt photo step: turn, straighten (tilt) and crop; the crop is then shrunk to a fixed size for Gemini."""
import io

import streamlit as st
from PIL import Image
from streamlit_cropper import st_cropper

from grocery import imaging

STATE = "photo"  # session_state key holding the loaded photo and the user's adjustments


def clear_photo():
    st.session_state.pop(STATE, None)


def _to_fracs(box, size):
    w, h = size
    left, top, right, bottom = box
    return (left / w, top / h, right / w, bottom / h)


def _to_box(fracs, size):
    w, h = size
    left, top, right, bottom = fracs
    return (max(0, round(left * w)), max(0, round(top * h)), min(w, round(right * w)), min(h, round(bottom * h)))


def photo_editor(uploaded):
    """Render the photo controls for an uploaded receipt.

    Returns (data, mime, filename) ready for Gemini, or None if the file can't be opened.
    PDFs are passed through untouched.
    """
    if uploaded.type == "application/pdf" or uploaded.name.lower().endswith(".pdf"):
        st.caption("PDF receipts are sent to Gemini as they are.")
        return uploaded.getvalue(), "application/pdf", uploaded.name

    state = st.session_state.setdefault(STATE, {})
    if state.get("file_id") != uploaded.file_id:
        try:
            img = imaging.load_photo(uploaded.getvalue(), imaging.WORKING_SHORT_SIDE)
        except Exception:
            st.error("Couldn't open that image. Try a JPG or PNG photo.")
            return None
        state.clear()
        state.update(file_id=uploaded.file_id, original=img, turns=0, fracs=None)
    fid = state["file_id"]

    # 1. Turn and straighten
    st.markdown("**1. Turn and straighten**")
    turn_row = st.container(horizontal=True)  # stays one row on phones, unlike st.columns
    if turn_row.button("↺ Left", key=f"left_{fid}", help="Rotate 90° left"):
        state["turns"] -= 1
        state["fracs"] = None
    if turn_row.button("↻ Right", key=f"right_{fid}", help="Rotate 90° right"):
        state["turns"] += 1
        state["fracs"] = None
    tilt = st.slider(
        "Tilt", -15.0, 15.0, 0.0, 0.5, format="%.1f°", key=f"tilt_{fid}",
        help="Drag until the lines of text are level.",
    )

    view = (state["turns"] % 4, tilt)
    if state.get("view") != view:
        rotated = imaging.rotate(state["original"], *view)
        small, scale = imaging.display_copy(rotated)
        state.update(view=view, rotated=rotated, small=small)
    rotated, small = state["rotated"], state["small"]
    if state["fracs"] is None:
        state["fracs"] = _to_fracs(imaging.detect_receipt_box(rotated), rotated.size)

    # 2. Crop. The cropper only reads its starting box when it is (re)created, so the start box is
    # fixed per cropper key; passing a fresh one every run could make it jump while being dragged.
    st.markdown("**2. Crop to the receipt**")
    st.caption("Tap the red box once, then drag its corner squares so it covers just the receipt.")
    crop_key = f"crop_{fid}_{view[0]}_{tilt}"
    if state.get("crop_key") != crop_key:
        left, top, right, bottom = _to_box(state["fracs"], small.size)
        state.update(crop_key=crop_key, crop_start=(left, right, top, bottom))
    rect = st_cropper(
        small, realtime_update=True, box_color="#FF4B4B", return_type="box", should_resize_image=False,
        default_coords=state["crop_start"], stroke_width=2, key=crop_key,
    )
    small_box = (rect["left"], rect["top"], rect["left"] + rect["width"], rect["top"] + rect["height"])
    if rect["width"] > 5 and rect["height"] > 5:
        state["fracs"] = _to_fracs(small_box, small.size)
    box = _to_box(state["fracs"], rotated.size)

    prepared = (view, box)
    if state.get("prepared") != prepared:
        jpeg = imaging.prepare_for_gemini(rotated, box)
        state.update(prepared=prepared, jpeg=jpeg, jpeg_size=Image.open(io.BytesIO(jpeg)).size)
    w, h = state["jpeg_size"]
    with st.expander(f"👀 What Gemini will see: {w} × {h} px, {max(1, len(state['jpeg']) // 1024)} KB"):
        st.image(state["jpeg"])
    return state["jpeg"], "image/jpeg", "receipt.jpg"
