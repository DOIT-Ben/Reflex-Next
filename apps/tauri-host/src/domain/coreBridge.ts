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

export class TauriRuntimeBridge implements CoreBridge {
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
        .invoke("runtime_cancel", { command: createCancelCommand(requestId) })
        .finally(() => queue.close());
    };

    try {
      unlisten = await this.host.listen<CoreEventEnvelope>(
        "reflex://core-event",
        ({ payload }) => {
          if (payload.request_id !== requestId) return;
          queue.push(payload.event);
          if (payload.event.type === "done" || payload.event.type === "error") {
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

export async function createDefaultCoreBridge(host?: TauriHostApi | null): Promise<CoreBridge> {
  if (!host) {
    return new DemoCoreBridge();
  }

  try {
    await host.invoke("runtime_available");
  } catch {}

  return new TauriRuntimeBridge(host);
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
