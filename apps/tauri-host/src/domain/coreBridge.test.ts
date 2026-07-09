import { describe, expect, it } from "vitest";
import {
  createCancelCommand,
  createDefaultCoreBridge,
  createOptimizeCommand,
  parseNdjsonEnvelopes,
  parseNdjsonEvents,
  selectEventsForRequest,
  TauriRuntimeBridge,
  type CoreEventEnvelope,
  type TauriEvent
} from "./coreBridge";
import { createDraftRequest } from "./reflexSession";

describe("core bridge", () => {
  it("parses sidecar NDJSON into CoreEvent objects", () => {
    const events = parseNdjsonEvents(
      [
        '{"version":1,"request_id":"req-1","event":{"type":"status","data":{"message":"正在分析场景"}}}',
        '{"version":1,"request_id":"req-1","event":{"type":"done","data":{"text":"优化结果","scene":"email"}}}'
      ].join("\n")
    );

    expect(events).toEqual([
      { type: "status", data: { message: "正在分析场景" } },
      { type: "done", data: { text: "优化结果", scene: "email" } }
    ]);
  });

  it("keeps compatibility with bare CoreEvent lines during frontend-only previews", () => {
    expect(parseNdjsonEvents('{"type":"chunk","data":{"text":"片段"}}')).toEqual([
      { type: "chunk", data: { text: "片段" } }
    ]);
  });

  it("rejects unknown event types from a host bridge", () => {
    expect(() => parseNdjsonEvents('{"type":"debug","data":{}}')).toThrow(
      "Unknown Core event type"
    );
  });

  it("creates Runtime optimize and cancel command envelopes", () => {
    const request = {
      ...createDraftRequest("写一封邮件"),
      style: "concise" as const,
      provider: "minimax"
    };

    expect(createOptimizeCommand("req-1", request)).toEqual({
      version: 1,
      request_id: "req-1",
      type: "optimize",
      payload: request
    });
    expect(createCancelCommand("req-1")).toEqual({
      version: 1,
      request_id: "req-1",
      type: "cancel",
      payload: {}
    });
  });

  it("creates a Tauri runtime bridge when a host api is available", () => {
    const host = {
      invoke: async () => undefined,
      listen: async () => () => undefined
    };

    expect(createDefaultCoreBridge(host)).toBeInstanceOf(TauriRuntimeBridge);
  });

  it("filters stale Runtime events by active request id", () => {
    const envelopes = parseNdjsonEnvelopes(
      [
        '{"version":1,"request_id":"old","event":{"type":"chunk","data":{"text":"旧结果"}}}',
        '{"version":1,"request_id":"active","event":{"type":"chunk","data":{"text":"新结果"}}}'
      ].join("\n")
    );

    expect(selectEventsForRequest(envelopes, "active")).toEqual([
      { type: "chunk", data: { text: "新结果" } }
    ]);
  });

  it("sends optimize through Tauri invoke and yields only matching request events", async () => {
    let listener: ((event: TauriEvent<CoreEventEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const invoked: Array<{ command: string; args: unknown }> = [];
    const request = createDraftRequest("写一封邮件");
    const host = {
      invoke: async (command: string, args: unknown) => {
        invoked.push({ command, args });
        queueMicrotask(() => {
          listener?.({
            payload: {
              version: 1,
              request_id: "old",
              event: { type: "chunk", data: { text: "旧结果" } }
            }
          });
          listener?.({
            payload: {
              version: 1,
              request_id: "req-tauri",
              event: { type: "status", data: { message: "正在分析场景" } }
            }
          });
          listener?.({
            payload: {
              version: 1,
              request_id: "req-tauri",
              event: { type: "done", data: { text: "完成" } }
            }
          });
        });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => {
          unlistenCalled = true;
        };
      }
    };
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-tauri" });

    const events = [];
    for await (const event of bridge.optimize(request)) {
      events.push(event);
    }

    expect(invoked).toEqual([
      {
        command: "runtime_optimize",
        args: { command: createOptimizeCommand("req-tauri", request) }
      }
    ]);
    expect(events).toEqual([
      { type: "status", data: { message: "正在分析场景" } },
      { type: "done", data: { text: "完成" } }
    ]);
    expect(unlistenCalled).toBe(true);
  });

  it("sends cancel through Tauri invoke when an active run is aborted", async () => {
    let listener: ((event: TauriEvent<CoreEventEnvelope>) => void) | null = null;
    const invoked: Array<{ command: string; args: unknown }> = [];
    const request = createDraftRequest("写一封邮件");
    const controller = new AbortController();
    const host = {
      invoke: async (command: string, args: unknown) => {
        invoked.push({ command, args });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    };
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-cancel" });
    const iterator = bridge.optimize(request, { signal: controller.signal });

    const pending = iterator.next();
    await Promise.resolve();
    expect(listener).not.toBeNull();
    controller.abort();
    const result = await pending;

    expect(result.done).toBe(true);
    expect(invoked).toEqual([
      {
        command: "runtime_optimize",
        args: { command: createOptimizeCommand("req-cancel", request) }
      },
      {
        command: "runtime_cancel",
        args: { command: createCancelCommand("req-cancel") }
      }
    ]);
  });
});
