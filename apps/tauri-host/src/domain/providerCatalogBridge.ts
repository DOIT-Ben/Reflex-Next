import type { TauriEvent, TauriHostApi } from "./coreBridge";
import type { ProviderReleaseStatus, RuntimeProviderDescriptor } from "./providerCatalog";

export const PROVIDER_CATALOG_UNAVAILABLE_MESSAGE = "模型目录暂不可用，请稍后重试。";

const PROVIDER_CATALOG_EVENT = "reflex://provider-catalog";
const DEFAULT_TIMEOUT_MS = 10_000;
const LISTENER_SETUP_TIMEOUT_MS = 5_000;
const MAX_PROVIDERS = 64;
const MAX_PROVIDER_MODELS = 256;
const MAX_PROVIDER_DISPLAY_NAME_LENGTH = 80;
const MAX_PROVIDER_MODEL_ID_LENGTH = 256;

export type ProviderCatalogBridge = {
  listProviders(options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<RuntimeProviderDescriptor[]>;
};

export class RuntimeProviderCatalogBridge implements ProviderCatalogBridge {
  async listProviders(
    options: { signal?: AbortSignal; timeoutMs?: number } = {}
  ): Promise<RuntimeProviderDescriptor[]> {
    const timeoutMs = positiveTimeout(options.timeoutMs, DEFAULT_TIMEOUT_MS);
    const result = createResult<RuntimeProviderDescriptor[]>();
    let expectedRequestId: string | null = null;
    const pendingPayloads = new Map<string, Record<string, unknown>>();
    let unlisten: (() => void) | undefined;
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    let removeAbortListener: (() => void) | undefined;

    const consume = (payload: Record<string, unknown>) => {
      if (!expectedRequestId) {
        pendingPayloads.set(String(payload.request_id), payload);
        if (pendingPayloads.size > 8) {
          const oldestRequestId = pendingPayloads.keys().next().value;
          if (typeof oldestRequestId === "string") pendingPayloads.delete(oldestRequestId);
        }
        return;
      }
      if (payload.request_id !== expectedRequestId) return;
      try {
        result.resolve(parseProviderCatalogEnvelope(payload));
      } catch {
        result.reject(createSafeError());
      }
    };

    try {
      if (options.signal?.aborted) throw createSafeError();
      unlisten = await listenWithTimeout(
        this.host.listen<Record<string, unknown>>(
          PROVIDER_CATALOG_EVENT,
          (event: TauriEvent<Record<string, unknown>>) => {
            const payload = event.payload;
            if (!isRecord(payload) || !isSafeRequestId(payload.request_id)) return;
            consume(payload);
          }
        ),
        LISTENER_SETUP_TIMEOUT_MS
      );

      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutHandle = setTimeout(() => reject(createSafeError()), timeoutMs);
      });
      const abortPromise = createAbortPromise(options.signal, () => {
        removeAbortListener = undefined;
      });
      removeAbortListener = abortPromise.cleanup;

      const rawRequestId = await Promise.race([
        this.host.invoke<unknown>("runtime_list_providers"),
        timeoutPromise,
        abortPromise.promise
      ]);
      expectedRequestId = normalizeRequestId(rawRequestId);
      const pendingPayload = pendingPayloads.get(expectedRequestId);
      pendingPayloads.clear();
      if (pendingPayload) consume(pendingPayload);

      return await Promise.race([result.promise, timeoutPromise, abortPromise.promise]);
    } catch {
      throw createSafeError();
    } finally {
      if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);
      removeAbortListener?.();
      try {
        unlisten?.();
      } catch {
        // Cleanup failures never become user-visible catalog errors.
      }
    }
  }

  constructor(private readonly host: TauriHostApi) {}
}

export function createProviderCatalogBridge(host: TauriHostApi): ProviderCatalogBridge {
  return new RuntimeProviderCatalogBridge(host);
}

