from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from reflex_core import CancellationToken, OptimizeRequest, OptimizeUseCase, TemplatePackResolver
from reflex_core.scene import RuleSceneDetector
from reflex_provider_minimax.provider import MiniMaxProvider

from .config import CloudSettings
from .schemas import CloudOptimizeRequest


class CloudOptimizerError(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _ProviderConfig:
    model: str
    base_url: str
    timeout_seconds: float
    tls_verify: bool = True
    ca_bundle_path: str | None = None


@dataclass(frozen=True)
class _ActiveRequest:
    installation_id: str
    token: CancellationToken


class CloudOptimizer:
    def __init__(self, settings: CloudSettings, use_case: OptimizeUseCase | None = None) -> None:
        self._settings = settings
        self._use_case = use_case or self._build_use_case(settings)
        self._active: dict[str, _ActiveRequest] = {}
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return self._use_case is not None

    @staticmethod
    def _build_use_case(settings: CloudSettings) -> OptimizeUseCase | None:
        secret = settings.provider_api_key.get_secret_value().strip()
        if not secret:
            return None
        template_root = Path(settings.template_pack_directory).resolve()
        provider = MiniMaxProvider(
            secret,
            _ProviderConfig(
                model=settings.provider_model,
                base_url=settings.provider_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
            ),
        )
        return OptimizeUseCase(
            scene_detector=RuleSceneDetector(),
            template_resolver=TemplatePackResolver.from_directory(template_root),
            provider=provider,
        )

    def claim(self, request_id: str, installation_id: str) -> None:
        if self._use_case is None:
            raise CloudOptimizerError("cloud_provider_unconfigured", 503)
        with self._lock:
            if request_id in self._active:
                raise CloudOptimizerError("optimize_request_conflict", 409)
            if len(self._active) >= self._settings.max_concurrent_global:
                raise CloudOptimizerError("cloud_capacity_reached", 429)
            installation_active = sum(
                item.installation_id == installation_id for item in self._active.values()
            )
            if installation_active >= self._settings.max_concurrent_per_installation:
                raise CloudOptimizerError("installation_concurrency_reached", 429)
            self._active[request_id] = _ActiveRequest(installation_id, CancellationToken())

    def release(self, request_id: str) -> None:
        with self._lock:
            active = self._active.pop(request_id, None)
        if active is not None:
            active.token.cancel()

    def cancel(self, request_id: str, installation_id: str) -> bool:
        with self._lock:
            active = self._active.get(request_id)
        if active is None or active.installation_id != installation_id:
            return False
        active.token.cancel()
        return True

    def stream(self, payload: CloudOptimizeRequest) -> Iterator[dict[str, object]]:
        with self._lock:
            active = self._active.get(payload.request_id)
        if active is None or self._use_case is None:
            raise CloudOptimizerError("optimize_request_unavailable", 409)
        request = OptimizeRequest(
            text=payload.text,
            mode=payload.mode,
            style=payload.style,
            scene=payload.scene,
            scene_policy=payload.scene_policy,
            provider="minimax",
            model=self._settings.provider_model,
            stream=True,
            metadata={"language": payload.language},
        )
        try:
            for envelope in self._use_case.optimize(
                request, request_id=payload.request_id, cancellation=active.token
            ):
                yield envelope.to_dict()
        finally:
            self.release(payload.request_id)
