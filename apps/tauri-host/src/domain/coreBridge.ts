import { streamMockOptimization } from "./mockCore";
import type { CoreEvent, OptimizeRequestDraft } from "./reflexSession";

export type OptimizeRunOptions = {
  signal?: AbortSignal;
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
  return payload
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => toCoreEvent(JSON.parse(line)));
}

function toCoreEvent(value: unknown): CoreEvent {
  if (!isRecord(value)) {
    throw new Error("Core event must be an object");
  }
  const eventCandidate = isRecord(value.event) ? value.event : value;
  if (!isRecord(eventCandidate)) {
    throw new Error("Core event must be an object");
  }
  if (!isCoreEventType(eventCandidate.type)) {
    throw new Error("Unknown Core event type");
  }
  return {
    type: eventCandidate.type,
    data: isRecord(eventCandidate.data) ? eventCandidate.data : {}
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
