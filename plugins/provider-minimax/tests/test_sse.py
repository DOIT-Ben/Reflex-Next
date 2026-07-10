import json
from pathlib import Path

import pytest

from reflex_provider_minimax.sse import SseProtocolError, extract_json_content, iter_content_chunks


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sse_ignores_keepalive_and_stops_on_done():
    lines = (FIXTURES / "stream_success.jsonl").read_text(encoding="utf-8").splitlines()

    assert list(iter_content_chunks(lines)) == ["第一段", "第二段"]


def test_parse_json_lines_without_sse_prefix():
    lines = [
        json.dumps({"choices": [{"delta": {"content": "JSONL"}}]}),
        "[DONE]",
    ]

    assert list(iter_content_chunks(lines)) == ["JSONL"]


def test_extract_json_content_accepts_message_and_text_shapes():
    fixture = json.loads((FIXTURES / "json_success.json").read_text(encoding="utf-8"))

    assert extract_json_content(fixture) == "完整结果"
    assert extract_json_content({"choices": [{"text": "文本结果"}]}) == "文本结果"


def test_invalid_data_json_raises_a_protocol_error_without_echoing_the_line():
    with pytest.raises(SseProtocolError) as caught:
        list(iter_content_chunks(["data: {private-invalid-json"]))

    assert str(caught.value) == "Provider response was invalid."
    assert "private-invalid-json" not in repr(caught.value)
