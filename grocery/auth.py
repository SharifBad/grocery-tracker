"""Name-only sign-in: type your name; it must match one in st.secrets["FAMILY"] (case-insensitive).

There is no password. Anyone with the app URL who knows a family member's name can get in.
"""
import streamlit as st

USER_KEY = "user"


def _family():
    try:
        names = st.secrets.get("FAMILY", [])
    except FileNotFoundError:  # no secrets.toml at all
        names = []
    return [str(n).strip() for n in names if str(n).strip()]


def require_family_member():
    """Return the signed-in family member's name, or render the sign-in form and stop."""
    family = _family()
    if st.session_state.get(USER_KEY) in family:
        return st.session_state[USER_KEY]

    st.title("🛒 Bibi's Grocery Tracker")
    if not family:
        st.error('No family members are set up yet. Add `FAMILY = ["Name", ...]` to the app\'s secrets.')
        st.stop()

    with st.form("sign_in"):
        name = st.text_input("Who are you?", placeholder="Your name")
        submitted = st.form_submit_button("Enter", type="primary")
    if submitted:
        match = next((n for n in family if n.casefold() == name.strip().casefold()), None)
        if match:
            st.session_state[USER_KEY] = match
            st.rerun()
        st.error("That name isn't on the family list.")
    st.stop()


def sign_out():
    st.session_state.pop(USER_KEY, None)


def current_user():
    return st.session_state[USER_KEY]
