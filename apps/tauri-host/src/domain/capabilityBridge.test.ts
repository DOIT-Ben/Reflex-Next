import { describe, expect, it, vi } from "vitest";

import {
  CapabilityBridge,
  CAPABILITY_UNAVAILABLE_MESSAGE,
  createListPluginsCommand,
  createPluginCallCommand,
  createPluginCancelCommand,
  type CapabilityListEnvelope,
  type PluginEventEnvelope
} from "./capabilityBridge";
import type { TauriEvent, TauriHostApi } from "./coreBridge";

describe("capability bridge", () => {
  it("registers the capability listener before invoking and returns safe descriptors only", async () => {
    const order: string[] = [];
    let listener: ((event: TauriEvent<CapabilityListEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        order.push("listen");
        listener = handler as (event: TauriEvent<CapabilityListEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async (command, args) => {
        order.push(`invoke:${command}`);
        expect(args).toEqual({ command: createListPluginsCommand("list-1") });
        listener?.({
          payload: {
            version: 1,
            request_id: "list-1",
            type: "capability_list",
            plugins: [
              {
                id: "translator",
                name: "翻译",
                version: "1.0.0",
                kind: "transformer",
                permissions: ["network"],
                public_operations: ["translate"],
                enabled: true,
                state: "available"
              }
            ]
          }
        });
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "list-1" });

    await expect(bridge.listPlugins()).resolves.toEqual([
      {
        id: "translator",
        name: "翻译",
        version: "1.0.0",
        kind: "transformer",
        permissions: ["network"],
        public_operations: ["translate"],
        enabled: true,
        state: "available"
      }
    ]);
    expect(order).toEqual(["listen", "invoke:runtime_list_plugins"]);
    expect(unlistenCalled).toBe(true);
  });

  it("filters request plugin and operation then queues through one terminal event", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async (command, args) => {
        expect(command).toBe("runtime_plugin_call");
        expect(args).toEqual({
          command: createPluginCallCommand("plugin-1", "translator", "translate", {
            text: "fixture"
          })
        });
        const emit = (payload: PluginEventEnvelope) => listener?.({ payload });
        emit(pluginEvent("stale", "translator", "translate", "chunk", { text: "stale" }));
        emit(pluginEvent("plugin-1", "history-sqlite", "translate", "chunk", { text: "wrong" }));
        emit(pluginEvent("plugin-1", "translator", "preview", "chunk", { text: "wrong" }));
        emit(pluginEvent("plugin-1", "translator", "translate", "started", {}));
        emit(pluginEvent("plugin-1", "translator", "translate", "chunk", { text: "A" }));
        emit(pluginEvent("plugin-1", "translator", "translate", "progress", { percent: 50 }));
        emit(pluginEvent("plugin-1", "translator", "translate", "result", { text: "AB" }));
        emit(pluginEvent("plugin-1", "translator", "translate", "chunk", { text: "late" }));
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "plugin-1" });

    const events = [];
    for await (const event of bridge.invoke("translator", "translate", { text: "fixture" })) {
      events.push(event);
    }

    expect(events.map((event) => event.status)).toEqual([
      "started",
      "chunk",
      "progress",
      "result"
    ]);
    expect(events.at(-1)?.data).toEqual({ text: "AB" });
    expect(unlistenCalled).toBe(true);
  });

  it("aborts only its own request and drops any late response", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    const calls: Array<{ command: string; args: unknown }> = [];
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => undefined;
      },
      invoke: async (command, args) => {
        calls.push({ command, args });
      }
    };
    const controller = new AbortController();
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "abort-own" });
    const iterator = bridge.invoke(
      "translator",
      "translate",
      { text: "fixture" },
      { signal: controller.signal }
    );

    const pending = iterator.next();
    await Promise.resolve();
    await Promise.resolve();
    controller.abort();
    listener?.({
      payload: pluginEvent("abort-own", "translator", "translate", "result", {
        text: "late"
      })
    });

    await expect(pending).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
    await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });
    expect(calls).toEqual([
      {
        command: "runtime_plugin_call",
        args: {
          command: createPluginCallCommand("abort-own", "translator", "translate", {
            text: "fixture"
          })
        }
      },
      {
        command: "runtime_plugin_cancel",
        args: { command: createPluginCancelCommand("abort-own") }
      }
    ]);
  });

  it("uses one fixed safe error and always unlistens when invoke fails", async () => {
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async () => () => {
        unlistenCalled = true;
      },
      invoke: async () => {
        throw new Error("module=C:\\private\\plugin.py token=fixture-private");
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "plugin-error" });

    const pending = bridge.invoke("translator", "translate", {}).next();

    await expect(pending).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
    await expect(pending).rejects.not.toThrow("fixture-private");
    expect(unlistenCalled).toBe(true);
  });

  it("rejects descriptors containing module paths with the same safe error", async () => {
    let listener: ((event: TauriEvent<CapabilityListEnvelope>) => void) | null = null;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<CapabilityListEnvelope>) => void;
        return () => undefined;
      },
      invoke: async () => {
        listener?.({
          payload: {
            version: 1,
            request_id: "unsafe-list",
            type: "capability_list",
            plugins: [
              {
                id: "translator",
                name: "Translator",
                version: "1",
                kind: "transformer",
                permissions: [],
                public_operations: ["translate"],
                enabled: true,
                state: "available",
                module: "C:\\private\\plugin.py"
              } as never
            ]
          }
        });
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "unsafe-list" });

    await expect(bridge.listPlugins()).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
  });

  it("rejects plugin data with Runtime-invalid keys without exposing the payload", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => undefined;
      },
      invoke: async () => {
        listener?.({
          payload: pluginEvent("invalid-data", "translator", "translate", "result", {
            "": "fixture-private"
          })
        });
      }
    };
    const bridge = new CapabilityBridge(host, {
      requestIdFactory: () => "invalid-data"
    });

    await expect(bridge.invoke("translator", "translate", {}).next()).rejects.toThrow(
      CAPABILITY_UNAVAILABLE_MESSAGE
    );
  });

  it("rejects a pending consumer when a malformed matching event arrives", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async () => undefined
    };
    const bridge = new CapabilityBridge(host, {
      requestIdFactory: () => "pending-invalid"
    });
    const iterator = bridge.invoke("translator", "translate", {});

    const pending = iterator.next();
    await Promise.resolve();
    await Promise.resolve();
    expect(listener).not.toBeNull();
    listener?.({
      payload: {
        ...pluginEvent("pending-invalid", "translator", "translate", "chunk", {}),
        debug: "fixture-private"
      } as never
    });

    await expect(pending).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
    await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });
    expect(unlistenCalled).toBe(true);
  });

  it("times out list requests, cancels only that request, and unlistens", async () => {
    const calls: Array<{ command: string; args: unknown }> = [];
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async () => () => {
        unlistenCalled = true;
      },
      invoke: async (command, args) => {
        calls.push({ command, args });
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "list-timeout" });

    await expect(bridge.listPlugins({ timeoutMs: 5 })).rejects.toThrow(
      CAPABILITY_UNAVAILABLE_MESSAGE
    );

    expect(calls).toEqual([
      {
        command: "runtime_list_plugins",
        args: { command: createListPluginsCommand("list-timeout") }
      },
      {
        command: "runtime_plugin_cancel",
        args: { command: createPluginCancelCommand("list-timeout") }
      }
    ]);
    expect(unlistenCalled).toBe(true);
  });

  it(
    "bounds list cleanup even when the initial invoke never settles",
    async () => {
      let unlistenCalled = false;
      const calls: string[] = [];
      const host: TauriHostApi = {
        listen: async () => () => {
          unlistenCalled = true;
        },
        invoke: async (command) => {
          calls.push(command);
          if (command === "runtime_list_plugins") {
            await new Promise(() => undefined);
          }
        }
      };
      const bridge = new CapabilityBridge(host, {
        requestIdFactory: () => "list-hanging-invoke"
      });

      await expect(bridge.listPlugins({ timeoutMs: 5 })).rejects.toThrow(
        CAPABILITY_UNAVAILABLE_MESSAGE
      );
      expect(calls).toEqual(["runtime_list_plugins", "runtime_plugin_cancel"]);
      expect(unlistenCalled).toBe(true);
    },
    100
  );

  it("aborts list requests with the same bounded cleanup contract", async () => {
    const calls: Array<{ command: string; args: unknown }> = [];
    let unlistenCalled = false;
    const controller = new AbortController();
    const host: TauriHostApi = {
      listen: async () => () => {
        unlistenCalled = true;
      },
      invoke: async (command, args) => {
        calls.push({ command, args });
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "list-abort" });
    const pending = bridge.listPlugins({ signal: controller.signal, timeoutMs: 1_000 });
    await Promise.resolve();
    await Promise.resolve();
    controller.abort();

    await expect(pending).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
    expect(calls.at(-1)).toEqual({
      command: "runtime_plugin_cancel",
      args: { command: createPluginCancelCommand("list-abort") }
    });
    expect(unlistenCalled).toBe(true);
  });

  it("cancels an unterminated generator when the consumer breaks", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    const calls: Array<{ command: string; args: unknown }> = [];
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async (command, args) => {
        calls.push({ command, args });
        if (command === "runtime_plugin_call") {
          listener?.({
            payload: pluginEvent("plugin-break", "translator", "translate", "started", {})
          });
        }
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "plugin-break" });

    for await (const _event of bridge.invoke("translator", "translate", {})) {
      break;
    }

    expect(calls.at(-1)).toEqual({
      command: "runtime_plugin_cancel",
      args: { command: createPluginCancelCommand("plugin-break") }
    });
    expect(unlistenCalled).toBe(true);
  });

  it("abort clears buffered plugin events and rejects the pending consumer", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const controller = new AbortController();
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async (command) => {
        if (command === "runtime_plugin_call") {
          listener?.({
            payload: pluginEvent("buffer-abort", "translator", "translate", "chunk", {
              text: "first"
            })
          });
          listener?.({
            payload: pluginEvent("buffer-abort", "translator", "translate", "chunk", {
              text: "must-not-yield"
            })
          });
        }
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "buffer-abort" });
    const iterator = bridge.invoke(
      "translator",
      "translate",
      {},
      { signal: controller.signal }
    );

    await expect(iterator.next()).resolves.toMatchObject({
      done: false,
      value: { data: { text: "first" } }
    });
    controller.abort();
    await expect(iterator.next()).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
    await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });
    expect(unlistenCalled).toBe(true);
  });

  it("still unlistens when generator cancellation cannot be delivered", async () => {
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalled = false;
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalled = true;
        };
      },
      invoke: async (command) => {
        if (command === "runtime_plugin_cancel") throw new Error("fixture cancel failure");
        listener?.({
          payload: pluginEvent("cancel-fails", "translator", "translate", "started", {})
        });
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "cancel-fails" });

    for await (const _event of bridge.invoke("translator", "translate", {})) {
      break;
    }

    expect(unlistenCalled).toBe(true);
  });

  it(
    "aborts immediately while the initial plugin invoke is still pending",
    async () => {
      const controller = new AbortController();
      const calls: string[] = [];
      let unlistenCalls = 0;
      const host: TauriHostApi = {
        listen: async () => () => {
          unlistenCalls += 1;
        },
        invoke: async (command) => {
          calls.push(command);
          if (command === "runtime_plugin_call") {
            await new Promise(() => undefined);
          }
        }
      };
      const bridge = new CapabilityBridge(host, { requestIdFactory: () => "pending-abort" });
      const iterator = bridge.invoke(
        "translator",
        "translate",
        {},
        { signal: controller.signal, timeoutMs: 1_000 }
      );

      const pending = iterator.next();
      await Promise.resolve();
      await Promise.resolve();
      controller.abort();

      await expect(pending).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
      expect(calls).toEqual(["runtime_plugin_call", "runtime_plugin_cancel"]);
      expect(unlistenCalls).toBe(1);
    },
    150
  );

  it(
    "times out immediately while the initial plugin invoke is still pending",
    async () => {
      const calls: string[] = [];
      let unlistenCalls = 0;
      const host: TauriHostApi = {
        listen: async () => () => {
          unlistenCalls += 1;
        },
        invoke: async (command) => {
          calls.push(command);
          if (command === "runtime_plugin_call") {
            await new Promise(() => undefined);
          }
        }
      };
      const bridge = new CapabilityBridge(host, { requestIdFactory: () => "pending-timeout" });

      await expect(
        bridge.invoke("translator", "translate", {}, { timeoutMs: 5 }).next()
      ).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
      expect(calls).toEqual(["runtime_plugin_call", "runtime_plugin_cancel"]);
      expect(unlistenCalls).toBe(1);
    },
    150
  );

  it("cleans the plugin listener exactly once when the initial invoke rejects", async () => {
    let unlistenCalls = 0;
    const host: TauriHostApi = {
      listen: async () => () => {
        unlistenCalls += 1;
      },
      invoke: async (command) => {
        if (command === "runtime_plugin_call") throw new Error("fixture invoke failure");
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "invoke-cleanup" });

    await expect(bridge.invoke("translator", "translate", {}).next()).rejects.toThrow(
      CAPABILITY_UNAVAILABLE_MESSAGE
    );
    expect(unlistenCalls).toBe(1);
  });

  it(
    "does not block generator cleanup when the cancel invoke stays pending",
    async () => {
      let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
      let unlistenCalls = 0;
      const host: TauriHostApi = {
        listen: async (_name, handler) => {
          listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
          return () => {
            unlistenCalls += 1;
          };
        },
        invoke: async (command) => {
          if (command === "runtime_plugin_cancel") {
            await new Promise(() => undefined);
          }
          listener?.({
            payload: pluginEvent("pending-cancel", "translator", "translate", "started", {})
          });
        }
      };
      const bridge = new CapabilityBridge(host, { requestIdFactory: () => "pending-cancel" });

      for await (const _event of bridge.invoke("translator", "translate", {})) {
        break;
      }

      expect(unlistenCalls).toBe(1);
    },
    150
  );

  it("keeps a valid progressing stream alive beyond the ten second window", async () => {
    vi.useFakeTimers();
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalls = 0;
    const calls: string[] = [];
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalls += 1;
        };
      },
      invoke: async (command) => {
        calls.push(command);
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "long-progress" });
    const iterator = bridge.invoke("translator", "translate", {});

    try {
      const started = iterator.next();
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(9_000);
      listener?.({
        payload: pluginEvent("long-progress", "translator", "translate", "started", {})
      });
      await expect(started).resolves.toMatchObject({ value: { status: "started" } });

      const progress = iterator.next();
      const progressResult = expect(progress).resolves.toMatchObject({
        value: { status: "progress" }
      });
      await vi.advanceTimersByTimeAsync(9_000);
      listener?.({
        payload: pluginEvent("long-progress", "translator", "translate", "progress", {
          percent: 50
        })
      });
      await progressResult;

      const result = iterator.next();
      const terminalResult = expect(result).resolves.toMatchObject({
        value: { status: "result" }
      });
      await vi.advanceTimersByTimeAsync(9_000);
      listener?.({
        payload: pluginEvent("long-progress", "translator", "translate", "result", {
          text: "done"
        })
      });
      await terminalResult;
      await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });

      expect(calls).toEqual(["runtime_plugin_call"]);
      expect(unlistenCalls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels after one inactivity window following the last valid event", async () => {
    vi.useFakeTimers();
    let listener: ((event: TauriEvent<PluginEventEnvelope>) => void) | null = null;
    let unlistenCalls = 0;
    const calls: string[] = [];
    const host: TauriHostApi = {
      listen: async (_name, handler) => {
        listener = handler as (event: TauriEvent<PluginEventEnvelope>) => void;
        return () => {
          unlistenCalls += 1;
        };
      },
      invoke: async (command) => {
        calls.push(command);
      }
    };
    const bridge = new CapabilityBridge(host, { requestIdFactory: () => "stalled-progress" });
    const iterator = bridge.invoke("translator", "translate", {});

    try {
      const started = iterator.next();
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(9_000);
      listener?.({
        payload: pluginEvent("stalled-progress", "translator", "translate", "started", {})
      });
      await expect(started).resolves.toMatchObject({ value: { status: "started" } });

      const stalled = iterator.next();
      const stalledResult = expect(stalled).rejects.toThrow(CAPABILITY_UNAVAILABLE_MESSAGE);
      await vi.advanceTimersByTimeAsync(10_001);
      await stalledResult;
      expect(calls).toEqual(["runtime_plugin_call", "runtime_plugin_cancel"]);
      expect(unlistenCalls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

function pluginEvent(
  requestId: string,
  pluginId: string,
  operation: string,
  status: PluginEventEnvelope["status"],
  data: Record<string, unknown>
): PluginEventEnvelope {
  return {
    version: 1,
    request_id: requestId,
    type: "plugin_event",
    plugin_id: pluginId,
    operation,
    status,
    data
  };
}
