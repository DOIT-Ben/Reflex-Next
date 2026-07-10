"""NDJSON Runtime sidecar entrypoint."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import TextIO


class OsFdAdapter:
    """Injectable process-FD operations used before plugin imports."""

    @staticmethod
    def duplicate(fd: int) -> int:
        return os.dup(fd)

    @staticmethod
    def redirect_outputs_to_sink() -> None:
        sink_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(sink_fd, 1)
            os.dup2(sink_fd, 2)
        finally:
            os.close(sink_fd)

    @staticmethod
    def open_writer(fd: int) -> TextIO:
        return os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
            closefd=True,
        )

    @staticmethod
    def close_fd(fd: int) -> None:
        os.close(fd)

    @staticmethod
    def restore(source_fd: int, target_fd: int) -> None:
        os.dup2(source_fd, target_fd)


@dataclass
class _ProtocolStreams:
    fd_adapter: OsFdAdapter
    original_fd1: int
    original_fd2: int
    protocol: TextIO
    diagnostic: TextIO
    sink_stdout: TextIO
    sink_stderr: TextIO
    original_stdout: TextIO
    original_stderr: TextIO
    original_dunder_stdout: TextIO
    original_dunder_stderr: TextIO
    closing: bool = False
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        if self.closing:
            return
        self.closing = True
        first_error: Exception | None = None

        def attempt(action) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as error:
                if first_error is None:
                    first_error = error

        try:
            for stream in (
                self.protocol,
                self.diagnostic,
                self.sink_stdout,
                self.sink_stderr,
            ):
                attempt(stream.flush)
            attempt(lambda: self.fd_adapter.restore(self.original_fd1, 1))
            attempt(lambda: self.fd_adapter.restore(self.original_fd2, 2))
            attempt(lambda: setattr(sys, "stdout", self.original_stdout))
            attempt(lambda: setattr(sys, "stderr", self.original_stderr))
            attempt(lambda: setattr(sys, "__stdout__", self.original_dunder_stdout))
            attempt(lambda: setattr(sys, "__stderr__", self.original_dunder_stderr))
            for stream in (
                self.protocol,
                self.diagnostic,
                self.sink_stdout,
                self.sink_stderr,
            ):
                attempt(stream.close)
            attempt(lambda: self.fd_adapter.close_fd(self.original_fd1))
            attempt(lambda: self.fd_adapter.close_fd(self.original_fd2))
        finally:
            self.closing = False
            self.closed = True
        if first_error is not None:
            raise first_error


def main(fd_adapter: OsFdAdapter | None = None) -> int:
    _configure_stdin()
    streams = _isolate_process_output(fd_adapter or OsFdAdapter())
    runtime = None
    try:
        # Importing RuntimeContext can discover and import development plugins.
        from .context import RuntimeContext
        from .protocol import ProtocolError, parse_command

        runtime = RuntimeContext(stdout=streams.protocol, stderr=streams.diagnostic)
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
                runtime.emit_error(
                    "runtime",
                    "invalid_json",
                    f"Invalid JSON command: {exc}",
                    action="retry",
                )
                runtime.diagnostic(f"invalid_json: {exc}")
            except ProtocolError as exc:
                request_id = _safe_request_id(line)
                runtime.emit_error(
                    request_id, "protocol_error", str(exc), action="retry"
                )
                runtime.diagnostic(
                    f"protocol_error request_id={request_id}: {exc}"
                )
            except Exception as exc:
                request_id = _safe_request_id(line)
                runtime.emit_error(
                    request_id,
                    "runtime_error",
                    "Runtime command failed.",
                    action="retry",
                )
                runtime.diagnostic(
                    f"runtime_error request_id={request_id} category={type(exc).__name__}"
                )
        return 0
    finally:
        if runtime is not None:
            runtime.close()
        streams.close()


def _safe_request_id(line: str) -> str:
    try:
        payload = json.loads(line)
    except Exception:
        return "runtime"
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    return request_id if isinstance(request_id, str) and request_id.strip() else "runtime"


def _configure_stdin() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")


def _isolate_process_output(fd_adapter: OsFdAdapter) -> _ProtocolStreams:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_dunder_stdout = sys.__stdout__
    original_dunder_stderr = sys.__stderr__

    original_fd1 = None
    original_fd2 = None
    protocol_fd = None
    diagnostic_fd = None
    sink_stdout_fd = None
    sink_stderr_fd = None
    opened_streams: list[TextIO] = []
    try:
        original_fd1 = fd_adapter.duplicate(1)
        original_fd2 = fd_adapter.duplicate(2)
        protocol_fd = fd_adapter.duplicate(1)
        diagnostic_fd = fd_adapter.duplicate(2)
        fd_adapter.redirect_outputs_to_sink()
        protocol = fd_adapter.open_writer(protocol_fd)
        opened_streams.append(protocol)
        protocol_fd = None
        diagnostic = fd_adapter.open_writer(diagnostic_fd)
        opened_streams.append(diagnostic)
        diagnostic_fd = None
        sink_stdout_fd = fd_adapter.duplicate(1)
        sink_stdout = fd_adapter.open_writer(sink_stdout_fd)
        opened_streams.append(sink_stdout)
        sink_stdout_fd = None
        sink_stderr_fd = fd_adapter.duplicate(2)
        sink_stderr = fd_adapter.open_writer(sink_stderr_fd)
        opened_streams.append(sink_stderr)
        sink_stderr_fd = None
    except Exception:
        if original_fd1 is not None and original_fd2 is not None:
            for source_fd, target_fd in ((original_fd1, 1), (original_fd2, 2)):
                try:
                    fd_adapter.restore(source_fd, target_fd)
                except OSError:
                    pass
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        sys.__stdout__ = original_dunder_stdout
        sys.__stderr__ = original_dunder_stderr
        for stream in opened_streams:
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        for fd in (
            protocol_fd,
            diagnostic_fd,
            sink_stdout_fd,
            sink_stderr_fd,
            original_fd1,
            original_fd2,
        ):
            if fd is None:
                continue
            try:
                fd_adapter.close_fd(fd)
            except OSError:
                pass
        raise

    sys.stdout = sink_stdout
    sys.stderr = sink_stderr
    sys.__stdout__ = sink_stdout
    sys.__stderr__ = sink_stderr
    return _ProtocolStreams(
        fd_adapter=fd_adapter,
        original_fd1=original_fd1,
        original_fd2=original_fd2,
        protocol=protocol,
        diagnostic=diagnostic,
        sink_stdout=sink_stdout,
        sink_stderr=sink_stderr,
        original_stdout=original_stdout,
        original_stderr=original_stderr,
        original_dunder_stdout=original_dunder_stdout,
        original_dunder_stderr=original_dunder_stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
