"""Pure batch text parsing and export capability."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from reflex_core.safety import InputValidationError, validate_input

_MAX_ITEMS = 200
_MAX_CONTENT_CHARS = 2_000_000
_MAX_CELL_CHARS = 100_000
_EXPORT_FIELDS = ("id", "prompt", "result", "status")
_EXPORT_ITEM_FIELDS = frozenset(_EXPORT_FIELDS)
_FORMULA_PREFIXES = frozenset("=+-@")


class BatchRunnerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BatchRunnerDescriptor:
    plugin_id: str = "batch-runner"
    display_name: str = "Batch Runner"
    version: str = "1"
    kind: str = "command"
    permissions: tuple[str, ...] = ()
    operations: tuple[str, ...] = ("parse", "export", "template")
    public_operations: tuple[str, ...] = ("parse", "export", "template")


class BatchRunnerPlugin:
    descriptor = BatchRunnerDescriptor()

    def invoke(self, operation: str, payload: dict[str, Any], services: Any, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if operation == "parse":
            return {"items": _parse(payload, cancellation)}
        if operation == "export":
            return {"content": _export(payload, cancellation)}
        if operation == "template":
            return {"content": "prompt\n写一封商务邮件\n解释什么是机器学习\n"}
        raise BatchRunnerError("batch_operation_unavailable")


def _parse(payload: object, cancellation: Any) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or set(payload) != {"format", "content"}:
        raise BatchRunnerError("batch_payload_invalid")
    fmt, content = payload.get("format"), payload.get("content")
    if fmt not in {"csv", "txt"} or not isinstance(content, str) or len(content) > _MAX_CONTENT_CHARS:
        raise BatchRunnerError("batch_payload_invalid")
    prompts: list[str] = []
    try:
        if fmt == "txt":
            for line in content.splitlines():
                cancellation.raise_if_cancelled()
                if line.strip() and not line.lstrip().startswith("#"):
                    _append_prompt(prompts, line)
        else:
            rows = csv.DictReader(io.StringIO(content, newline=""), strict=True)
            fieldnames = rows.fieldnames
            if (
                not fieldnames
                or not ({"prompt", "提示词"} & set(fieldnames))
                or any(len(field) > _MAX_CELL_CHARS for field in fieldnames)
            ):
                raise BatchRunnerError("batch_csv_column_missing")
            for row in rows:
                cancellation.raise_if_cancelled()
                if None in row or any(
                    value is not None and len(value) > _MAX_CELL_CHARS
                    for value in row.values()
                ):
                    raise BatchRunnerError("batch_payload_invalid")
                prompt = row.get("prompt") or row.get("提示词") or ""
                if prompt.strip():
                    _append_prompt(prompts, prompt)
    except BatchRunnerError:
        raise
    except (csv.Error, InputValidationError, TypeError):
        raise BatchRunnerError("batch_payload_invalid") from None
    cancellation.raise_if_cancelled()
    if not prompts:
        raise BatchRunnerError("batch_item_count_invalid")
    return [{"id": index + 1, "prompt": prompt, "status": "pending"} for index, prompt in enumerate(prompts)]


def _append_prompt(prompts: list[str], prompt: str) -> None:
    prompts.append(validate_input(prompt, max_length=_MAX_CELL_CHARS))
    if len(prompts) > _MAX_ITEMS:
        raise BatchRunnerError("batch_item_count_invalid")


def _export(payload: object, cancellation: Any) -> str:
    if not isinstance(payload, dict) or set(payload) != {"format", "items"} or payload.get("format") not in {"csv", "txt"} or not isinstance(payload.get("items"), list):
        raise BatchRunnerError("batch_payload_invalid")
    items = payload["items"]
    if not items or len(items) > _MAX_ITEMS or any(not isinstance(item, dict) for item in items):
        raise BatchRunnerError("batch_payload_invalid")
    if payload["format"] == "txt":
        return _export_txt(items, cancellation)
    return _export_csv(items, cancellation)


def _export_txt(items: list[dict[object, object]], cancellation: Any) -> str:
    sections: list[str] = []
    total_chars = 1
    for item in items:
        cancellation.raise_if_cancelled()
        _validate_export_item(item)
        section = (
            f"=== 项目 {_export_cell(item.get('id'))} "
            f"[{_export_cell(item.get('status', 'unknown'))}] ===\n"
            f"原始: {_export_cell(item.get('prompt'))}\n"
            f"结果: {_export_cell(item.get('result'))}"
        )
        total_chars += len(section) + (2 if sections else 0)
        if total_chars > _MAX_CONTENT_CHARS:
            raise BatchRunnerError("batch_payload_invalid")
        sections.append(section)
    cancellation.raise_if_cancelled()
    return "\n\n".join(sections) + "\n"


def _export_csv(items: list[dict[object, object]], cancellation: Any) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_EXPORT_FIELDS)
    try:
        writer.writeheader()
        for item in items:
            cancellation.raise_if_cancelled()
            _validate_export_item(item)
            writer.writerow(
                {
                    field: _neutralize_formula(_export_cell(item.get(field)))
                    for field in _EXPORT_FIELDS
                }
            )
            if output.tell() > _MAX_CONTENT_CHARS:
                raise BatchRunnerError("batch_payload_invalid")
    except BatchRunnerError:
        raise
    except (csv.Error, TypeError, ValueError, UnicodeError):
        raise BatchRunnerError("batch_payload_invalid") from None
    cancellation.raise_if_cancelled()
    return output.getvalue()


def _validate_export_item(item: dict[object, object]) -> None:
    if not set(item).issubset(_EXPORT_ITEM_FIELDS):
        raise BatchRunnerError("batch_payload_invalid")


def _export_cell(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise BatchRunnerError("batch_payload_invalid")
    text = str(value)
    if len(text) > _MAX_CELL_CHARS:
        raise BatchRunnerError("batch_payload_invalid")
    return text


def _neutralize_formula(value: str) -> str:
    if not value:
        return value
    first = ord(value[0])
    if value[0] in _FORMULA_PREFIXES or first < 32 or 127 <= first <= 159:
        return f"'{value}"
    return value


def plugin() -> BatchRunnerPlugin:
    return BatchRunnerPlugin()
