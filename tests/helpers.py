"""Helpers for AppTest-based tests."""
from pathlib import Path

from streamlit import config
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
FAMILY = ["Bibi", "Dad"]
CODE = "lemon tiger 47"


def make_app(user=None, family=FAMILY, code=CODE):
    """AppTest for app.py with test secrets. `user` skips the sign-in form.

    A dummy key is always set: with no secrets at all, Streamlit would fall back to reading the
    real .streamlit/secrets.toml from the working directory.
    """
    from grocery import auth

    # .streamlit/config.toml hides error details from users; tests need to see them.
    config.set_option("client.showErrorDetails", "full")
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["GEMINI_API_KEY"] = "test-not-a-real-key"
    if family is not None:
        at.secrets["FAMILY"] = family
    if code is not None:
        at.secrets["FAMILY_CODE"] = code
    if user:
        at.session_state["user"] = user
        at.session_state["code_fingerprint"] = auth._fingerprint(code)
    return at


def no_exc(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def button(at, text):
    return next(b for b in at.button if text in b.label)


def save_receipt_for_test(store_name, items, user="Bibi", day=None, total=None):
    """Save a receipt through grocery.db (the `store` fixture's in-memory fake). Returns its id."""
    from grocery import db
    from grocery.utils import today

    total = total if total is not None else sum(i["price"] for i in items)
    return db.save_receipt({"purchased_on": day or today(), "store": store_name, "total": total}, items, user)
