"""Pure batch text parsing and export capability."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from reflex_core.safety import InputValidationError, validate_input

_MAX_ITEMS = 200


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
            return {"items": _parse(payload)}
        if operation == "export":
            return {"content": _export(payload)}
        if operation == "template":
            return {"content": "prompt\n写一封商务邮件\n解释什么是机器学习\n"}
        raise BatchRunnerError("batch_operation_unavailable")


def _parse(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or set(payload) != {"format", "content"}:
        raise BatchRunnerError("batch_payload_invalid")
    fmt, content = payload.get("format"), payload.get("content")
    if fmt not in {"csv", "txt"} or not isinstance(content, str) or len(content) > 2_000_000:
        raise BatchRunnerError("batch_payload_invalid")
    try:
        if fmt == "txt":
            prompts = [validate_input(line) for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        else:
            rows = csv.DictReader(io.StringIO(content))
            if not rows.fieldnames or not ({"prompt", "提示词"} & set(rows.fieldnames)):
                raise BatchRunnerError("batch_csv_column_missing")
            prompts = [validate_input(row.get("prompt") or row.get("提示词") or "") for row in rows if (row.get("prompt") or row.get("提示词") or "").strip()]
    except (csv.Error, InputValidationError, TypeError):
        raise BatchRunnerError("batch_payload_invalid") from None
    if not prompts or len(prompts) > _MAX_ITEMS:
        raise BatchRunnerError("batch_item_count_invalid")
    return [{"id": index + 1, "prompt": prompt, "status": "pending"} for index, prompt in enumerate(prompts)]


def _export(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"format", "items"} or payload.get("format") not in {"csv", "txt"} or not isinstance(payload.get("items"), list):
        raise BatchRunnerError("batch_payload_invalid")
    items = payload["items"]
    if not items or len(items) > _MAX_ITEMS or any(not isinstance(item, dict) for item in items):
        raise BatchRunnerError("batch_payload_invalid")
    if payload["format"] == "txt":
        return "\n\n".join(f"=== 项目 {item.get('id')} [{item.get('status', 'unknown')}] ===\n原始: {item.get('prompt', '')}\n结果: {item.get('result', '')}" for item in items) + "\n"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["id", "prompt", "result", "status"])
    writer.writeheader()
    for item in items:
        writer.writerow({field: str(item.get(field, ""))[:1_000_000] for field in writer.fieldnames})
    return output.getvalue()


def plugin() -> BatchRunnerPlugin:
    return BatchRunnerPlugin()
