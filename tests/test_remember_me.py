"""Stay signed in: remember-me tokens and the sign-in checkbox."""
import pytest
from helpers import CODE, make_app, no_exc

from grocery import auth

FAMILY = ["Bibi", "Dad"]


def test_remember_me_token_round_trip():
    token = auth.make_token("Bibi", CODE)
    assert auth.read_token(token, CODE, FAMILY) == "Bibi"
    assert auth.read_token(token, "  LEMON tiger 47 ", FAMILY) == "Bibi", "same code, different case"


@pytest.mark.parametrize("case", ["forged", "expired", "code changed", "name removed", "garbage", "missing"])
def test_remember_me_token_rejected(case):
    token = auth.make_token("Bibi", CODE)
    payload, signature = token.split(".")
    tampered = auth.make_token("Dad", CODE).split(".")[0] + "." + signature
    cases = {
        "forged": (tampered, CODE, FAMILY, None),
        "expired": (token, CODE, FAMILY, __import__("time").time() + 31 * 86400),
        "code changed": (token, "new code", FAMILY, None),
        "name removed": (token, CODE, ["Dad"], None),
        "garbage": ("not-a-token", CODE, FAMILY, None),
        "missing": (None, CODE, FAMILY, None),
    }
    tok, code, family, now = cases[case]
    assert auth.read_token(tok, code, family, now=now) is None


def test_sign_in_form_offers_stay_signed_in(store):
    at = no_exc(make_app().run())
    assert at.checkbox[0].label.startswith("Stay signed in") and at.checkbox[0].value is True


# --- Streamlit Cloud: the cookie comes back as a one-time ?remember= link parameter ---

def scripts(at):
    return " ".join(str(e.proto) for e in at.get("html"))


def test_valid_token_in_the_link_signs_in_and_is_removed(store):
    at = make_app()
    at.query_params["remember"] = auth.make_token("Bibi", CODE)
    no_exc(at.run())
    assert at.session_state["user"] == "Bibi" and at.title[0].value == "📸 Add a receipt"
    assert "remember" not in at.query_params


def test_invalid_token_in_the_link_clears_the_cookie_instead_of_looping(store):
    for bad in (auth.make_token("Bibi", "an old code"), "garbage", auth.make_token("Mallory", CODE)):
        at = make_app()
        at.query_params["remember"] = bad
        no_exc(at.run())
        assert [t.label for t in at.text_input] == ["Who are you?", "Family code"]
        assert "Max-Age=0" in scripts(at) and "searchParams.set" not in scripts(at), "clears, never hands over again"
        assert "remember" not in at.query_params


def test_sign_in_page_hands_over_a_remembered_cookie(store):
    at = no_exc(make_app().run())
    assert "searchParams.set" in scripts(at) and "gt_remember" in scripts(at)


def test_no_hand_over_after_signing_out(store):
    at = no_exc(make_app(user="Bibi").run())
    next(b for b in at.button if b.label == "Sign out").click().run()
    no_exc(at)
    assert "searchParams.set" not in scripts(at) and "Max-Age=0" in scripts(at)
