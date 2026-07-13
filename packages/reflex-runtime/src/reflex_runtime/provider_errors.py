"""Stable provider errors that are safe to cross the Runtime protocol."""

from __future__ import annotations


class ProviderRuntimeError(RuntimeError):
    """Carry only an approved code, message and recovery action."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        recoverable: bool,
        action: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.recoverable = recoverable
        self.action = action

    def __repr__(self) -> str:
        return (
            "ProviderRuntimeError("
            f"code={self.code!r}, safe_message={self.safe_message!r}, "
            f"recoverable={self.recoverable!r}, action={self.action!r})"
        )


def provider_unconfigured() -> ProviderRuntimeError:
    return ProviderRuntimeError(
        "provider_unconfigured",
        "Provider is not configured.",
        recoverable=True,
        action="settings",
    )


def provider_configuration_invalid() -> ProviderRuntimeError:
    return ProviderRuntimeError(
        "provider_invalid_response",
        "Provider configuration is invalid.",
        recoverable=True,
        action="settings",
    )


def runtime_busy() -> ProviderRuntimeError:
    return ProviderRuntimeError(
        "runtime_busy",
        "Runtime is busy.",
        recoverable=True,
        action="retry",
    )
