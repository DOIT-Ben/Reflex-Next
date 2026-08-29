import { describe, expect, it, vi } from "vitest";
import {
  createCancelCommand,
  createDefaultCoreBridge,
  CloudCoreBridge,
  createOptimizeCommand,
  isSuccessfulCompletionEvent,
  parseNdjsonEnvelopes,
  parseNdjsonEvents,
  selectEventsForRequest,
  RoutedCoreBridge,
  TauriRuntimeBridge,
  UnavailableCoreBridge,
  type CoreEventEnvelope,
  type TauriEvent
} from "./coreBridge";
import { createDraftRequest } from "./reflexSession";
import { createTauriHostStub } from "./testHost";

describe("core bridge", () => {
  it("treats only a result event as successful completion", () => {
    expect(isSuccessfulCompletionEvent({ type: "done", data: {} })).toBe(true);
    expect(isSuccessfulCompletionEvent({ type: "status", data: { phase: "completed" } })).toBe(false);
    expect(isSuccessfulCompletionEvent({ type: "status", data: { phase: "streaming" } })).toBe(false);
  });

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
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        calls.push(command);
        return false;
      },
      listen: async () => () => undefined
    });

    const initialized = await createDefaultCoreBridge(host);
    const events = [];
    for await (const event of initialized.bridge.optimize(createDraftRequest("本地请求"))) {
      events.push(event);
    }

    expect(initialized.bridge).toBeInstanceOf(TauriRuntimeBridge);
    expect(initialized.runtimeAvailable).toBe(false);
    expect(calls).toEqual(["runtime_available"]);
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
  });

  it("creates a Tauri runtime bridge only when runtime_available returns true", async () => {
    const host = createTauriHostStub({
      invoke: async () => true,
      listen: async () => () => undefined
    });

    const initialized = await createDefaultCoreBridge(host);

    expect(initialized.bridge).toBeInstanceOf(TauriRuntimeBridge);
    expect(initialized.runtimeAvailable).toBe(true);
  });

  it("never falls back to demo output when a Tauri Runtime probe rejects", async () => {
    const host = createTauriHostStub({
      invoke: async () => {
        throw new Error("probe failed");
      },
      listen: async () => () => undefined
    });

    const initialized = await createDefaultCoreBridge(host);
    const events = [];
    for await (const event of initialized.bridge.optimize(createDraftRequest("本地请求"))) {
      events.push(event);
    }

    expect(initialized.bridge).toBeInstanceOf(TauriRuntimeBridge);
    expect(initialized.runtimeAvailable).toBe(false);
    expect(events.map((event) => event.type)).toEqual(["error"]);
  });

  it("uses an unavailable bridge when no Tauri host exists", async () => {
    const initialized = await createDefaultCoreBridge(null);
    const events = [];
    for await (const event of initialized.bridge.optimize(createDraftRequest("生产请求"))) {
      events.push(event);
    }

    expect(initialized.bridge).toBeInstanceOf(UnavailableCoreBridge);
    expect(initialized.runtimeAvailable).toBe(false);
    expect(events.map((event) => event.type)).toEqual(["error"]);
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
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    let unlistenCalled = false;
    const invoked: Array<{ command: string; args: unknown }> = [];
    const request = createDraftRequest("写一封邮件");
    const host = createTauriHostStub({
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
              event: { type: "metric", data: { save_status: "saved" } }
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
    });
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
      { type: "metric", data: { save_status: "saved" } }
    ]);
    expect(unlistenCalled).toBe(true);
  });

  it("closes a done-only Runtime stream after a bounded fallback", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const host = createTauriHostStub({
      invoke: async () => {
        queueMicrotask(() => {
          listener?.({
            payload: {
              version: 1,
              request_id: "req-done-only",
              event: { type: "done", data: { text: "完成" } }
            }
          });
        });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-done-only" });

    vi.useFakeTimers();
    const events: Array<{ type: string; data: Record<string, unknown> }> = [];
    try {
      const run = (async () => {
        for await (const event of bridge.optimize(createDraftRequest("只返回结果"))) {
          events.push(event);
        }
      })();
      await vi.runAllTimersAsync();
      await run;
    } finally {
      vi.useRealTimers();
    }

    expect(events).toEqual([{ type: "done", data: { text: "完成" } }]);
  });

  it("keeps a metric that arrives after the old short completion window", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const host = createTauriHostStub({
      invoke: async () => {
        queueMicrotask(() => {
          listener?.({
            payload: {
              version: 1,
              request_id: "req-delayed-metric",
              event: { type: "done", data: { text: "完成" } }
            }
          });
          setTimeout(() => {
            listener?.({
              payload: {
                version: 1,
                request_id: "req-delayed-metric",
                event: { type: "metric", data: { save_status: "saved" } }
              }
            });
          }, 300);
        });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-delayed-metric" });
    const events = [];
    for await (const event of bridge.optimize(createDraftRequest("延迟元数据"))) events.push(event);

    expect(events.map((event) => event.type)).toEqual(["done", "metric"]);
  });

  it("fails a Runtime stream that never emits an event instead of waiting forever", async () => {
    const invoked: Array<{ command: string; args?: unknown }> = [];
    const host = createTauriHostStub({
      invoke: async (command: string, args?: unknown) => {
        invoked.push({ command, args });
        return undefined;
      },
      listen: async () => () => undefined
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-no-events" });

    vi.useFakeTimers();
    const events: Array<{ type: string; data: Record<string, unknown> }> = [];
    try {
      const run = (async () => {
        for await (const event of bridge.optimize(createDraftRequest("无事件"))) {
          events.push(event);
        }
      })();
      await vi.runAllTimersAsync();
      await run;
    } finally {
      vi.useRealTimers();
    }

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "request_timeout",
          message: "模型响应超时，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
    expect(invoked).toEqual([
      { command: "runtime_optimize", args: { command: createOptimizeCommand("req-no-events", createDraftRequest("无事件")) } },
      { command: "runtime_cancel", args: { command: createCancelCommand("req-no-events") } }
    ]);
  });

  it("unblocks when the Runtime invoke itself never settles", async () => {
    const invoked: string[] = [];
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        invoked.push(command);
        if (command === "runtime_optimize") return new Promise<never>(() => undefined);
        return undefined;
      },
      listen: async () => () => undefined
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-hung-invoke" });

    vi.useFakeTimers();
    const events: Array<{ type: string; data: Record<string, unknown> }> = [];
    try {
      const run = (async () => {
        for await (const event of bridge.optimize(createDraftRequest("挂起调用"))) {
          events.push(event);
        }
      })();
      await vi.runAllTimersAsync();
      await run;
    } finally {
      vi.useRealTimers();
    }

    expect(events.map((event) => event.type)).toEqual(["error"]);
    expect(invoked).toEqual(["runtime_optimize", "runtime_cancel"]);
  });

  it("unblocks when a terminal Runtime event arrives before a hanging invoke settles", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        if (command === "runtime_optimize") {
          queueMicrotask(() => {
            listener?.({
              payload: {
                version: 1,
                request_id: "req-terminal-first",
                event: {
                  type: "error",
                  data: {
                    code: "provider_error",
                    message: "模型服务请求失败，请稍后重试。",
                    recoverable: true,
                    action: "retry"
                  }
                }
              }
            });
          });
          return new Promise<never>(() => undefined);
        }
        return undefined;
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-terminal-first" });
    const events = [];

    for await (const event of bridge.optimize(createDraftRequest("先终止"))) events.push(event);

    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("error");
  });

  it("rejects a metric that arrives before the result event", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const host = createTauriHostStub({
      invoke: async () => {
        queueMicrotask(() => {
          listener?.({
            payload: {
              version: 1,
              request_id: "req-metric-first",
              event: { type: "metric", data: { save_status: "saved" } }
            }
          });
        });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-metric-first" });
    const events = [];
    for await (const event of bridge.optimize(createDraftRequest("乱序元数据"))) events.push(event);

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "protocol_invalid",
          message: "生成结果顺序异常，请重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
  });

  it("routes Reflex Cloud requests through authenticated cloud commands only", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const invoked: Array<{ command: string; args: unknown }> = [];
    const host = createTauriHostStub({
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
    });
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

  it("maps only approved Cloud host errors to stable user-facing events", async () => {
    const cases = [
      ["请求内容无效，请检查后重试。", "request_invalid", false, "edit"],
      ["安装身份已失效，请重新打开应用。", "installation_unauthorized", false, "restart"],
      ["今日免费额度已用完，可明天再试或使用自备 Provider。", "quota_exhausted", false, "settings"],
      ["输入内容过长，请缩短后重试。", "quota_input_too_large", false, "edit"],
      ["免费额度服务暂时不可用，请稍后再试。", "quota_unavailable", true, "retry"],
      ["当前网络请求过于频繁，请稍后再试。", "ip_rate_limited", true, "retry"],
      ["网络限流服务暂时不可用，请稍后再试。", "ip_quota_unavailable", true, "retry"],
      ["今日云端请求额度已用完，请明天再试或切换到自备 Provider。", "global_request_budget_exhausted", false, "settings"],
      ["今日云端服务预算已用完，请稍后再试或切换到自备 Provider。", "global_cost_budget_exhausted", false, "settings"],
      ["云端计费配置暂不可用，请稍后再试。", "budget_pricing_unconfigured", true, "retry"],
      ["云端预算服务暂时不可用，请稍后再试。", "budget_unavailable", true, "retry"],
      ["云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。", "cloud_provider_unconfigured", false, "settings"],
      ["云端当前繁忙，请稍后重试。", "cloud_capacity_reached", true, "retry"],
      ["当前安装已有请求处理中，请等待完成。", "installation_concurrency_reached", true, "retry"],
      ["该请求正在处理中，请勿重复提交。", "optimize_request_conflict", true, "retry"],
      ["请先在隐私设置中开启对应的数据改进授权。", "consent_required", false, "settings"],
      ["隐私授权版本已更新，请刷新授权设置后再提交。", "consent_outdated", false, "settings"],
      ["云端免费额度已用完或请求过于频繁。", "cloud_rate_limited", true, "retry"],
      ["云端服务返回了无效数据。", "cloud_protocol_invalid", true, "retry"]
    ] as const;

    for (const [message, code, recoverable, action] of cases) {
      const host = createTauriHostStub({
        invoke: async (command: string) => {
          if (command === "cloud_optimize") throw message;
        },
        listen: async () => () => undefined
      });
      const bridge = new RoutedCoreBridge(host, { requestIdFactory: () => `req-${code}` });
      const events = [];

      for await (const event of bridge.optimize({
        ...createDraftRequest("云端优化"),
        provider: "reflex-cloud"
      })) {
        events.push(event);
      }

      expect(events).toEqual([{ type: "error", data: { code, message, recoverable, action } }]);
    }
  });

  it("redacts unknown Cloud host failures instead of echoing internal details", async () => {
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        if (command === "cloud_optimize") {
          throw new Error("provider failed with api_key=private-value");
        }
      },
      listen: async () => () => undefined
    });
    const bridge = new RoutedCoreBridge(host, { requestIdFactory: () => "req-cloud-error" });
    const events = [];

    for await (const event of bridge.optimize({
      ...createDraftRequest("云端优化"),
      provider: "reflex-cloud"
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "cloud_unavailable",
          message: "云端服务暂不可用，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
    expect(JSON.stringify(events)).not.toContain("private-value");
  });

  it("normalizes Cloud SSE errors and drops untrusted event fields", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        if (command === "cloud_optimize") {
          queueMicrotask(() => {
            listener?.({
              payload: {
                version: 1,
                request_id: "req-cloud-sse-error",
                event: {
                  type: "error",
                  data: {
                    code: "provider_service_error",
                    message: "provider failed api_key=private-value",
                    recoverable: false,
                    action: "ignore",
                    secret: "private-value"
                  }
                }
              }
            });
          });
        }
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new RoutedCoreBridge(host, { requestIdFactory: () => "req-cloud-sse-error" });
    const events = [];

    for await (const event of bridge.optimize({
      ...createDraftRequest("云端优化"),
      provider: "reflex-cloud"
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        type: "error",
        data: {
          code: "provider_service_error",
          message: "模型服务暂不可用，请稍后重试。",
          recoverable: true,
          action: "retry"
        }
      }
    ]);
    expect(JSON.stringify(events)).not.toContain("private-value");
  });

  it("sends cancel through Tauri invoke when an active run is aborted", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const invoked: Array<{ command: string; args: unknown }> = [];
    const request = createDraftRequest("写一封邮件");
    const controller = new AbortController();
    const host = createTauriHostStub({
      invoke: async (command: string, args: unknown) => {
        invoked.push({ command, args });
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
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

  it("does not leak cancel rejection or buffered events after Runtime abort", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    let resolveOptimize: () => void = () => {};
    const controller = new AbortController();
    const host = createTauriHostStub({
      invoke: (command: string) => {
        if (command === "runtime_optimize") {
          return new Promise<void>((resolve) => {
            resolveOptimize = resolve;
          });
        }
        if (command === "runtime_cancel") return Promise.reject(new Error("cancel raced with shutdown"));
        return Promise.resolve();
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new TauriRuntimeBridge(host, { requestIdFactory: () => "req-abort-buffer" });
    const iterator = bridge.optimize(createDraftRequest("写一封邮件"), { signal: controller.signal });
    const pending = iterator.next();
    await Promise.resolve();
    listener?.({
      payload: {
        version: 1,
        request_id: "req-abort-buffer",
        event: { type: "chunk", data: { text: "不应在取消后返回" } }
      }
    });

    controller.abort();
    resolveOptimize?.();

    await expect(pending).resolves.toEqual({ done: true, value: undefined });
    await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });
  });

  it("does not send Cloud cancel after the stream already reached a terminal metric", async () => {
    let listener: (event: TauriEvent<CoreEventEnvelope>) => void = () => {};
    const invoked: string[] = [];
    const controller = new AbortController();
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        invoked.push(command);
        if (command === "cloud_optimize") {
          queueMicrotask(() => {
            for (const event of [
              { type: "done", data: { text: "云端结果" } },
              { type: "metric", data: { save_status: "saved" } }
            ] as const) {
              listener?.({ payload: { version: 1, request_id: "req-cloud-terminal", event } });
            }
          });
        }
      },
      listen: async (_eventName: string, handler: (event: TauriEvent<CoreEventEnvelope>) => void) => {
        listener = handler;
        return () => undefined;
      }
    });
    const bridge = new CloudCoreBridge(host, { requestIdFactory: () => "req-cloud-terminal" });
    const iterator = bridge.optimize(
      { ...createDraftRequest("云端结果"), provider: "reflex-cloud" },
      { signal: controller.signal }
    );

    const events = [];
    for await (const event of iterator) {
      events.push(event);
      if (event.type === "metric") controller.abort();
    }

    expect(events.map((event) => event.type)).toEqual(["done", "metric"]);
    expect(invoked).toEqual(["cloud_optimize"]);
  });

  it("turns Runtime launch failures into one safe recoverable error event", async () => {
    let unlistenCalled = false;
    const host = createTauriHostStub({
      invoke: async (command: string) => {
        if (command === "runtime_optimize") {
          throw new Error("uv failed with api_key=secret-value");
        }
      },
      listen: async () => () => {
        unlistenCalled = true;
      }
    });
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
    const host = createTauriHostStub({
      invoke: async () => undefined,
      listen: async () => {
        throw new Error("listener failed with token=secret-value");
      }
    });
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
