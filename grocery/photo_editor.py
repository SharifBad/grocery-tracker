"""Receipt photo step: turn, straighten (tilt) and crop; the crop is then shrunk to a fixed size for Gemini.

The photo and the user's adjustments live in st.session_state["photo"], not in the file uploader,
so they survive switching pages or going back and forth between the photo and the review step
(Streamlit forgets the state of any widget that isn't on screen).
"""
import io

import streamlit as st
from PIL import Image
from streamlit_cropper import st_cropper

from grocery import imaging

STATE = "photo"


def _state():
    return st.session_state.get(STATE)


def has_photo():
    return _state() is not None


def clear_photo():
    st.session_state.pop(STATE, None)


def remount():
    """Call when the photo controls come back on screen: the cropper restarts from the last crop."""
    state = _state()
    if state:
        state["mount"] = state.get("mount", 0) + 1
        state["in_uploader"] = False


def sync_upload(uploaded, page_changed=False):
    """Load a newly uploaded file into state, or forget the photo if the user removed it.

    Returns an error message for unusable files, else None.
    """
    state = _state()
    if uploaded is None:
        # Removed with the uploader's ✕ (it held the file on the previous run and we didn't just
        # arrive from another page or from the review step).
        if state and state.get("in_uploader") and not page_changed:
            clear_photo()
        return None
    if state and state.get("file_id") == uploaded.file_id:
        state["in_uploader"] = True
        return None

    is_pdf = uploaded.type == "application/pdf" or uploaded.name.lower().endswith(".pdf")
    new = {"file_id": uploaded.file_id, "name": uploaded.name, "in_uploader": True, "mount": 0}
    if is_pdf:
        new.update(kind="pdf", data=uploaded.getvalue())
    else:
        try:
            img = imaging.load_photo(uploaded.getvalue(), imaging.WORKING_SHORT_SIDE)
        except imaging.UnusableImage as e:
            clear_photo()
            return str(e)
        new.update(kind="image", original=img, turns=0, tilt=0.0, fracs=None)
    st.session_state[STATE] = new
    return None


def _to_fracs(box, size):
    w, h = size
    left, top, right, bottom = box
    return (left / w, top / h, right / w, bottom / h)


def _to_box(fracs, size):
    w, h = size
    left, top, right, bottom = fracs
    return imaging.clamp_box((left * w, top * h, right * w, bottom * h), size)


def photo_editor():
    """Render the photo controls for the photo in state. Returns (data, mime, filename) for Gemini."""
    state = _state()
    if state["kind"] == "pdf":
        st.caption(f"📄 {state['name']}: PDF receipts are sent to Gemini as they are.")
        return state["data"], "application/pdf", state["name"]
    fid, mount = state["file_id"], state.get("mount", 0)

    # 1. Turn and straighten
    st.markdown("**1. Turn and straighten**")
    turn_row = st.container(horizontal=True)  # stays one row on phones, unlike st.columns
    if turn_row.button("↺ Left", key=f"left_{fid}", help="Rotate 90° left"):
        state["turns"] -= 1
        state["fracs"] = None
    if turn_row.button("↻ Right", key=f"right_{fid}", help="Rotate 90° right"):
        state["turns"] += 1
        state["fracs"] = None
    tilt_key = f"tilt_{fid}"
    if tilt_key not in st.session_state:  # widget state is dropped while off screen; restore it
        st.session_state[tilt_key] = state["tilt"]
    tilt = st.slider("Tilt", -15.0, 15.0, step=0.5, format="%.1f°", key=tilt_key,
                     help="Drag until the lines of text are level.")
    state["tilt"] = tilt

    view = (state["turns"] % 4, tilt)
    if state.get("view") != view:
        rotated = imaging.rotate(state["original"], *view)
        small, _ = imaging.display_copy(rotated)
        state.update(view=view, rotated=rotated, small=small)
    rotated, small = state["rotated"], state["small"]
    if state["fracs"] is None or _to_box(state["fracs"], rotated.size) is None:
        state["fracs"] = _to_fracs(imaging.detect_receipt_box(rotated), rotated.size)

    # 2. Crop. The cropper only reads its starting box when it is created, so the start box is
    # fixed per cropper key (new key on turn, tilt, or coming back on screen).
    st.markdown("**2. Crop to the receipt**")
    st.caption("Tap the red box once, then drag its corner squares so it covers just the receipt.")
    crop_key = f"crop_{fid}_{view[0]}_{tilt}_{mount}"
    if state.get("crop_key") != crop_key:
        left, top, right, bottom = _to_box(state["fracs"], small.size) or (0, 0, small.width, small.height)
        state.update(crop_key=crop_key, crop_start=(left, right, top, bottom))
    rect = st_cropper(
        small, realtime_update=True, box_color="#FF4B4B", return_type="box", should_resize_image=False,
        default_coords=state["crop_start"], stroke_width=2, key=crop_key,
    )
    dragged = (rect["left"], rect["top"], rect["left"] + rect["width"], rect["top"] + rect["height"])
    if imaging.clamp_box(dragged, small.size):  # ignore a box dragged (almost) off the picture
        state["fracs"] = _to_fracs(dragged, small.size)
    box = _to_box(state["fracs"], rotated.size)

    prepared = (view, box)
    if state.get("prepared") != prepared:
        jpeg = imaging.prepare_for_gemini(rotated, box)
        state.update(prepared=prepared, jpeg=jpeg, jpeg_size=Image.open(io.BytesIO(jpeg)).size)
    w, h = state["jpeg_size"]
    with st.expander(f"👀 What Gemini will see: {w} × {h} px, {max(1, len(state['jpeg']) // 1024)} KB"):
        st.image(state["jpeg"])
    return state["jpeg"], "image/jpeg", "receipt.jpg"
