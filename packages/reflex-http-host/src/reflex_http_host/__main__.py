"""uvicorn entrypoint for the Reflex Next HTTP host.

Configuration (environment variables):
  REFLEX_HTTP_HOST            bind address (default 127.0.0.1)
  REFLEX_HTTP_PORT            bind port (default 8790)
  REFLEX_HTTP_TOKEN           optional bearer token; empty disables auth
  REFLEX_HTTP_REQUEST_TIMEOUT per-request SSE timeout in seconds (default 120)
  REFLEX_RUNTIME_DEVELOPMENT  set to "0" to disable the development mock
"""

from __future__ import annotations

import os


def main() -> int:
    import uvicorn

    host = os.environ.get("REFLEX_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("REFLEX_HTTP_PORT", "8790"))
    uvicorn.run(
        "reflex_http_host.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
