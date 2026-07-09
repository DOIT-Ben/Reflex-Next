"""NDJSON Runtime sidecar entrypoint."""

from __future__ import annotations

import json
import sys

from .context import RuntimeContext
from .protocol import ProtocolError, parse_command


def main() -> int:
    _configure_stdio()
    runtime = RuntimeContext()
    keep_running = True
    for raw_line in sys.stdin:
        if not keep_running:
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            command = parse_command(payload)
            keep_running = runtime.handle(command)
            if not keep_running:
                break
        except json.JSONDecodeError as exc:
            runtime.emit_error("runtime", "invalid_json", f"Invalid JSON command: {exc}", action="retry")
            runtime.diagnostic(f"invalid_json: {exc}")
        except ProtocolError as exc:
            request_id = _safe_request_id(line)
            runtime.emit_error(request_id, "protocol_error", str(exc), action="retry")
            runtime.diagnostic(f"protocol_error request_id={request_id}: {exc}")
        except Exception as exc:
            request_id = _safe_request_id(line)
            runtime.emit_error(request_id, "runtime_error", "Runtime command failed.", action="retry")
            runtime.diagnostic(f"runtime_error request_id={request_id}: {exc}")
    return 0


def _safe_request_id(line: str) -> str:
    try:
        payload = json.loads(line)
    except Exception:
        return "runtime"
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    return request_id if isinstance(request_id, str) and request_id.strip() else "runtime"


def _configure_stdio() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
