"""grocery.extract with a fake Gemini client: settings sent, compact schema, add-up check and re-read."""
from unittest import mock

import httpx
import pytest
from google.genai import Client, _transformers, errors, types

from grocery import extract
from grocery.config import CATEGORIES


class Usage:
    def __init__(self, n):
        self.total_token_count = n


class Response:
    def __init__(self, text, tokens=1000):
        self.parsed, self.text, self.usage_metadata = None, text, Usage(tokens)


GOOD = '{"d":"2026-11-03","s":"REWE","t":3.00,"i":[{"n":"MILCH","c":"Dairy","p":1.00},{"n":"BROT","c":"Bakery","p":2.00}]}'
OFF_BY_1 = '{"d":"2026-11-03","s":"REWE","t":3.00,"i":[{"n":"MILCH","c":"Dairy","p":1.00},{"n":"BROT","c":"Bakery","p":1.00}]}'
OFF_BY_2 = '{"d":"2026-11-03","s":"REWE","t":3.00,"i":[{"n":"MILCH","c":"Dairy","p":1.00}]}'
NO_TOTAL = '{"d":null,"s":"REWE","t":null,"i":[{"n":"MILCH","c":"Dairy","p":1.00}]}'


def run(*responses, sleep=None):
    fake = mock.MagicMock()
    fake.models.generate_content.side_effect = [r if isinstance(r, Exception) else Response(r) for r in responses]
    notes = []
    with mock.patch.object(extract, "_client", return_value=fake), mock.patch.object(extract.time, "sleep"):
        out = extract.extract_receipt(b"img", "image/jpeg", on_progress=notes.append)
    configs = [c.kwargs["config"] for c in fake.models.generate_content.call_args_list]
    return out, configs, notes


def test_schema_uses_one_letter_keys_and_category_enum():
    schema = _transformers.t_schema(Client(api_key="x")._api_client, extract.ExtractedReceipt)
    assert list(schema.properties) == ["d", "s", "t", "i"]
    item = schema.properties["i"].items
    assert list(item.properties) == ["n", "c", "p"] and item.properties["c"].enum == CATEGORIES


def test_cheap_settings_and_single_call_when_items_add_up():
    out, configs, notes = run(GOOD)
    (config,) = configs
    assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert out["items"] == [{"name": "MILCH", "category": "Dairy", "price": 1.0}, {"name": "BROT", "category": "Bakery", "price": 2.0}]
    assert out["total"] == 3.0 and out["tokens"] == 1000 and not notes


def test_rereads_at_medium_when_items_do_not_add_up():
    out, configs, notes = run(OFF_BY_1, GOOD)
    assert configs[1].media_resolution == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
    assert out["items"][1]["price"] == 2.0 and out["tokens"] == 2000
    assert any("add up" in n for n in notes)


@pytest.mark.parametrize("first, second, expected_items", [(OFF_BY_1, OFF_BY_2, 2), (OFF_BY_2, OFF_BY_1, 2)])
def test_keeps_the_read_closest_to_adding_up(first, second, expected_items):
    out, configs, _ = run(first, second)
    assert len(configs) == 2 and len(out["items"]) == expected_items


def test_no_total_means_no_reread_and_date_guessed():
    out, configs, _ = run(NO_TOTAL)
    assert len(configs) == 1 and out["total"] is None and out["date_guessed"]


def test_store_is_mapped_to_the_chain_and_the_prompt_lists_the_chains():
    from grocery.config import STORES
    out, _, _ = run(GOOD.replace('"s":"REWE"', '"s":"REWE Markt GmbH"'))
    assert out["store"] == "REWE"
    assert all(name in extract.PROMPT for name in STORES)


def test_full_field_names_still_parse():
    out, _, _ = run('{"date":"2026-11-03","store":"X","total":1.0,"items":[{"name":"A","category":"Meat","price":1.0}]}')
    assert out["items"][0]["category"] == "Meat"


def api_error(code):
    return errors.APIError(code, {"error": {"code": code, "message": "test", "status": "TEST"}})


def test_busy_and_network_errors_retry_then_give_up():
    out, configs, notes = run(api_error(503), GOOD)
    assert len(configs) == 2 and any("busy" in n for n in notes) and out["total"] == 3.0
    out, configs, _ = run(httpx.ConnectError("connection reset"), GOOD)
    assert len(configs) == 2 and out["total"] == 3.0
    with pytest.raises(extract.ExtractionError, match="still busy"):
        run(*[api_error(429)] * extract.MAX_ATTEMPTS)


def test_other_errors_fail_fast_with_a_friendly_message():
    with pytest.raises(extract.ExtractionError, match=r"couldn't read this file \(error 400\)"):
        run(api_error(400))
    # Only the status code decides: an unrelated error that merely mentions "503" isn't retried.
    with pytest.raises(extract.ExtractionError, match="couldn't read this file"):
        run(ValueError("bad value 503 in payload"))


def test_failed_reread_keeps_the_first_read():
    out, configs, _ = run(OFF_BY_1, *[api_error(503)] * extract.MAX_ATTEMPTS)
    assert len(configs) == 1 + extract.MAX_ATTEMPTS
    assert [i["price"] for i in out["items"]] == [1.0, 1.0], "first read kept; review step flags the gap"


def test_unparseable_answer_is_a_friendly_error():
    with pytest.raises(extract.ExtractionError, match="couldn't be understood"):
        run("not json")
