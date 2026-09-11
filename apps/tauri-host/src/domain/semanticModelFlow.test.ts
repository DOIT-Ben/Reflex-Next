import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createSemanticModelFlow } from "./semanticModelFlow";
import type { CapabilityInvokeBridge } from "./translationFlow";
import type { PluginEventEnvelope } from "./capabilityBridge";

function createBridge(events: PluginEventEnvelope[]): CapabilityInvokeBridge {
  return {
    invoke: async function* () {
      for (const event of events) yield event;
    }
  };
}

const readyResult: PluginEventEnvelope = {
  version: 1,
  request_id: "s",
  type: "plugin_event",
  plugin_id: "semantic-detector",
  operation: "status",
  status: "result",
  data: { model_id: "bge-small", model_state: "ready", runtime_state: "ready", size_bytes: 25_000_000 }
};

function createDeps(overrides: Partial<Parameters<typeof createSemanticModelFlow>[0]> = {}) {
  return {
    capabilityBridge: () => null,
    isEnabled: () => true,
    ...overrides
  } as Parameters<typeof createSemanticModelFlow>[0];
}

describe("createSemanticModelFlow", () => {
  it("reflects a ready model from the status result", async () => {
    const flow = createSemanticModelFlow(
      createDeps({ capabilityBridge: () => createBridge([readyResult]) })
    );

    await flow.run("status");
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("ready"));

    expect(get(flow.state).modelId).toBe("bge-small");
    expect(get(flow.state).sizeBytes).toBe(25_000_000);
  });

  it("ignores operations when the plugin is disabled", async () => {
    const flow = createSemanticModelFlow(
      createDeps({ capabilityBridge: () => createBridge([readyResult]), isEnabled: () => false })
    );

    await flow.run("status");

    expect(get(flow.state).phase).toBe("idle");
  });

  it("maps plugin errors to the error phase with the plugin code", async () => {
    const flow = createSemanticModelFlow(
      createDeps({
        capabilityBridge: () =>
          createBridge([
            {
              version: 1,
              request_id: "s",
              type: "plugin_event",
              plugin_id: "semantic-detector",
              operation: "download",
              status: "error",
              data: {},
              code: "model_download_failed"
            }
          ])
      })
    );

    await flow.run("download");
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("error"));

    expect(get(flow.state).errorCode).toBe("model_download_failed");
  });

  it("resets to a fresh state on reset()", async () => {
    const flow = createSemanticModelFlow(
      createDeps({ capabilityBridge: () => createBridge([readyResult]) })
    );
    await flow.run("status");
    await vi.waitFor(() => expect(get(flow.state).phase).toBe("ready"));

    flow.reset();

    expect(get(flow.state).phase).toBe("idle");
  });
});
