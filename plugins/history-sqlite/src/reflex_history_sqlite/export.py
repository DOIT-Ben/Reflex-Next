"""Path-free, UTF-8 history serialization for the host-private exporter."""

from __future__ import annotations

import base64
import csv
import io
import json
from collections import OrderedDict
from typing import Any, Iterable, Iterator

from reflex_core.safety import redact_for_history

from .contract import HistoryPluginError

EXPORT_FIELDS = (
    "id", "created_at", "input", "output", "mode", "style", "scene",
    "provider", "model", "elapsed_ms", "status", "rating", "tags",
)
CHUNK_SIZE = 16 * 1024
MAX_EXPORT_RECORDS = 10_000
MAX_EXPORT_BYTES = 64 * 1024 * 1024


def stream_records(
    records: Iterable[dict[str, Any]],
    format_name: str,
    redaction: str,
    cancellation: Any,
) -> Iterator[dict[str, Any]]:
    record_count = [0]
    total_bytes = 0
    buffer = bytearray()
    for piece in _serialized_pieces(
        records,
        format_name,
        redaction,
        cancellation,
        record_count,
    ):
        cancellation.raise_if_cancelled()
        total_bytes += len(piece)
        if total_bytes > MAX_EXPORT_BYTES:
            raise HistoryPluginError("history_export_too_large")
        offset = 0
        while offset < len(piece):
            cancellation.raise_if_cancelled()
            take = min(CHUNK_SIZE - len(buffer), len(piece) - offset)
            buffer.extend(piece[offset : offset + take])
            offset += take
            if len(buffer) == CHUNK_SIZE:
                yield _chunk_event(bytes(buffer))
                buffer.clear()
    if buffer:
        cancellation.raise_if_cancelled()
        yield _chunk_event(bytes(buffer))
    yield {
        "status": "result",
        "data": {"record_count": record_count[0], "format": format_name},
    }


def _serialized_pieces(
    records: Iterable[dict[str, Any]],
    format_name: str,
    redaction: str,
    cancellation: Any,
    record_count: list[int],
) -> Iterator[bytes]:
    if format_name == "json":
        yield b"["
    elif format_name == "csv":
        yield _csv_line(EXPORT_FIELDS)
    else:
        yield b"# Reflex history export\n\n"
    for source in records:
        cancellation.raise_if_cancelled()
        if record_count[0] >= MAX_EXPORT_RECORDS:
            raise HistoryPluginError("history_export_too_large")
        record = _record(source, redaction)
        if format_name == "json":
            prefix = b"," if record_count[0] else b""
            yield prefix + json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        elif format_name == "csv":
            yield _csv_line([_csv_safe(record[field]) for field in EXPORT_FIELDS])
        else:
            yield _markdown_record(record).encode("utf-8")
        record_count[0] += 1
    if format_name == "json":
        yield b"]"


def _chunk_event(body: bytes) -> dict[str, Any]:
    return {
        "status": "chunk",
        "data": {"bytes": base64.b64encode(body).decode("ascii")},
    }


def _csv_line(values: Iterable[Any]) -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(values)
    return output.getvalue().encode("utf-8")


def _record(record: dict[str, Any], redaction: str) -> OrderedDict[str, Any]:
    return OrderedDict(
        (
            ("id", record["id"]),
            ("created_at", record["created_at"]),
            ("input", redact_for_history(record["input"], redaction)),
            ("output", redact_for_history(record["output"], redaction)),
            ("mode", record["mode"]),
            ("style", record["style"]),
            ("scene", record["scene"]),
            ("provider", record["provider"]),
            ("model", record["model"]),
            ("elapsed_ms", record["elapsed_ms"]),
            ("status", record["status"]),
            ("rating", record["rating"]),
            ("tags", list(record["tags"])),
        )
    )


def _csv_safe(value: Any) -> Any:
    if isinstance(value, list):
        value = json.dumps([_csv_safe(item) for item in value], ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        leading = value[: len(value) - len(value.lstrip())]
        return leading + "'" + value[len(leading):]
    return value


def _markdown_record(record: OrderedDict[str, Any]) -> str:
    return "\n".join(
        [
            f"## {record['id']}",
            f"- Created: {record['created_at']}",
            f"- Mode: {record['mode']}",
            f"- Style: {record['style']}",
            "",
            _fenced("Input", str(record["input"])),
            "",
            _fenced("Output", str(record["output"])),
            "",
        ]
    )


def _fenced(label: str, body: str) -> str:
    longest = max((len(run) for run in body.split("`") if run == ""), default=0)
    longest = max(longest, _longest_backtick_run(body))
    fence = "`" * max(3, longest + 1)
    return f"### {label}\n{fence}text\n{body}\n{fence}"


def _longest_backtick_run(value: str) -> int:
    longest = current = 0
    for character in value:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
