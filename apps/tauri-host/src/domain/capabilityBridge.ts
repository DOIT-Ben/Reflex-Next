import type { TauriHostApi } from "./coreBridge";

export const CAPABILITY_UNAVAILABLE_MESSAGE = "插件能力暂不可用，请稍后重试。";
const DEFAULT_LIST_TIMEOUT_MS = 10_000;
const DEFAULT_PLUGIN_TIMEOUT_MS = 10_000;
const LISTENER_SETUP_TIMEOUT_MS = 5_000;

export type PluginKind = "storage" | "transformer" | "command";
export type PluginState =
  | "available"
  | "disabled"
  | "absent"
  | "read_only"
  | "writable"
  | "private"
  | "unavailable";

export type CapabilityDescriptor = {
  id: string;
  name: string;
  version: string;
  kind: PluginKind;
  permissions: string[];
  public_operations: string[];
  enabled: boolean;
  state: PluginState;
  error_code?: string;
};

export type CapabilityListEnvelope = {
  version: 1;
  request_id: string;
  type: "capability_list";
  plugins: CapabilityDescriptor[];
};

export type PluginEventStatus =
  | "started"
  | "chunk"
  | "progress"
  | "result"
  | "cancelled"
  | "error";

export type PluginEventEnvelope = {
  version: 1;
  request_id: string;
  type: "plugin_event";
  plugin_id: string;
  operation: string;
  status: PluginEventStatus;
  data: Record<string, unknown>;
  code?: string;
};

type BridgeOptions = {
  requestIdFactory?: () => string;
};

export class CapabilityBridge {
  private readonly requestIdFactory: () => string;

  constructor(
    private readonly host: TauriHostApi,
    options: BridgeOptions = {}
  ) {
    this.requestIdFactory = options.requestIdFactory ?? createRequestId;
  }

  async listPlugins(
    options: { signal?: AbortSignal; timeoutMs?: number } = {}
  ): Promise<CapabilityDescriptor[]> {
    const requestId = this.requestIdFactory();
    let unlisten: (() => void) | undefined;
    let settled = false;
    let completed = false;
    let commandDispatched = false;
    let cancellationSent = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let failListRequest: (() => void) | undefined;
    const timeoutMs =
      typeof options.timeoutMs === "number" &&
      Number.isFinite(options.timeoutMs) &&
      options.timeoutMs > 0
        ? options.timeoutMs
        : DEFAULT_LIST_TIMEOUT_MS;

    const cancelRequest = () => {
      if (!commandDispatched || cancellationSent || completed) return;
      cancellationSent = true;
      try {
        void this.host
          .invoke("runtime_plugin_cancel", {
            command: createPluginCancelCommand(requestId)
          })
          .catch(() => undefined);
      } catch {
        // The fixed bridge error remains the only caller-visible failure.
      }
    };

    try {
      let resolveResult!: (plugins: CapabilityDescriptor[]) => void;
      let rejectResult!: (error: Error) => void;
      const result = new Promise<CapabilityDescriptor[]>((resolve, reject) => {
        resolveResult = resolve;
        rejectResult = reject;
      });
      unlisten = await listenWithTimeout(this.host.listen<unknown>(
        "reflex://capability-list",
        (event) => {
          if (settled || !isRecord(event.payload)) return;
          if (event.payload.request_id !== requestId) return;
          try {
            const envelope = parseCapabilityListEnvelope(event.payload);
            settled = true;
            completed = true;
            resolveResult(envelope.plugins);
          } catch {
            settled = true;
            rejectResult(createSafeError());
          }
        }
      ), LISTENER_SETUP_TIMEOUT_MS);
      failListRequest = () => {
        if (settled) return;
        settled = true;
        rejectResult(createSafeError());
      };
      if (options.signal?.aborted) {
        failListRequest();
      } else {
        options.signal?.addEventListener("abort", failListRequest, { once: true });
      }
      timeout = setTimeout(failListRequest, timeoutMs);
      if (settled) return await result;
      commandDispatched = true;
      void this.host
        .invoke("runtime_list_plugins", {
          command: createListPluginsCommand(requestId)
        })
        .catch(() => failListRequest?.());
      return await result;
    } catch {
      cancelRequest();
      throw createSafeError();
    } finally {
      if (timeout !== undefined) clearTimeout(timeout);
      if (failListRequest) {
        options.signal?.removeEventListener("abort", failListRequest);
      }
      try {
        unlisten?.();
      } catch {
        // Cleanup failures are not exposed to the UI.
      }
    }
  }

