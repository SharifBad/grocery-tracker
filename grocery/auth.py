"""Sign-in: your name (must be in FAMILY) plus the shared family code (FAMILY_CODE), from secrets.

Changing FAMILY_CODE signs everyone out on their next click, which is how to revoke access.
"""
import hashlib
import hmac
import time

import streamlit as st

USER_KEY = "user"
CODE_KEY = "code_fingerprint"


def _secret(name, default):
    try:
        return st.secrets.get(name, default)
    except FileNotFoundError:  # no secrets.toml at all
        return default


def _family():
    return [str(n).strip() for n in _secret("FAMILY", []) if str(n).strip()]


def _normalize_code(code):
    # Case and surrounding spaces don't matter: phones like to capitalise the first letter.
    return str(code or "").strip().casefold()


def _fingerprint(code):
    return hashlib.sha256(_normalize_code(code).encode()).hexdigest()


def require_family_member():
    """Return the signed-in family member's name, or render the sign-in form and stop."""
    family = _family()
    family_code = _secret("FAMILY_CODE", "")
    if (
        st.session_state.get(USER_KEY) in family
        and family_code
        and st.session_state.get(CODE_KEY) == _fingerprint(family_code)
    ):
        return st.session_state[USER_KEY]

    st.session_state.pop(USER_KEY, None)
    st.title("🛒 Bibi's Grocery Tracker")
    if not family or not _normalize_code(family_code):
        st.error('Sign-in isn\'t set up yet. Add `FAMILY = ["Name", ...]` and `FAMILY_CODE = "..."` to the app\'s secrets.')
        st.stop()

    with st.form("sign_in"):
        name = st.text_input("Who are you?", placeholder="Your name")
        code = st.text_input("Family code", type="password")
        submitted = st.form_submit_button("Enter", type="primary")
    if submitted:
        match = next((n for n in family if n.casefold() == name.strip().casefold()), None)
        code_ok = hmac.compare_digest(_normalize_code(code).encode(), _normalize_code(family_code).encode())
        if match and code_ok:
            st.session_state[USER_KEY] = match
            st.session_state[CODE_KEY] = _fingerprint(family_code)
            st.rerun()
        time.sleep(1)  # slows down guessing
        st.error("That name or family code isn't right.")
    st.stop()


def sign_out():
    st.session_state.pop(USER_KEY, None)
    st.session_state.pop(CODE_KEY, None)


def current_user():
    return st.session_state[USER_KEY]
