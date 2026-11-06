import datetime

from helpers import CODE, make_app, no_exc

from grocery import auth


def sign_in(at, name, code):
    at.text_input[0].input(name)
    at.text_input[1].input(code)
    at.button[0].click().run()
    return at


def on_sign_in_page(at):
    return [t.label for t in at.text_input] == ["Who are you?", "Family code"]


def test_needs_name_and_code(store):
    at = no_exc(make_app().run())
    assert on_sign_in_page(at)
    assert not any("Add a receipt" in t.value for t in at.title)

    sign_in(at, "Bibi", "wrong code")
    assert any("isn't right" in e.value for e in at.error) and on_sign_in_page(at)
    sign_in(at, "Mallory", CODE)
    assert any("isn't right" in e.value for e in at.error) and on_sign_in_page(at)


def test_name_and_code_are_forgiving_about_case_and_spaces(store):
    at = sign_in(no_exc(make_app().run()), "  bibi ", "  LEMON Tiger 47 ")
    no_exc(at)
    assert at.session_state["user"] == "Bibi" and at.title[0].value == "📸 Add a receipt"


def test_sign_out_forgets_everything(store):
    at = make_app(user="Bibi")
    at.session_state["draft_no"] = 1
    at.session_state["draft"] = {"purchased_on": datetime.date(2026, 11, 3), "date_guessed": False, "store": "REWE",
                                 "total": 1.0, "items": [{"name": "X", "category": "Other", "price": 1.0}],
                                 "files": [], "suggested": {}, "remembered": 0}
    at.session_state["photo"] = {"parts": [{"kind": "pdf", "file_id": "f", "name": "r.pdf", "data": b"%PDF"}],
                                 "in_uploader": False, "mount": 0}
    no_exc(at.run())
    next(b for b in at.button if b.label == "Sign out").click().run()
    assert on_sign_in_page(at)
    assert "user" not in at.session_state and "draft" not in at.session_state and "photo" not in at.session_state


def test_wrong_attempts_slow_down_progressively(monkeypatch):
    slept = []
    monkeypatch.setattr(auth.time, "sleep", slept.append)
    auth._recent_failures().clear()
    for _ in range(12):
        slept.append(auth._failure_delay())
    assert slept[0] == 1 and slept[-1] > slept[0] and max(slept) <= 10
    auth._recent_failures().clear()


def test_changing_the_code_signs_everyone_out(store):
    at = make_app(user="Bibi")
    at.session_state["code_fingerprint"] = auth._fingerprint("old code")
    no_exc(at.run())
    assert on_sign_in_page(at)


def test_removed_family_member_is_signed_out(store):
    at = make_app(user="Eve")
    no_exc(at.run())
    assert on_sign_in_page(at)


def test_missing_setup_is_explained():
    for kwargs in ({"family": None}, {"code": None}, {"code": "   "}):
        at = no_exc(make_app(**kwargs).run())
        assert any("isn't set up yet" in e.value for e in at.error), kwargs


def test_name_ignores_capitals_and_always_gets_the_same_account_and_photo(store):
    from grocery.ui import avatar

    for typed in ("SHIQING", "shiqing", "Shiqing", " sHiQiNg "):
        at = sign_in(no_exc(make_app(family=["Shiqing", "Charif"]).run()), typed, CODE)
        no_exc(at)
        assert at.session_state["user"] == "Shiqing", typed
        assert avatar(at.session_state["user"]) and avatar(typed), typed
    assert avatar("CHARIF") == avatar("charif") == avatar("Charif")