  async *invoke(
    pluginId: string,
    operation: string,
    input: Record<string, unknown>,
    options: { signal?: AbortSignal; timeoutMs?: number } = {}
  ): AsyncGenerator<PluginEventEnvelope> {
    const requestId = this.requestIdFactory();
    const queue = createAsyncQueue<PluginEventEnvelope>();
    let unlisten: (() => void) | undefined;
    let finished = false;
    let terminalSeen = false;
    let commandDispatched = false;
    let cancellationSent = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const timeoutMs =
      typeof options.timeoutMs === "number" &&
      Number.isFinite(options.timeoutMs) &&
      options.timeoutMs > 0
        ? options.timeoutMs
        : DEFAULT_PLUGIN_TIMEOUT_MS;

    const requestCancel = (): void => {
      if (!commandDispatched || terminalSeen || cancellationSent) return;
      cancellationSent = true;
      try {
        void this.host
          .invoke("runtime_plugin_cancel", {
            command: createPluginCancelCommand(requestId)
          })
          .catch(() => undefined);
      } catch {
        // Cancellation failures never replace the fixed bridge error.
      }
    };

    const clearResponseTimeout = () => {
      if (timeout === undefined) return;
      clearTimeout(timeout);
      timeout = undefined;
    };

    const failRequest = () => {
      if (finished || terminalSeen) return;
      finished = true;
      clearResponseTimeout();
      queue.cancel(createSafeError());
      requestCancel();
    };

    const armResponseTimeout = () => {
      clearResponseTimeout();
      if (!finished && !terminalSeen) {
        timeout = setTimeout(failRequest, timeoutMs);
      }
    };

    const abort = () => failRequest();

    try {
      unlisten = await listenWithTimeout(this.host.listen<unknown>("reflex://plugin-event", (event) => {
        if (finished || !isRecord(event.payload)) return;
        if (
          event.payload.request_id !== requestId ||
          event.payload.plugin_id !== pluginId ||
          event.payload.operation !== operation
        ) {
          return;
        }
        try {
          const parsed = parsePluginEventEnvelope(event.payload);
          const terminal = isTerminalStatus(parsed.status);
          if (terminal) {
            terminalSeen = true;
            finished = true;
            clearResponseTimeout();
          } else {
            armResponseTimeout();
          }
          queue.push(parsed);
          if (terminal) {
            queue.close();
          }
        } catch {
          failRequest();
        }
      }), LISTENER_SETUP_TIMEOUT_MS);

      if (options.signal?.aborted) {
        failRequest();
      } else {
        options.signal?.addEventListener("abort", abort, { once: true });
      }
      armResponseTimeout();
      if (!finished) {
        commandDispatched = true;
        try {
          void this.host
            .invoke("runtime_plugin_call", {
              command: createPluginCallCommand(requestId, pluginId, operation, input)
            })
            .catch(() => failRequest());
        } catch {
          failRequest();
        }
      }

      while (true) {
        const item = await queue.next();
        if (item.done) return;
        yield item.value;
      }
    } catch {
      throw createSafeError();
    } finally {
      clearResponseTimeout();
      options.signal?.removeEventListener("abort", abort);
      try {
        unlisten?.();
      } catch {
        // Cleanup failures are not exposed to the UI.
      }
      if (commandDispatched && !terminalSeen) {
        requestCancel();
      }
    }
  }
}

export function createListPluginsCommand(requestId: string) {
  return {
    version: 1 as const,
    request_id: requestId,
    type: "list_plugins" as const,
    payload: {}
  };
}

export function createPluginCallCommand(
  requestId: string,
  pluginId: string,
  operation: string,
  input: Record<string, unknown>
) {
  return {
    version: 1 as const,
    request_id: requestId,
    type: "plugin_call" as const,
    payload: { plugin_id: pluginId, operation, input }
  };
}

export function createPluginCancelCommand(requestId: string) {
  return {
    version: 1 as const,
    request_id: requestId,
    type: "cancel" as const,
    payload: {}
  };
}

function parseCapabilityListEnvelope(value: Record<string, unknown>): CapabilityListEnvelope {
  if (
    !hasExactKeys(value, ["version", "request_id", "type", "plugins"]) ||
    value.version !== 1 ||
    value.type !== "capability_list" ||
    !isSafeRequestId(value.request_id) ||
    !Array.isArray(value.plugins)
  ) {
    throw createSafeError();
  }
  const plugins = value.plugins.map(parseDescriptor);
  return {
    version: 1,
    request_id: value.request_id,
    type: "capability_list",
    plugins
  };
}

function parseDescriptor(value: unknown): CapabilityDescriptor {
  if (!isRecord(value)) throw createSafeError();
  const state = value.state;
  const unavailable = state === "unavailable";
  const keys = unavailable
    ? [
        "id",
        "name",
        "version",
        "kind",
        "permissions",
        "public_operations",
        "enabled",
        "state",
        "error_code"
      ]
    : [
        "id",
        "name",
        "version",
        "kind",
        "permissions",
        "public_operations",
        "enabled",
        "state"
      ];
  if (
    !hasExactKeys(value, keys) ||
    !isSafeId(value.id) ||
    typeof value.name !== "string" ||
    !value.name.trim() ||
    typeof value.version !== "string" ||
    !value.version.trim() ||
    !isPluginKind(value.kind) ||
    !isSafeIdArray(value.permissions) ||
    !isSafeIdArray(value.public_operations) ||
    typeof value.enabled !== "boolean" ||
    !isPluginState(state)
  ) {
    throw createSafeError();
  }
  if (unavailable ? !isSafeId(value.error_code) : value.error_code !== undefined) {
    throw createSafeError();
  }
  const descriptor: CapabilityDescriptor = {
    id: value.id,
    name: value.name,
    version: value.version,
    kind: value.kind,
    permissions: value.permissions,
    public_operations: value.public_operations,
    enabled: value.enabled,
    state
  };
  if (unavailable) descriptor.error_code = value.error_code;
  return descriptor;
}

