"""Sign-in: your name (must be in FAMILY) plus the shared family code (FAMILY_CODE), from secrets.

Changing FAMILY_CODE signs everyone out on their next click, which is how to revoke access.
Wrong attempts slow down all sign-ins a little (1 s, growing to 10 s with many recent failures),
which makes guessing the code impractical without ever locking the family out.

"Stay signed in" keeps a signed cookie on the device for 30 days: name + expiry + an HMAC keyed
with the family code, so it can't be forged, and changing FAMILY_CODE (or removing the name from
FAMILY) invalidates it. Sign out deletes it.

Streamlit Community Cloud's proxy doesn't pass the cookie on to the app server (st.context.cookies
never sees it there), so on the sign-in page a small script reads it in the browser and reloads
the app's frame once with ?remember=<token> (only its own frame: Cloud's iframe sandbox forbids
navigating the outer page). The app checks that token and removes it from the address.
Locally the cookie is read directly and the script never runs.
"""
import base64
import hashlib
import hmac
import time

import streamlit as st

from grocery.config import LOGO
from grocery.ui import brand_header

USER_KEY = "user"
CODE_KEY = "code_fingerprint"
COOKIE = "gt_remember"
REMEMBER_PARAM = "remember"
REMEMBER_DAYS = 30


def _secret(name, default):
    try:
        return st.secrets.get(name, default)
    except FileNotFoundError:  # no secrets.toml at all
        return default


def _family():
    return [str(n).strip() for n in _secret("FAMILY", []) if str(n).strip()]


@st.cache_resource
def _recent_failures():
    return []  # timestamps of failed sign-ins, shared by all sessions in this server process


def _failure_delay():
    now = time.time()
    failures = _recent_failures()
    failures[:] = [t for t in failures if now - t < 600]
    failures.append(now)
    return min(1 + len(failures) // 5, 10)


def _normalize_code(code):
    # Case and surrounding spaces don't matter: phones like to capitalise the first letter.
    return str(code or "").strip().casefold()


def _fingerprint(code):
    return hashlib.sha256(_normalize_code(code).encode()).hexdigest()


def _cookie_key(family_code):
    return hashlib.sha256(("grocery-tracker-remember:" + _normalize_code(family_code)).encode()).digest()


def make_token(name, family_code, now=None):
    expires = int((now or time.time()) + REMEMBER_DAYS * 86400)
    payload = base64.urlsafe_b64encode(f"{name}|{expires}".encode()).decode().rstrip("=")
    signature = hmac.new(_cookie_key(family_code), payload.encode(), "sha256").hexdigest()[:32]
    return f"{payload}.{signature}"


def read_token(token, family_code, family, now=None):
    """The family member a remember-me token belongs to, or None if forged, expired or revoked."""
    try:
        payload, signature = str(token).split(".")
        expected = hmac.new(_cookie_key(family_code), payload.encode(), "sha256").hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return None
        name, expires = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode().rsplit("|", 1)
        if int(expires) < (now or time.time()):
            return None
        return name if name in family else None
    except Exception:
        return None


def _set_cookie(value, max_age):
    try:
        secure = "; Secure" if str(st.context.url or "").startswith("https") else ""
    except Exception:
        secure = ""
    st.html(
        f"<script>document.cookie = '{COOKIE}={value}; Max-Age={max_age}; Path=/; SameSite=Lax{secure}';</script>",
        unsafe_allow_javascript=True,
    )


def _cookie_value():
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:  # no browser context (tests, scripts)
        return None


def _hand_over_cookie():
    """Browser-side: reload once with ?remember=<cookie> so the app can read it (see module docstring)."""
    st.html(
        f"""<script>
(() => {{
  const found = document.cookie.match(/(?:^|; ){COOKIE}=([^;]+)/);
  if (!found) return;
  // Reload only the app's own frame: Cloud sandboxes it without permission to navigate the outer page.
  const url = new URL(window.location.href);
  if (url.searchParams.has("{REMEMBER_PARAM}")) return;  // already handed over once: never loop
  url.searchParams.set("{REMEMBER_PARAM}", found[1]);
  window.location.replace(url.toString());
}})();
</script>""",
        unsafe_allow_javascript=True,
    )


def _take_query_token():
    """The ?remember= token, removed from the address so it doesn't linger in the URL."""
    try:
        token = st.query_params.get(REMEMBER_PARAM)
        if token is not None:
            del st.query_params[REMEMBER_PARAM]
        return token
    except Exception:
        return None


def require_family_member():
    """Return the signed-in family member's name, or render the sign-in form and stop."""
    family = _family()
    family_code = _secret("FAMILY_CODE", "")
    if (
        st.session_state.get(USER_KEY) in family
        and family_code
        and st.session_state.get(CODE_KEY) == _fingerprint(family_code)
    ):
        if st.session_state.pop("_remember_me", False):  # just signed in with "stay signed in"
            _set_cookie(make_token(st.session_state[USER_KEY], family_code), REMEMBER_DAYS * 86400)
        return st.session_state[USER_KEY]

    st.session_state.pop(USER_KEY, None)
    handed_over = _take_query_token()
    signed_out = st.session_state.get("_signed_out", False)
    # Remembered on this device? (Not right after signing out: this session still sees the old cookie.)
    if family and _normalize_code(family_code) and not signed_out:
        remembered = read_token(_cookie_value(), family_code, family) or read_token(handed_over, family_code, family)
        if remembered:
            st.session_state[USER_KEY] = remembered
            st.session_state[CODE_KEY] = _fingerprint(family_code)
            return remembered

    # Less empty space above the logo (Streamlit's default is 6rem), but still clear of the
    # 3.75rem header bar: any less and the bar covers the top of the logo.
    st.markdown("<style>[data-testid='stMainBlockContainer'] {padding-top: 4.5rem}</style>", unsafe_allow_html=True)
    brand_header(LOGO, "Bibi's Grocery Tracker")
    if not family or not _normalize_code(family_code):
        st.error('Sign-in isn\'t set up yet. Add `FAMILY = ["Name", ...]` and `FAMILY_CODE = "..."` to the app\'s secrets.')
        st.stop()

    with st.form("sign_in"):
        name = st.text_input("Who are you?", placeholder="Your name")
        code = st.text_input("Family code", type="password")
        remember = st.checkbox(f"Stay signed in on this device ({REMEMBER_DAYS} days)", value=True)
        submitted = st.form_submit_button("Enter", type="primary")
    if st.session_state.pop("_clear_cookie", False) or handed_over:
        _set_cookie("", 0)  # signed out, or the remembered login is no longer valid: forget it
    elif not signed_out:
        _hand_over_cookie()
    if submitted:
        match = next((n for n in family if n.casefold() == name.strip().casefold()), None)
        code_ok = hmac.compare_digest(_normalize_code(code).encode(), _normalize_code(family_code).encode())
        if match and code_ok:
            st.session_state[USER_KEY] = match
            st.session_state[CODE_KEY] = _fingerprint(family_code)
            st.session_state.pop("_signed_out", None)
            if remember:
                st.session_state["_remember_me"] = True
            st.rerun()
        time.sleep(_failure_delay())  # slows down guessing
        st.error("That name or family code isn't right.")
    st.stop()


def sign_out():
    """Forget everything, including any half-finished receipt, so the next person starts clean."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state["_signed_out"] = True  # don't sign straight back in from the cookie
    st.session_state["_clear_cookie"] = True


def current_user():
    return st.session_state[USER_KEY]


def family_members():
    """Everyone in FAMILY, as written in the secrets."""
    return _family()
