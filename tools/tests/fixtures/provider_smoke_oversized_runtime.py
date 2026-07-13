"""Emit one over-limit NDJSON line and remain alive until the client terminates us."""

from __future__ import annotations

import sys
import time


MAX_RUNTIME_LINE_BYTES = 8 * 1024 * 1024


def main() -> int:
    if not sys.stdin.buffer.readline():
        return 0
    sys.stdout.buffer.write(b"x" * (MAX_RUNTIME_LINE_BYTES + 1))
    sys.stdout.buffer.flush()
    time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