function parsePluginEventEnvelope(value: Record<string, unknown>): PluginEventEnvelope {
  const status = value.status;
  const error = status === "error";
  const keys = error
    ? [
        "version",
        "request_id",
        "type",
        "plugin_id",
        "operation",
        "status",
        "data",
        "code"
      ]
    : [
        "version",
        "request_id",
        "type",
        "plugin_id",
        "operation",
        "status",
        "data"
      ];
  if (
    !hasExactKeys(value, keys) ||
    value.version !== 1 ||
    value.type !== "plugin_event" ||
    !isSafeRequestId(value.request_id) ||
    !isSafeId(value.plugin_id) ||
    !isSafeId(value.operation) ||
    !isPluginEventStatus(status) ||
    !isRecord(value.data) ||
    !isSafePluginData(value.data)
  ) {
    throw createSafeError();
  }
  if (error ? !isSafeId(value.code) || Object.keys(value.data).length !== 0 : value.code !== undefined) {
    throw createSafeError();
  }
  const event: PluginEventEnvelope = {
    version: 1,
    request_id: value.request_id,
    type: "plugin_event",
    plugin_id: value.plugin_id,
    operation: value.operation,
    status,
    data: value.data
  };
  if (error) event.code = value.code;
  return event;
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => key in value);
}

function isSafeId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 64 &&
    /^[a-z][a-z0-9_-]*$/.test(value)
  );
}

function isSafeRequestId(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 128 && /^[A-Za-z0-9_.:-]+$/.test(value);
}

function isSafeIdArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isSafeId) && new Set(value).size === value.length;
}

function isSafePluginData(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (Array.isArray(value)) return value.every(isSafePluginData);
  if (!isRecord(value)) return false;
  return Object.entries(value).every(
    ([key, item]) =>
      key.length >= 1 &&
      key.length <= 128 &&
      !Array.from(key).some((character) => character < " ") &&
      isSafePluginData(item)
  );
}

function isPluginKind(value: unknown): value is PluginKind {
  return value === "storage" || value === "transformer" || value === "command";
}

function isPluginState(value: unknown): value is PluginState {
  return (
    value === "available" ||
    value === "disabled" ||
    value === "absent" ||
    value === "read_only" ||
    value === "writable" ||
    value === "private" ||
    value === "unavailable"
  );
}

function isPluginEventStatus(value: unknown): value is PluginEventStatus {
  return (
    value === "started" ||
    value === "chunk" ||
    value === "progress" ||
    value === "result" ||
    value === "cancelled" ||
    value === "error"
  );
}

function isTerminalStatus(value: PluginEventStatus): boolean {
  return value === "result" || value === "error" || value === "cancelled";
}

function createSafeError(): Error {
  return new Error(CAPABILITY_UNAVAILABLE_MESSAGE);
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
          try { unlisten(); } catch { /* Best-effort late cleanup. */ }
          return;
        }
        settled = true;
        finish();
        resolve(unlisten);
      },
      (error) => {
        if (settled) return;
        settled = true;
        finish();
        reject(error);
      }
    );
  });
}

function createRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `plugin-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function createAsyncQueue<T>() {
  const values: T[] = [];
  const waiters: Array<{
    resolve: (item: IteratorResult<T>) => void;
    reject: (reason: unknown) => void;
  }> = [];
  let closed = false;
  let failure: Error | undefined;

  return {
    push(value: T) {
      if (closed) return;
      const waiter = waiters.shift();
      if (waiter) {
        waiter.resolve({ done: false, value });
      } else {
        values.push(value);
      }
    },
    close() {
      if (closed) return;
      closed = true;
      while (waiters.length > 0) {
        waiters.shift()?.resolve({ done: true, value: undefined });
      }
    },
    cancel(error: Error) {
      if (closed) return;
      values.length = 0;
      failure = error;
      closed = true;
      while (waiters.length > 0) {
        waiters.shift()?.reject(error);
      }
    },
    next(): Promise<IteratorResult<T>> {
      if (failure) return Promise.reject(failure);
      const value = values.shift();
      if (value !== undefined) return Promise.resolve({ done: false, value });
      if (closed) return Promise.resolve({ done: true, value: undefined });
      return new Promise((resolve, reject) => waiters.push({ resolve, reject }));
    }
  };
}