export function parseProviderCatalogEnvelope(
  value: Record<string, unknown>
): RuntimeProviderDescriptor[] {
  if (
    !hasExactKeys(value, ["version", "request_id", "type", "providers"]) ||
    value.version !== 1 ||
    value.type !== "provider_catalog" ||
    !isSafeRequestId(value.request_id) ||
    !Array.isArray(value.providers) ||
    value.providers.length > MAX_PROVIDERS
  ) {
    throw createSafeError();
  }

  const providers = value.providers.map(parseProviderDescriptor);
  let previousId: string | null = null;
  for (const provider of providers) {
    if (previousId !== null && previousId >= provider.id) throw createSafeError();
    previousId = provider.id;
  }
  return providers;
}

function parseProviderDescriptor(value: unknown): RuntimeProviderDescriptor {
  if (!isRecord(value) || !hasExactKeys(value, [
    "id",
    "name",
    "models",
    "default_model",
    "release_status",
    "session_configured"
  ])) {
    throw createSafeError();
  }

  const id = value.id;
  const name = value.name;
  const models = value.models;
  const defaultModel = value.default_model;
  const releaseStatus = value.release_status;
  const sessionConfigured = value.session_configured;
  if (
    !isSafeId(id) ||
    !isSafePublicText(name, MAX_PROVIDER_DISPLAY_NAME_LENGTH) ||
    !Array.isArray(models) ||
    models.length === 0 ||
    models.length > MAX_PROVIDER_MODELS ||
    !models.every((model) => isSafePublicText(model, MAX_PROVIDER_MODEL_ID_LENGTH)) ||
    new Set(models).size !== models.length ||
    !isSafePublicText(defaultModel, MAX_PROVIDER_MODEL_ID_LENGTH) ||
    !models.includes(defaultModel) ||
    !isProviderReleaseStatus(releaseStatus) ||
    typeof sessionConfigured !== "boolean"
  ) {
    throw createSafeError();
  }

  return {
    id,
    name,
    models: [...models],
    defaultModel,
    releaseStatus,
    sessionConfigured
  };
}

function normalizeRequestId(value: unknown): string {
  if (!isSafeRequestId(value)) throw createSafeError();
  return value;
}

function isProviderReleaseStatus(value: unknown): value is ProviderReleaseStatus {
  return value === "supported" || value === "experimental";
}

function isSafeId(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value);
}

function isSafeRequestId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
}

function isSafePublicText(value: unknown, maxLength: number): value is string {
  return (
    typeof value === "string" &&
    value === value.trim() &&
    value.length >= 1 &&
    value.length <= maxLength &&
    !Array.from(value).some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  );
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => key in value);
}

function positiveTimeout(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function createSafeError(): Error {
  return new Error(PROVIDER_CATALOG_UNAVAILABLE_MESSAGE);
}

function createResult<T>() {
  let resolveResult!: (value: T) => void;
  let rejectResult!: (reason: Error) => void;
  let settled = false;
  const promise = new Promise<T>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject;
  });
  return {
    promise,
    resolve(value: T) {
      if (settled) return;
      settled = true;
      resolveResult(value);
    },
    reject(error: Error) {
      if (settled) return;
      settled = true;
      rejectResult(error);
    }
  };
}

function createAbortPromise(signal: AbortSignal | undefined, onCleanup: () => void) {
  let cleanup = () => undefined;
  const promise = new Promise<never>((_, reject) => {
    const fail = () => reject(createSafeError());
    if (!signal) return;
    if (signal.aborted) {
      fail();
      return;
    }
    signal.addEventListener("abort", fail, { once: true });
    cleanup = () => {
      signal.removeEventListener("abort", fail);
      onCleanup();
    };
  });
  return { promise, cleanup: () => cleanup() };
}

function listenWithTimeout(
  listener: Promise<() => void>,
  timeoutMs: number
): Promise<() => void> {
  let settled = false;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  return new Promise((resolve, reject) => {
    const finish = () => {
      if (timeout !== undefined) clearTimeout(timeout);
      timeout = undefined;
    };
    timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(createSafeError());
    }, timeoutMs);
    listener.then(
      (unlisten) => {
        if (settled) {
          try {
            unlisten();
          } catch {
            // Best-effort cleanup if setup completes after the deadline.
          }
          return;
        }
        settled = true;
        finish();
        resolve(unlisten);
      },
      () => {
        if (settled) return;
        settled = true;
        finish();
        reject(createSafeError());
      }
    );
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
