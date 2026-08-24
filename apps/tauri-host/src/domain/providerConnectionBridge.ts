import type { TauriEvent, TauriHostApi } from "./coreBridge";

export const PROVIDER_MODELS_UNAVAILABLE_MESSAGE = "无法获取模型列表，请检查 Base URL、API Key 和网络连接。";
export const PROVIDER_TEST_UNAVAILABLE_MESSAGE = "模型连接测试失败，请检查配置后重试。";

const MODELS_EVENT = "reflex://provider-models";
const CONNECTION_EVENT = "reflex://provider-connection-result";
const DEFAULT_TIMEOUT_MS = 15_000;

export type ProviderConnectionInput = {
  providerId: string;
  baseUrl: string;
  model?: string | null;
};

export type ProviderConnectionResult = {
  ok: boolean;
  latencyMs: number | null;
  model: string | null;
};

export type ProviderConnectionBridge = {
  discoverModels(input: ProviderConnectionInput, options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<string[]>;
  testConnection(input: ProviderConnectionInput, options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<ProviderConnectionResult>;
};

export function createProviderConnectionBridge(host: TauriHostApi): ProviderConnectionBridge {
  return {
    async discoverModels(input, options) {
      return await requestEvent(host, MODELS_EVENT, "runtime_discover_provider_models", normalizeInput(input, false), parseModels, PROVIDER_MODELS_UNAVAILABLE_MESSAGE, options);
    },
    async testConnection(input, options) {
      return await requestEvent(host, CONNECTION_EVENT, "runtime_test_provider_connection", normalizeInput(input, true), parseConnectionResult, PROVIDER_TEST_UNAVAILABLE_MESSAGE, options);
    }
  };
}

async function requestEvent<T>(
  host: TauriHostApi,
  eventName: string,
  command: string,
  args: Record<string, unknown>,
  parse: (value: unknown) => T,
  safeMessage: string,
  options: { signal?: AbortSignal; timeoutMs?: number } = {}
): Promise<T> {
  const timeoutMs = typeof options.timeoutMs === "number" && options.timeoutMs > 0 ? options.timeoutMs : DEFAULT_TIMEOUT_MS;
  let expectedRequestId: string | null = null;
  let pendingPayload: unknown;
  let resolveResult!: (value: T) => void;
  let rejectResult!: (reason: Error) => void;
  let settled = false;
  const result = new Promise<T>((resolve, reject) => { resolveResult = resolve; rejectResult = reject; });
  const consume = (payload: unknown) => {
    if (!isRecord(payload) || !safeRequestId(payload.request_id)) return;
    if (!expectedRequestId) { pendingPayload = payload; return; }
    if (payload.request_id !== expectedRequestId || settled) return;
    try { settled = true; resolveResult(parse(payload)); } catch { settled = true; rejectResult(new Error(safeMessage)); }
  };
  let unlisten: (() => void) | undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const abort = () => { if (!settled) { settled = true; rejectResult(new Error(safeMessage)); } };
  try {
    if (options.signal?.aborted) throw new Error(safeMessage);
    unlisten = await host.listen(eventName, (event: TauriEvent<unknown>) => consume(event.payload));
    options.signal?.addEventListener("abort", abort, { once: true });
    timeout = setTimeout(abort, timeoutMs);
    const requestId = await host.invoke(command, args);
    if (!safeRequestId(requestId)) throw new Error(safeMessage);
    expectedRequestId = requestId;
    if (isRecord(pendingPayload) && pendingPayload.request_id === expectedRequestId) consume(pendingPayload);
    return await result;
  } catch {
    throw new Error(safeMessage);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
    try { unlisten?.(); } catch { /* best-effort listener cleanup */ }
  }
}

function normalizeInput(input: ProviderConnectionInput, requireModel: boolean): Record<string, unknown> {
  const providerId = input.providerId.trim().toLowerCase();
  const baseUrl = normalizeBaseUrl(input.baseUrl);
  const model = normalizeModel(input.model);
  if (!/^[a-z0-9._-]{1,64}$/.test(providerId) || !baseUrl || (requireModel && !model)) throw new Error();
  return { providerId, baseUrl, ...(model ? { model } : {}) };
}

function normalizeBaseUrl(value: string): string | null {
  const candidate = value.trim();
  if (!candidate || candidate.length > 2048 || Array.from(candidate).some((character) => character.charCodeAt(0) < 32)) return null;
  try {
    const url = new URL(candidate);
    if (url.username || url.password || url.protocol !== "https:") return null;
    return candidate.replace(/\/$/, "");
  } catch { return null; }
}

function normalizeModel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const model = value.trim();
  return model && model.length <= 256 && !Array.from(model).some((character) => character.charCodeAt(0) < 32) ? model : null;
}

function parseModels(value: unknown): string[] {
  if (!isRecord(value) || value.version !== 1 || value.type !== "provider_models" || !Array.isArray(value.models) || value.models.length === 0 || value.models.length > 256) throw new Error();
  const models = value.models.map((item) => typeof item === "string" ? item : isRecord(item) ? item.id : null);
  if (!models.every((model): model is string => Boolean(normalizeModel(model)))) throw new Error();
  return [...new Set(models)];
}

function parseConnectionResult(value: unknown): ProviderConnectionResult {
  if (!isRecord(value) || value.version !== 1 || value.type !== "provider_connection_result" || typeof value.ok !== "boolean") throw new Error();
  const latency = value.latency_ms;
  const latencyMs = typeof latency === "number" && Number.isInteger(latency) && latency >= 0 && latency <= 3_600_000 ? latency : null;
  return { ok: value.ok, latencyMs, model: normalizeModel(value.model) };
}

function safeRequestId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
