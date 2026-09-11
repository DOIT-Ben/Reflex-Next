import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { batchEventText, createBatchFlow } from "./batchFlow";
import { setBatchSourceText } from "./batchState";
import type { CapabilityInvokeBridge } from "./translationFlow";
import type { CoreBridge } from "./coreBridge";
import type { PluginEventEnvelope } from "./capabilityBridge";

function fillSource(flow: ReturnType<typeof createBatchFlow>, source: string) {
  flow.state.update((state) => setBatchSourceText(state, source));
}

function createPluginBridge(events: PluginEventEnvelope[]): CapabilityInvokeBridge {
  return {
    invoke: async function* () {
      for (const event of events) yield event;
    }
  };
}

function createCoreBridgeForRun(): CoreBridge {
  return {
    optimize: async function* (request: { text: string }) {
      yield { type: "chunk", data: { text: `${request.text}!` } } as never;
      yield { type: "done", data: { text: `${request.text}!` } } as never;
    }
  } as unknown as CoreBridge;
}

function createDeps(overrides: Partial<Parameters<typeof createBatchFlow>[0]> = {}) {
  const base = {
    coreBridge: () => createCoreBridgeForRun(),
    capabilityBridge: () => null,
    requestContext: () => ({ mode: "content" as const, provider: "minimax", model: "m1" }),
    language: () => "zh-CN" as const,
    translate: (source: string) => source,
    showToast: vi.fn()
  };
  return { ...base, ...overrides } as Parameters<typeof createBatchFlow>[0];
}

const parseResult: PluginEventEnvelope = {
  version: 1,
  request_id: "b",
  type: "plugin_event",
  plugin_id: "batch-runner",
  operation: "parse",
  status: "result",
  data: { items: [{ id: 1, prompt: "第一段" }, { id: 2, prompt: "第二段" }] }
};

describe("batchEventText", () => {
  it("picks the first string field and normalizes line endings", () => {
    expect(batchEventText({ output: "a\r\nb" })).toBe("a\nb");
    expect(batchEventText({ result: "x" })).toBe("x");
    expect(batchEventText({})).toBe("");
  });
});

describe("createBatchFlow", () => {
  it("opens and closes with a fresh file notice", () => {
    const flow = createBatchFlow(createDeps());

    flow.open();
    expect(get(flow.state).phase).toBe("idle");
    expect(get(flow.fileNotice)).toBeNull();

    flow.close();
    expect(get(flow.state).phase).toBe("closed");
  });

  it("parses the source through the plugin bridge into ready items", async () => {
    const flow = createBatchFlow(
      createDeps({ capabilityBridge: () => createPluginBridge([parseResult]) })
    );
    flow.open();
    fillSource(flow, "第一段\n第二段");

    await flow.parse();

    expect(get(flow.state).phase).toBe("ready");
    expect(get(flow.state).items.map((item) => item.prompt)).toEqual(["第一段", "第二段"]);
  });

  it("keeps parsing state when the plugin bridge ends without a terminal event", async () => {
    const flow = createBatchFlow(
      createDeps({ capabilityBridge: () => createPluginBridge([]) })
    );
    flow.open();
    fillSource(flow, "第一段\n第二段");

    await flow.parse();

    expect(get(flow.state).phase).toBe("parsing");
  });

  it("runs every item through the core bridge and finalizes the run", async () => {
    const flow = createBatchFlow(
      createDeps({ capabilityBridge: () => createPluginBridge([parseResult]) })
    );
    flow.open();
    fillSource(flow, "第一段\n第二段");
    await flow.parse();

    await flow.run();

    const state = get(flow.state);
    expect(state.phase).toBe("completed");
    expect(state.items.map((item) => item.result)).toEqual(["第一段!", "第二段!"]);
  });

  it("exports results through the plugin and triggers a download", async () => {
    const revokeObjectURL = vi.fn();
    const createObjectURL = vi.fn(() => "blob:batch");
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.stubGlobal("document", {
      createElement: () => ({
        href: "",
        download: "",
        style: { display: "" },
        click: vi.fn(),
        remove: vi.fn()
      }),
      body: { append: vi.fn() }
    });
    vi.stubGlobal("window", { setTimeout: (callback: () => void) => callback() });
    const showToast = vi.fn();
    const flow = createBatchFlow(
      createDeps({
        capabilityBridge: () => ({
          invoke: async function* (_plugin: string, operation: string) {
            if (operation === "parse") {
              yield parseResult;
              return;
            }
            yield {
              version: 1,
              request_id: "e",
              type: "plugin_event",
              plugin_id: "batch-runner",
              operation: "export",
              status: "result",
              data: { content: "id,prompt\n1,第一段" }
            } satisfies PluginEventEnvelope;
          }
        }),
        showToast
      })
    );
    flow.open();
    fillSource(flow, "第一段\n第二段");
    await flow.parse();
    await flow.run();

    await flow.export();

    expect(showToast).toHaveBeenCalledWith("批处理结果已导出");
    vi.unstubAllGlobals();
  });
});
