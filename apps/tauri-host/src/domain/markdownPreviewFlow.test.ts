import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createMarkdownPreviewFlow } from "./markdownPreviewFlow";
import type { CapabilityInvokeBridge } from "./translationFlow";
import type { PluginEventEnvelope } from "./capabilityBridge";

function createPreviewBridge(status: PluginEventEnvelope["status"], data: Record<string, unknown>): CapabilityInvokeBridge {
  return {
    invoke: async function* () {
      yield {
        version: 1,
        request_id: "p",
        type: "plugin_event",
        plugin_id: "markdown-preview",
        operation: "preview",
        status,
        data
      } satisfies PluginEventEnvelope;
    }
  };
}

describe("createMarkdownPreviewFlow", () => {
  it("stays closed for empty sources or disabled plugins", () => {
    const flow = createMarkdownPreviewFlow({ capabilityBridge: () => null });

    flow.open("   ", true);
    expect(get(flow.state).phase).toBe("closed");

    flow.open("# 标题", false);
    expect(get(flow.state).phase).toBe("closed");
  });

  it("completes with the plugin result payload", async () => {
    const flow = createMarkdownPreviewFlow({
      capabilityBridge: () => createPreviewBridge("result", { html: "<h1>标题</h1>" })
    });

    flow.open("# 标题", true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("completed"));

    expect(get(flow.state).sourceText).toBe("# 标题");
  });

  it("enters the error phase when the plugin reports an error", async () => {
    const flow = createMarkdownPreviewFlow({
      capabilityBridge: () => createPreviewBridge("error", {})
    });

    flow.open("# 标题", true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("error"));
  });

  it("enters the error phase when no capability bridge exists", async () => {
    const flow = createMarkdownPreviewFlow({ capabilityBridge: () => null });

    flow.open("# 标题", true);
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("error"));
  });

  it("switches modes and closes idempotently", () => {
    const flow = createMarkdownPreviewFlow({
      capabilityBridge: () => createPreviewBridge("result", { html: "<p>x</p>" })
    });

    flow.open("# 标题", true);
    flow.setMode("source");
    expect(get(flow.state).mode).toBe("source");

    flow.close();
    expect(get(flow.state).phase).toBe("closed");

    flow.close();
    expect(get(flow.state).phase).toBe("closed");
  });
});
