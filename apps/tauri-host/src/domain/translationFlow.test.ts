import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createTranslationFlow, type CapabilityInvokeBridge } from "./translationFlow";
import type { CoreBridge } from "./coreBridge";
import type { CurrentResult, HostState } from "./hostState";
import type { PluginEventEnvelope } from "./capabilityBridge";

vi.mock("./hostState", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./hostState")>();
  return {
    ...actual,
    applyTranslationAsCurrentResult: vi.fn((state: HostState) => ({
      ...(state as unknown as object),
      applied: ["translation"]
    }))
  };
});

function createFakeResult(overrides: Partial<CurrentResult> = {}): CurrentResult {
  return {
    requestId: "ui-test",
    historyId: null,
    sourceText: "hello world",
    output: "hello world",
    scene: null,
    style: "balanced",
    mode: "content",
    provider: "minimax",
    model: "m1",
    elapsedMs: 12,
    saveStatus: "saved",
    rating: null,
    ...overrides
  };
}

function createPluginBridge(
  events: PluginEventEnvelope[]
): CapabilityInvokeBridge {
  return {
    invoke: async function* () {
      for (const event of events) yield event;
    }
  };
}

function createCoreBridge(events: Array<{ type: string; data: Record<string, unknown> }>): CoreBridge {
  return {
    optimize: async function* () {
      for (const event of events) yield event as never;
    }
  } as unknown as CoreBridge;
}

function createDeps(overrides: Partial<Parameters<typeof createTranslationFlow>[0]> = {}) {
  const hostState: { state: HostState } = { state: { applied: [] } as unknown as HostState };
  const base = {
    coreBridge: () => null,
    capabilityBridge: () => null,
    currentResult: () => createFakeResult(),
    fallbackRoute: () => ({ provider: "minimax", model: "m1" }),
    updateHostState: (updater: (state: HostState) => HostState) => {
      hostState.state = updater(hostState.state);
    },
    writeClipboardValue: vi.fn(async () => true),
    showToast: vi.fn()
  };
  return { deps: { ...base, ...overrides } as Parameters<typeof createTranslationFlow>[0], hostState };
}

const pluginChunk: PluginEventEnvelope = {
  version: 1,
  request_id: "t",
  type: "plugin_event",
  plugin_id: "translator",
  operation: "translate",
  status: "chunk",
  data: { text: "你好" }
};

const pluginResult: PluginEventEnvelope = {
  version: 1,
  request_id: "t",
  type: "plugin_event",
  plugin_id: "translator",
  operation: "translate",
  status: "result",
  data: { text: "你好世界", source_language: "zh", target_language: "en" }
};

describe("createTranslationFlow", () => {
  it("stays closed when the translator plugin is disabled", () => {
    const { deps } = createDeps();
    const flow = createTranslationFlow(deps);

    flow.open(createFakeResult(), false);

    expect(get(flow.state).phase).toBe("closed");
  });

  it("completes through the translator plugin bridge", async () => {
    const { deps } = createDeps({
      capabilityBridge: () => createPluginBridge([pluginChunk, pluginResult])
    });
    const flow = createTranslationFlow(deps);

    flow.open(createFakeResult(), true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("completed"));

    expect(get(flow.state).translatedText).toBe("你好世界");
  });

  it("completes through the cloud plan when the provider is reflex-cloud", async () => {
    const { deps } = createDeps({
      currentResult: () => createFakeResult({ provider: "reflex-cloud" }),
      coreBridge: () =>
        createCoreBridge([
          { type: "chunk", data: { text: "bon" } },
          { type: "done", data: { text: "bonjour", final_text: null } }
        ])
    });
    const flow = createTranslationFlow(deps);

    flow.open(createFakeResult({ provider: "reflex-cloud" }), true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("completed"));

    expect(get(flow.state).translatedText).toBe("bonjour");
  });

  it("fails with a friendly message when no bridge is available", async () => {
    const { deps } = createDeps();
    const flow = createTranslationFlow(deps);

    flow.open(createFakeResult(), true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("error"));

    expect(get(flow.state).error).toBe("翻译暂时不可用，请重试。");
  });

  it("copies the translated text through the shared clipboard writer", async () => {
    const { deps } = createDeps({
      capabilityBridge: () => createPluginBridge([pluginResult])
    });
    const flow = createTranslationFlow(deps);
    flow.open(createFakeResult(), true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("completed"));

    await flow.copy();

    expect(deps.writeClipboardValue).toHaveBeenCalledWith("你好世界", "✓ 译文已复制");
  });

  it("applies the result to the host state and closes on useAsCurrentResult", async () => {
    const { deps, hostState } = createDeps({
      capabilityBridge: () => createPluginBridge([pluginResult])
    });
    const flow = createTranslationFlow(deps);
    flow.open(createFakeResult(), true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("completed"));

    flow.useAsCurrentResult();

    expect((hostState.state as unknown as { applied: string[] }).applied).toEqual(["translation"]);
    expect(get(flow.state).phase).toBe("closed");
    expect(deps.showToast).toHaveBeenCalledWith("已设为当前结果");
  });
});
