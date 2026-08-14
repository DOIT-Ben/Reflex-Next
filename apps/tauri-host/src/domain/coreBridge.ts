import { streamMockOptimization } from "./mockCore";
import type { CoreEvent, OptimizeRequestDraft } from "./reflexSession";

export type OptimizeRunOptions = {
  signal?: AbortSignal;
};

export type RuntimeCommandType = "optimize" | "cancel" | "ping" | "shutdown";

export type RuntimeCommandEnvelope = {
  version: 1;
  request_id: string;
  type: RuntimeCommandType;
  payload: Record<string, unknown>;
};

export type CoreEventEnvelope = {
  version: 1;
  request_id: string;
  event: CoreEvent;
};

export type TauriEvent<T> = {
  payload: T;
};

export type TauriHostApi = {
  invoke<T = unknown>(command: string, args?: Record<string, unknown>): Promise<T>;
  listen<T>(
    eventName: string,
    handler: (event: TauriEvent<T>) => void
  ): Promise<() => void>;
};

export interface CoreBridge {
  optimize(
    request: OptimizeRequestDraft,
    options?: OptimizeRunOptions
  ): AsyncGenerator<CoreEvent>;
}

export class DemoCoreBridge implements CoreBridge {
  async *optimize(
    request: OptimizeRequestDraft,
    options: OptimizeRunOptions = {}
  ): AsyncGenerator<CoreEvent> {
    for await (const event of streamMockOptimization(request)) {
      if (options.signal?.aborted) return;
      yield event;
    }
  }
}

export type CoreBridgeInitialization = {
  bridge: CoreBridge;
  runtimeAvailable: boolean;
};

export function createDemoCoreBridge(): CoreBridge {
  return new DemoCoreBridge();
}

export class UnavailableCoreBridge implements CoreBridge {
  async *optimize(): AsyncGenerator<CoreEvent> {
    yield runtimeUnavailableEvent();
  }
}

export class TauriRuntimeBridge implements CoreBridge {
  private readonly requestIdFactory: () => string;
  private readonly runtimeAvailable: boolean;

  constructor(
    private readonly host: TauriHostApi,
    options: { requestIdFactory?: () => string; runtimeAvailable?: boolean } = {}
  ) {
    this.requestIdFactory = options.requestIdFactory ?? createRequestId;
    this.runtimeAvailable = options.runtimeAvailable ?? true;
  }

