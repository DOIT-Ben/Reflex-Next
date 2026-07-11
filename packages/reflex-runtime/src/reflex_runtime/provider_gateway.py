"""Restricted Provider gateway exposed only to approved capability plugins."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from reflex_core import OperationCancelled, OptimizeRequest
from reflex_core.safety import safe_provider_error

from .provider_errors import ProviderRuntimeError, provider_unconfigured


class ProviderGateway:
    def __init__(
        self,
        resolve_provider: Callable[[OptimizeRequest], Any],
        provider_id: object,
        model: object,
    ) -> None:
        self._resolve_provider = resolve_provider
        self._provider_id = provider_id
        self._model = model

    def __repr__(self) -> str:
        return "ProviderGateway(<redacted>)"

    def __call__(
        self,
        rendered_request: Any,
        text: str,
        cancellation: Any,
    ) -> Iterable[str]:
        try:
            cancellation.raise_if_cancelled()
            request = OptimizeRequest(
                text=text,
                mode="content",
                style="precise",
                scene="doc_translation",
                scene_policy="manual",
                provider=self._provider_id,
                model=self._model,
                stream=True,
                metadata={"capability": "translator"},
            )
            if request.provider is None:
                raise provider_unconfigured()
            provider = self._resolve_provider(request)
            for chunk in provider.stream(rendered_request, request, cancellation):
                cancellation.raise_if_cancelled()
                yield chunk
        except OperationCancelled:
            raise
        except ProviderRuntimeError:
            raise
        except Exception as error:
            code, message, recoverable, action = safe_provider_error(error)
            raise ProviderRuntimeError(
                code,
                message,
                recoverable=recoverable,
                action=action,
            ) from None
