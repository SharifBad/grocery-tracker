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
