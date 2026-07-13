import csv
import io
from pathlib import Path

import pytest

from reflex_core import CancellationToken, OperationCancelled
from reflex_batch_runner.plugin import BatchRunnerError, BatchRunnerPlugin


FIXTURES = Path(__file__).parent / "fixtures"


class CancelAfterChecks:
    def __init__(self, allowed_checks: int) -> None:
        self.allowed_checks = allowed_checks
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.checks > self.allowed_checks:
            raise OperationCancelled("operation cancelled")


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


def test_csv_export_neutralizes_formula_prefixes_and_preserves_quoting():
    plugin = BatchRunnerPlugin()
    dangerous = ["=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", "\t=1", "\r=1", "\x01@cmd"]
    items = [
        {
            "id": index,
            "prompt": value,
            "result": 'line one,\n"line two"',
            "status": "completed",
        }
        for index, value in enumerate(dangerous, start=1)
    ]

    exported = plugin.invoke(
        "export",
        {"format": "csv", "items": items},
        {},
        CancellationToken(),
    )["content"]
    rows = list(csv.DictReader(io.StringIO(exported, newline=""), strict=True))

    assert [row["prompt"] for row in rows] == [f"'{value}" for value in dangerous]
    assert all(row["result"] == 'line one,\n"line two"' for row in rows)


def test_csv_parser_accepts_embedded_newlines_quotes_and_literal_paths():
    plugin = BatchRunnerPlugin()
    content = (FIXTURES / "adversarial.csv").read_text(encoding="utf-8")

    items = plugin.invoke(
        "parse",
        {"format": "csv", "content": content},
        {},
        CancellationToken(),
    )["items"]

    assert items[0]["prompt"] == 'first line\nsecond line, "quoted"'
    assert items[1]["prompt"] == r"\\server\share\file.txt"


def test_csv_parser_rejects_unterminated_quoted_cell():
    plugin = BatchRunnerPlugin()

    with pytest.raises(BatchRunnerError) as error:
        plugin.invoke(
            "parse",
            {"format": "csv", "content": 'prompt\n"unterminated'},
            {},
            CancellationToken(),
        )

    assert error.value.code == "batch_payload_invalid"


def test_rejects_oversized_cells_rows_and_total_export():
    plugin = BatchRunnerPlugin()
    oversized = "x" * 100_001

    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "parse",
            {"format": "csv", "content": f"prompt,notes\nsafe,{oversized}"},
            {},
            CancellationToken(),
        )

    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "export",
            {"format": "csv", "items": [{"id": 1, "prompt": oversized}]},
            {},
            CancellationToken(),
        )

    too_many_rows = "prompt\n" + "\n".join(f"row-{index}" for index in range(201))
    with pytest.raises(BatchRunnerError) as row_error:
        plugin.invoke(
            "parse",
            {"format": "csv", "content": too_many_rows},
            {},
            CancellationToken(),
        )
    assert row_error.value.code == "batch_item_count_invalid"

    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "export",
            {
                "format": "csv",
                "items": [{"id": index, "prompt": "safe"} for index in range(201)],
            },
            {},
            CancellationToken(),
        )

    large_items = [
        {"id": index, "prompt": "p" * 100_000, "result": "", "status": "completed"}
        for index in range(21)
    ]
    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "export",
            {"format": "csv", "items": large_items},
            {},
            CancellationToken(),
        )


@pytest.mark.parametrize(
    "hostile_format",
    ["../out.csv", r"C:\out.csv", r"\\server\share\out.csv"],
)
def test_rejects_traversal_absolute_and_unc_formats(hostile_format, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = BatchRunnerPlugin()

    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "parse",
            {"format": hostile_format, "content": "prompt\nsafe"},
            {},
            CancellationToken(),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path_field", ["path", "output_path", "filename"])
def test_rejects_path_fields_without_creating_files(path_field, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = BatchRunnerPlugin()
    payload = {
        "format": "csv",
        "items": [{"id": 1, "prompt": "safe", path_field: r"..\outside.csv"}],
    }

    with pytest.raises(BatchRunnerError):
        plugin.invoke("export", payload, {}, CancellationToken())

    assert list(tmp_path.iterdir()) == []


def test_rejects_nested_export_cells_without_partial_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin = BatchRunnerPlugin()

    with pytest.raises(BatchRunnerError):
        plugin.invoke(
            "export",
            {"format": "csv", "items": [{"id": 1, "prompt": ["not", "scalar"]}]},
            {},
            CancellationToken(),
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("operation", ["parse", "export"])
def test_cancellation_is_checked_during_work_without_partial_artifacts(
    operation,
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    plugin = BatchRunnerPlugin()
    payload = (
        {"format": "txt", "content": "first\nsecond\nthird\n"}
        if operation == "parse"
        else {
            "format": "csv",
            "items": [
                {"id": index, "prompt": f"prompt-{index}", "result": "done"}
                for index in range(3)
            ],
        }
    )

    with pytest.raises(OperationCancelled):
        plugin.invoke(operation, payload, {}, CancelAfterChecks(2))

    assert list(tmp_path.iterdir()) == []
