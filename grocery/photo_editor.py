"""Receipt photo step: turn, straighten (tilt) and crop; each crop is then shrunk to a fixed size for Gemini.

A receipt can come as up to MAX_PARTS photos (a long receipt photographed in parts) or one PDF.
The photos and the user's adjustments live in st.session_state["photo"], not in the file
uploader, so they survive switching pages or going back and forth between the photo and the
review step (Streamlit forgets the state of any widget that isn't on screen).

st.session_state["photo"] = {"parts": [part, ...], "in_uploader": bool, "mount": int}
part = {"file_id", "name", "kind": "image"|"pdf", ...adjustments and cached images}
"""
import io

import streamlit as st
from PIL import Image
from streamlit_cropper import st_cropper

from grocery import imaging
from grocery.extract import MAX_PARTS

STATE = "photo"


def _state():
    return st.session_state.get(STATE)


def has_photo():
    return bool(_state() and _state()["parts"])


def clear_photo():
    st.session_state.pop(STATE, None)


def remount():
    """Call when the photo controls come back on screen: the cropper restarts from the last crop."""
    state = _state()
    if state:
        state["mount"] = state.get("mount", 0) + 1
        state["in_uploader"] = False


def _load_part(uploaded):
    is_pdf = uploaded.type == "application/pdf" or uploaded.name.lower().endswith(".pdf")
    part = {"file_id": uploaded.file_id, "name": uploaded.name}
    if is_pdf:
        part.update(kind="pdf", data=uploaded.getvalue())
    else:
        img = imaging.load_photo(uploaded.getvalue(), imaging.WORKING_SHORT_SIDE)  # may raise UnusableImage
        part.update(kind="image", original=img, turns=0, tilt=0.0, fracs=None)
    return part


def sync_upload(uploaded, page_changed=False):
    """Bring state in line with the uploader: load new files, drop removed ones.

    `uploaded` is the uploader's list of files. Returns a list of messages to show (unusable
    files, too many files).
    """
    uploaded = list(uploaded or [])
    state = _state()
    if not uploaded:
        # All files removed with ✕ (the uploader held them on the previous run and we didn't just
        # arrive from another page or from the review step, where the uploader starts empty).
        if state and state.get("in_uploader") and not page_changed:
            clear_photo()
        return []

    messages = []
    if len(uploaded) > MAX_PARTS:
        messages.append(f"Only the first {MAX_PARTS} files are used for one receipt.")
        uploaded = uploaded[:MAX_PARTS]
    known = {p["file_id"]: p for p in (state["parts"] if state else [])}
    parts = []
    for file in uploaded:
        if file.file_id in known:
            parts.append(known[file.file_id])
            continue
        try:
            parts.append(_load_part(file))
        except imaging.UnusableImage as e:
            messages.append(f"{file.name}: {e}")
    if any(p["kind"] == "pdf" for p in parts) and len(parts) > 1:
        messages.append("A PDF receipt is read on its own; the other files were left out.")
        parts = [next(p for p in parts if p["kind"] == "pdf")]
    if not parts:
        clear_photo()
        return messages
    mount = state.get("mount", 0) if state else 0
    st.session_state[STATE] = {"parts": parts, "in_uploader": True, "mount": mount}
    return messages


def _to_fracs(box, size):
    w, h = size
    left, top, right, bottom = box
    return (left / w, top / h, right / w, bottom / h)


def _to_box(fracs, size):
    w, h = size
    left, top, right, bottom = fracs
    return imaging.clamp_box((left * w, top * h, right * w, bottom * h), size)


def _view(part):
    """Rotate per the part's turns/tilt (cached) and make sure it has a crop box."""
    view = (part["turns"] % 4, part["tilt"])
    if part.get("view") != view:
        rotated = imaging.rotate(part["original"], *view)
        small, _ = imaging.display_copy(rotated)
        part.update(view=view, rotated=rotated, small=small)
    if part["fracs"] is None or _to_box(part["fracs"], part["rotated"].size) is None:
        part["fracs"] = _to_fracs(imaging.detect_receipt_box(part["rotated"]), part["rotated"].size)
    return view


