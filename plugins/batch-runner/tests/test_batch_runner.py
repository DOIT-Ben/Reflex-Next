import pytest

from reflex_core import CancellationToken
from reflex_batch_runner.plugin import BatchRunnerError, BatchRunnerPlugin


def test_parses_txt_and_csv_without_filesystem_access():
    plugin = BatchRunnerPlugin()
    assert plugin.invoke("parse", {"format": "txt", "content": "# comment\nfirst\nsecond\n"}, {}, CancellationToken())["items"][1]["prompt"] == "second"
    assert plugin.invoke("parse", {"format": "csv", "content": "prompt\nfirst\n"}, {}, CancellationToken())["items"][0]["id"] == 1


def test_export_is_deterministic_and_rejects_bad_inputs():
    plugin = BatchRunnerPlugin()
    exported = plugin.invoke("export", {"format": "csv", "items": [{"id": 1, "prompt": "x", "result": "y", "status": "completed"}]}, {}, CancellationToken())["content"]
    assert "id,prompt,result,status" in exported
    with pytest.raises(BatchRunnerError):
        plugin.invoke("parse", {"format": "csv", "content": "text\nx"}, {}, CancellationToken())
