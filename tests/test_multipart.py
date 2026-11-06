"""Long receipts photographed in parts: all parts go to Gemini in one call."""
from unittest import mock

from test_extract import GOOD, Response

from grocery import extract


def test_parts_are_sent_together_with_the_overlap_note():
    fake = mock.MagicMock()
    fake.models.generate_content.return_value = Response(GOOD)
    with mock.patch.object(extract, "_client", return_value=fake):
        extract.extract_receipt([(b"top", "image/jpeg"), (b"bottom", "image/jpeg")])
        extract.extract_receipt(b"single", "image/jpeg")
    multi, single = (c.kwargs["contents"] for c in fake.models.generate_content.call_args_list)
    assert len(multi) == 3 and "ONE long receipt" in multi[-1]
    assert len(single) == 2 and "ONE long receipt" not in single[-1]
