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

export function createDefaultCoreBridge(): CoreBridge {
  return new DemoCoreBridge();
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
