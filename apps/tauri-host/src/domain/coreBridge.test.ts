import { describe, expect, it } from "vitest";
import {
  createCancelCommand,
  createDefaultCoreBridge,
  createOptimizeCommand,
  DemoCoreBridge,
  parseNdjsonEnvelopes,
  parseNdjsonEvents,
  selectEventsForRequest,
  RoutedCoreBridge,
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

  it("never falls back to demo output when a Tauri Runtime probe returns false", async () => {
    const calls: string[] = [];
    const host = {
      invoke: async (command: string) => {
        calls.push(command);
        return false;
      },
      listen: async () => () => undefined
    };

    const bridge = await createDefaultCoreBridge(host);

    expect(bridge).toBeInstanceOf(TauriRuntimeBridge);
    expect(calls).toEqual(["runtime_available"]);
  });

  it("creates a Tauri runtime bridge only when runtime_available returns true", async () => {
    const host = {
      invoke: async () => true,
      listen: async () => () => undefined
    };

    const bridge = await createDefaultCoreBridge(host);

    expect(bridge).toBeInstanceOf(TauriRuntimeBridge);
  });

  it("never falls back to demo output when a Tauri Runtime probe rejects", async () => {
    const host = {
      invoke: async () => {
        throw new Error("probe failed");
      },
      listen: async () => () => undefined
    };

    const bridge = await createDefaultCoreBridge(host);

    expect(bridge).toBeInstanceOf(TauriRuntimeBridge);
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
          listener?.({
            payload: {
              version: 1,
              request_id: "req-tauri",
              event: { type: "metric", data: { save_status: "saved", history_id: "history-1" } }
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
      { type: "done", data: { text: "完成" } },
      { type: "metric", data: { save_status: "saved", history_id: "history-1" } }
    ]);
    expect(unlistenCalled).toBe(true);
  });

  it("routes Reflex Cloud requests through authenticated cloud commands only", async () => {
    let listener: ((event: TauriEvent<CoreEventEnvelope>) => void) | null = null;
    const invoked: Array<{ command: string; args: unknown }> = [];
    const host = {
      invoke: async (command: string, args: unknown) => {
        invoked.push({ command, args });
        if (command !== "cloud_optimize") return;
        queueMicrotask(() => {
          for (const event of [
            { type: "request", data: { provider: "minimax", model: "MiniMax-M2.7-highspeed" } },
            { type: "chunk", data: { text: "云端" } },
            { type: "done", data: { text: "云端结果", scene: "general", provider: "minimax", model: "MiniMax-M2.7-highspeed" } },
            { type: "metric", data: { elapsed_seconds: 0.2 } }
          ] as const) {
            listener?.({ payload: { version: 1, request_id: "req-cloud", event } });
          }
        });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    };
    const bridge = new RoutedCoreBridge(host, { requestIdFactory: () => "req-cloud" });
    const request = { ...createDraftRequest("云端优化"), provider: "reflex-cloud" };

    const events = [];
    for await (const event of bridge.optimize(request)) events.push(event);

    expect(invoked).toHaveLength(1);
    expect(invoked[0]).toMatchObject({
      command: "cloud_optimize",
      args: { payload: { request_id: "req-cloud", text: "云端优化" } }
    });
    expect(events.map((event) => event.type)).toEqual(["request", "chunk", "done", "metric"]);
    expect(events[0].data).toMatchObject({ provider: "reflex-cloud", model: "MiniMax-M2.7-highspeed" });
    expect(events[2].data).toMatchObject({ provider: "reflex-cloud", model: "MiniMax-M2.7-highspeed" });
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

  it("turns Runtime launch failures into one safe recoverable error event", async () => {
    let unlistenCalled = false;
    const host = {
      invoke: async (command: string) => {
        if (command === "runtime_optimize") {
          throw new Error("uv failed with api_key=secret-value");
        }
      },
      listen: async () => () => {
        unlistenCalled = true;
      }
    };
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-error" });

    const events = [];
    for await (const event of bridge.optimize(createDraftRequest("写一封邮件"))) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "runtime_unavailable",
          message: "运行服务暂不可用，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
    expect(JSON.stringify(events)).not.toContain("secret-value");
    expect(unlistenCalled).toBe(true);
  });

  it("turns Runtime listener failures into one safe recoverable error event", async () => {
    const host = {
      invoke: async () => undefined,
      listen: async () => {
        throw new Error("listener failed with token=secret-value");
      }
    };
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-listener" });

    const events = [];
    for await (const event of bridge.optimize(createDraftRequest("写一封邮件"))) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "runtime_unavailable",
          message: "运行服务暂不可用，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
    expect(JSON.stringify(events)).not.toContain("secret-value");
  });
});