def _prepared(part):
    """(bytes, mime, name) to send to Gemini for one part, cached until the part changes."""
    if part["kind"] == "pdf":
        return part["data"], "application/pdf", part["name"]
    view = _view(part)
    box = _to_box(part["fracs"], part["rotated"].size)
    if part.get("prepared") != (view, box):
        jpeg = imaging.prepare_for_gemini(part["rotated"], box)
        part.update(prepared=(view, box), jpeg=jpeg, jpeg_size=Image.open(io.BytesIO(jpeg)).size)
    return part["jpeg"], "image/jpeg", part["name"]


def _edit(part, mount):
    """Turn / tilt / crop controls for one photo."""
    fid = part["file_id"]
    st.markdown("**1. Turn and straighten**")
    turn_row = st.container(horizontal=True)  # stays one row on phones, unlike st.columns
    if turn_row.button("↺ Left", key=f"left_{fid}", help="Rotate 90° left"):
        part["turns"] -= 1
        part["fracs"] = None
    if turn_row.button("↻ Right", key=f"right_{fid}", help="Rotate 90° right"):
        part["turns"] += 1
        part["fracs"] = None
    tilt_key = f"tilt_{fid}"
    if tilt_key not in st.session_state:  # widget state is dropped while off screen; restore it
        st.session_state[tilt_key] = part["tilt"]
    part["tilt"] = st.slider("Tilt", -15.0, 15.0, step=0.5, format="%.1f°", key=tilt_key,
                             help="Drag until the lines of text are level.")
    view = _view(part)
    small = part["small"]

    # The cropper only reads its starting box when it is created, so the start box is fixed per
    # cropper key (new key on turn, tilt, or coming back on screen).
    st.markdown("**2. Crop to the receipt**")
    st.caption("Tap the red box once, then drag its corner squares so it covers just the receipt.")
    crop_key = f"crop_{fid}_{view[0]}_{view[1]}_{mount}"
    if part.get("crop_key") != crop_key:
        left, top, right, bottom = _to_box(part["fracs"], small.size) or (0, 0, small.width, small.height)
        part.update(crop_key=crop_key, crop_start=(left, right, top, bottom))
    rect = st_cropper(
        small, realtime_update=True, box_color="#FF4B4B", return_type="box", should_resize_image=False,
        default_coords=part["crop_start"], stroke_width=2, key=crop_key,
    )
    dragged = (rect["left"], rect["top"], rect["left"] + rect["width"], rect["top"] + rect["height"])
    if imaging.clamp_box(dragged, small.size):  # ignore a box dragged (almost) off the picture
        part["fracs"] = _to_fracs(dragged, small.size)

    data, _, _ = _prepared(part)
    w, h = part["jpeg_size"]
    with st.expander(f"👀 What Gemini will see: {w} × {h} px, {max(1, len(data) // 1024)} KB"):
        st.image(data)


def photo_editor():
    """Render the photo controls. Returns [(bytes, mime, name), ...] for Gemini, one per part."""
    state = _state()
    parts, mount = state["parts"], state.get("mount", 0)
    if parts[0]["kind"] == "pdf":
        st.caption(f"📄 {parts[0]['name']}: PDF receipts are sent to Gemini as they are.")
        return [_prepared(parts[0])]

    if len(parts) > 1:
        labels = {p["file_id"]: f"Part {i + 1}" for i, p in enumerate(parts)}
        current = st.segmented_control(
            "Long receipt in parts: adjust each photo", list(labels), format_func=labels.get,
            default=parts[0]["file_id"], key=f"photo_part_{'_'.join(labels)}",
        ) or parts[0]["file_id"]
        part = next(p for p in parts if p["file_id"] == current)
    else:
        part = parts[0]
    _edit(part, mount)
    return [_prepared(p) for p in parts]