  async *optimize(
    request: OptimizeRequestDraft,
    options: OptimizeRunOptions = {}
  ): AsyncGenerator<CoreEvent> {
    if (!this.runtimeAvailable) {
      yield runtimeUnavailableEvent();
      return;
    }
    const requestId = this.requestIdFactory();
    const queue = createAsyncEventQueue();
    let unlisten = () => undefined;
    const abort = () => {
      void this.host
        .invoke("runtime_cancel", { command: createCancelCommand(requestId) })
        .finally(() => queue.close());
    };

    try {
      unlisten = await this.host.listen<CoreEventEnvelope>(
        "reflex://core-event",
        ({ payload }) => {
          if (payload.request_id !== requestId) return;
          queue.push(payload.event);
          if (
            payload.event.type === "metric" ||
            payload.event.type === "error" ||
            (payload.event.type === "status" &&
              (payload.event.data.phase === "cancelled" || payload.event.data.phase === "error"))
          ) {
            queue.close();
          }
        }
      );
      if (options.signal?.aborted) {
        abort();
        return;
      }
      options.signal?.addEventListener("abort", abort, { once: true });
      await this.host.invoke("runtime_optimize", {
        command: createOptimizeCommand(requestId, request)
      });

      while (true) {
        const item = await queue.next();
        if (item.done) return;
        yield item.value;
      }
    } catch {
      yield {
        type: "error",
        data: {
          code: "runtime_unavailable",
          message: "运行服务暂不可用，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      };
    } finally {
      options.signal?.removeEventListener("abort", abort);
      unlisten();
    }
  }
}

export class CloudCoreBridge implements CoreBridge {
  private readonly requestIdFactory: () => string;

  constructor(
    private readonly host: TauriHostApi,
    options: { requestIdFactory?: () => string } = {}
  ) {
    this.requestIdFactory = options.requestIdFactory ?? createRequestId;
  }

  async *optimize(
    request: OptimizeRequestDraft,
    options: OptimizeRunOptions = {}
  ): AsyncGenerator<CoreEvent> {
    const requestId = this.requestIdFactory();
    const queue = createAsyncEventQueue();
    let unlisten = () => undefined;
    const abort = () => {
      void this.host
        .invoke("cloud_cancel", { payload: { request_id: requestId } })
        .finally(() => queue.close());
    };

    try {
      unlisten = await this.host.listen<CoreEventEnvelope>(
        "reflex://cloud-event",
        ({ payload }) => {
          if (payload.request_id !== requestId) return;
          queue.push(presentCloudEvent(payload.event));
          if (
            payload.event.type === "metric" ||
            payload.event.type === "error" ||
            (payload.event.type === "status" &&
              (payload.event.data.phase === "cancelled" || payload.event.data.phase === "error"))
          ) {
            queue.close();
          }
        }
      );
      if (options.signal?.aborted) {
        abort();
        return;
      }
      options.signal?.addEventListener("abort", abort, { once: true });
      await this.host.invoke("cloud_optimize", {
        payload: {
          request_id: requestId,
          text: request.text,
          mode: request.mode,
          style: request.style,
          scene: request.scene,
          scene_policy: request.scene_policy,
          language: request.metadata.language
        }
      });

      while (true) {
        const item = await queue.next();
        if (item.done) return;
        yield item.value;
      }
    } catch (error) {
      yield {
        type: "error",
        data: cloudErrorPresentation(error)
      };
    } finally {
      options.signal?.removeEventListener("abort", abort);
      unlisten();
    }
  }
}

export class RoutedCoreBridge extends TauriRuntimeBridge {
  private readonly cloud: CloudCoreBridge;

  constructor(
    host: TauriHostApi,
    options: { requestIdFactory?: () => string; runtimeAvailable?: boolean } = {}
  ) {
    super(host, options);
    this.cloud = new CloudCoreBridge(host, options);
  }

  async *optimize(
    request: OptimizeRequestDraft,
    options: OptimizeRunOptions = {}
  ): AsyncGenerator<CoreEvent> {
    if (request.provider === "reflex-cloud") {
      yield* this.cloud.optimize(request, options);
      return;
    }
    yield* super.optimize(request, options);
  }
}

export async function createDefaultCoreBridge(
  host?: TauriHostApi | null
): Promise<CoreBridgeInitialization> {
  if (!host) {
    return {
      bridge: new UnavailableCoreBridge(),
      runtimeAvailable: false
    };
  }

  let runtimeAvailable = false;
  try {
    runtimeAvailable = await host.invoke<boolean>("runtime_available") === true;
  } catch {}

  return {
    bridge: new RoutedCoreBridge(host, { runtimeAvailable }),
    runtimeAvailable
  };
}

function runtimeUnavailableEvent(): CoreEvent {
  return {
    type: "error",
    data: {
      code: "runtime_unavailable",
      message: "运行服务暂不可用，请稍后重试。",
      recoverable: true,
      action: "retry"
    }
  };
}

export function parseNdjsonEvents(payload: string): CoreEvent[] {
  return parseNdjsonEnvelopes(payload).map((envelope) => envelope.event);
}

export function parseNdjsonEnvelopes(payload: string): CoreEventEnvelope[] {
  return payload
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => toCoreEventEnvelope(JSON.parse(line)));
}

export function selectEventsForRequest(
  envelopes: CoreEventEnvelope[],
  activeRequestId: string
): CoreEvent[] {
  return envelopes
    .filter((envelope) => envelope.request_id === activeRequestId)
    .map((envelope) => envelope.event);
}

export function createOptimizeCommand(
  requestId: string,
  request: OptimizeRequestDraft
): RuntimeCommandEnvelope {
  return createCommand("optimize", requestId, request as unknown as Record<string, unknown>);
}

export function createCancelCommand(requestId: string): RuntimeCommandEnvelope {
  return createCommand("cancel", requestId, {});
}

function createCommand(
  type: RuntimeCommandType,
  requestId: string,
  payload: Record<string, unknown>
): RuntimeCommandEnvelope {
  return {
    version: 1,
    request_id: requestId,
    type,
    payload
  };
}

function toCoreEventEnvelope(value: unknown): CoreEventEnvelope {
  if (!isRecord(value)) {
    throw new Error("Core event must be an object");
  }
  const eventCandidate = isRecord(value.event) ? value.event : value;
  return {
    version: value.version === 1 ? 1 : 1,
    request_id: typeof value.request_id === "string" ? value.request_id : "",
    event: toCoreEvent(eventCandidate)
  };
}

function toCoreEvent(value: unknown): CoreEvent {
  if (!isRecord(value)) {
    throw new Error("Core event must be an object");
  }
  if (!isCoreEventType(value.type)) {
    throw new Error("Unknown Core event type");
  }
  return {
    type: value.type,
    data: isRecord(value.data) ? value.data : {}
  };
}

function isCoreEventType(value: unknown): value is CoreEvent["type"] {
  return (
    value === "status" ||
    value === "scene" ||
    value === "request" ||
    value === "chunk" ||
    value === "done" ||
    value === "error" ||
    value === "metric"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function createRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type CloudErrorPresentation = {
  code: string;
  message: string;
  recoverable: boolean;
  action: "edit" | "restart" | "retry" | "settings";
};

const DEFAULT_CLOUD_ERROR: CloudErrorPresentation = {
  code: "cloud_unavailable",
  message: "云端服务暂不可用，请稍后重试。",
  recoverable: true,
  action: "retry"
};

const CLOUD_ERROR_PRESENTATIONS = new Map<string, CloudErrorPresentation>([
  ["请求内容无效，请检查后重试。", { code: "request_invalid", message: "请求内容无效，请检查后重试。", recoverable: false, action: "edit" }],
  ["安装身份已失效，请重新打开应用。", { code: "installation_unauthorized", message: "安装身份已失效，请重新打开应用。", recoverable: false, action: "restart" }],
  ["今日免费额度已用完，可明天再试或使用自备 Provider。", { code: "quota_exhausted", message: "今日免费额度已用完，可明天再试或使用自备 Provider。", recoverable: false, action: "settings" }],
  ["输入内容过长，请缩短后重试。", { code: "quota_input_too_large", message: "输入内容过长，请缩短后重试。", recoverable: false, action: "edit" }],
  ["免费额度服务暂时不可用，请稍后再试。", { code: "quota_unavailable", message: "免费额度服务暂时不可用，请稍后再试。", recoverable: true, action: "retry" }],
  ["当前网络请求过于频繁，请稍后再试。", { code: "ip_rate_limited", message: "当前网络请求过于频繁，请稍后再试。", recoverable: true, action: "retry" }],
  ["网络限流服务暂时不可用，请稍后再试。", { code: "ip_quota_unavailable", message: "网络限流服务暂时不可用，请稍后再试。", recoverable: true, action: "retry" }],
  ["今日云端请求额度已用完，请明天再试或切换到自备 Provider。", { code: "global_request_budget_exhausted", message: "今日云端请求额度已用完，请明天再试或切换到自备 Provider。", recoverable: false, action: "settings" }],
  ["今日云端服务预算已用完，请稍后再试或切换到自备 Provider。", { code: "global_cost_budget_exhausted", message: "今日云端服务预算已用完，请稍后再试或切换到自备 Provider。", recoverable: false, action: "settings" }],
  ["云端计费配置暂不可用，请稍后再试。", { code: "budget_pricing_unconfigured", message: "云端计费配置暂不可用，请稍后再试。", recoverable: true, action: "retry" }],
  ["云端预算服务暂时不可用，请稍后再试。", { code: "budget_unavailable", message: "云端预算服务暂时不可用，请稍后再试。", recoverable: true, action: "retry" }],
  ["云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。", { code: "cloud_provider_unconfigured", message: "云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。", recoverable: false, action: "settings" }],
  ["云端当前繁忙，请稍后重试。", { code: "cloud_capacity_reached", message: "云端当前繁忙，请稍后重试。", recoverable: true, action: "retry" }],
  ["当前安装已有请求处理中，请等待完成。", { code: "installation_concurrency_reached", message: "当前安装已有请求处理中，请等待完成。", recoverable: true, action: "retry" }],
  ["该请求正在处理中，请勿重复提交。", { code: "optimize_request_conflict", message: "该请求正在处理中，请勿重复提交。", recoverable: true, action: "retry" }],
  ["请先在隐私设置中开启对应的数据改进授权。", { code: "consent_required", message: "请先在隐私设置中开启对应的数据改进授权。", recoverable: false, action: "settings" }],
  ["隐私授权版本已更新，请刷新授权设置后再提交。", { code: "consent_outdated", message: "隐私授权版本已更新，请刷新授权设置后再提交。", recoverable: false, action: "settings" }],
  ["云端免费额度已用完或请求过于频繁。", { code: "cloud_rate_limited", message: "云端免费额度已用完或请求过于频繁。", recoverable: true, action: "retry" }],
  ["云端服务返回了无效数据。", { code: "cloud_protocol_invalid", message: "云端服务返回了无效数据。", recoverable: true, action: "retry" }]
]);

const CLOUD_CODE_PRESENTATIONS = new Map<string, CloudErrorPresentation>(
  [...CLOUD_ERROR_PRESENTATIONS.values()].map((presentation) => [presentation.code, presentation])
);

const CLOUD_STREAM_ERROR_PRESENTATIONS = new Map<string, CloudErrorPresentation>([
  ["invalid_input", { code: "invalid_input", message: "输入内容无效，请检查后重试。", recoverable: false, action: "edit" }],
  ["template_render_error", { code: "template_render_error", message: "生成方案准备失败，请稍后重试。", recoverable: false, action: "retry" }],
  ["empty_result", { code: "empty_result", message: "模型没有返回可用内容，请重试。", recoverable: true, action: "retry" }],
  ["output_too_large", { code: "output_too_large", message: "模型输出超过允许长度，请缩短输入后重试。", recoverable: false, action: "edit" }],
  ["request_timeout", { code: "request_timeout", message: "模型响应超时，请稍后重试。", recoverable: true, action: "retry" }],
  ["provider_unconfigured", { code: "provider_unconfigured", message: "请先在设置中配置当前 Provider。", recoverable: false, action: "settings" }],
  ["provider_invalid_response", { code: "provider_invalid_response", message: "模型服务返回了无效结果，请重试。", recoverable: true, action: "retry" }],
  ["provider_auth_failed", { code: "provider_auth_failed", message: "Provider 认证失败，请检查 API Key。", recoverable: false, action: "settings" }],
  ["provider_authentication_failed", { code: "provider_authentication_failed", message: "Provider 认证失败，请检查 API Key。", recoverable: false, action: "settings" }],
  ["provider_rate_limited", { code: "provider_rate_limited", message: "Provider 请求较多，请稍后重试。", recoverable: true, action: "retry" }],
  ["provider_timeout", { code: "provider_timeout", message: "模型服务响应超时，请重试。", recoverable: true, action: "retry" }],
  ["provider_network_error", { code: "provider_network_error", message: "模型服务网络连接失败，请重试。", recoverable: true, action: "retry" }],
  ["provider_service_error", { code: "provider_service_error", message: "模型服务暂不可用，请稍后重试。", recoverable: true, action: "retry" }],
  ["provider_unavailable", { code: "provider_unavailable", message: "模型服务暂不可用，请稍后重试。", recoverable: true, action: "retry" }],
  ["provider_empty_response", { code: "provider_empty_response", message: "模型没有返回可用内容，请重试。", recoverable: true, action: "retry" }],
  ["provider_error", { code: "provider_error", message: "模型服务请求失败，请稍后重试。", recoverable: true, action: "retry" }]
]);

function cloudErrorPresentation(error: unknown): CloudErrorPresentation {
  if (isRecord(error) && typeof error.code === "string") {
    return CLOUD_CODE_PRESENTATIONS.get(error.code) ?? CLOUD_STREAM_ERROR_PRESENTATIONS.get(error.code) ?? DEFAULT_CLOUD_ERROR;
  }
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : isRecord(error) && typeof error.message === "string"
          ? error.message
          : "";
  return CLOUD_ERROR_PRESENTATIONS.get(message) ?? DEFAULT_CLOUD_ERROR;
}

function cloudStreamErrorPresentation(data: Record<string, unknown>): CloudErrorPresentation {
  const code = typeof data.code === "string" ? data.code : "";
  return CLOUD_STREAM_ERROR_PRESENTATIONS.get(code) ?? DEFAULT_CLOUD_ERROR;
}

function presentCloudEvent(event: CoreEvent): CoreEvent {
  if (event.type === "error") {
    return { ...event, data: cloudStreamErrorPresentation(event.data) };
  }
  if (event.type !== "request" && event.type !== "done") return event;
  return {
    ...event,
    data: { ...event.data, provider: "reflex-cloud" }
  };
}

function createAsyncEventQueue() {
  const values: CoreEvent[] = [];
  const waiters: Array<(item: IteratorResult<CoreEvent>) => void> = [];
  let closed = false;

  return {
    push(value: CoreEvent) {
      if (closed) return;
      const waiter = waiters.shift();
      if (waiter) {
        waiter({ done: false, value });
        return;
      }
      values.push(value);
    },
    close() {
      if (closed) return;
      closed = true;
      while (waiters.length > 0) {
        waiters.shift()?.({ done: true, value: undefined });
      }
    },
    next(): Promise<IteratorResult<CoreEvent>> {
      const value = values.shift();
      if (value) {
        return Promise.resolve({ done: false, value });
      }
      if (closed) {
        return Promise.resolve({ done: true, value: undefined });
      }
      return new Promise((resolve) => waiters.push(resolve));
    }
  };
}
