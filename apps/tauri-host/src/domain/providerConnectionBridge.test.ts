import { describe, expect, it, vi } from "vitest";
import { createProviderConnectionBridge } from "./providerConnectionBridge";
import { createTauriHostStub } from "./testHost";

describe("provider connection bridge", () => {
  it("discovers normalized models without sending credentials from the frontend", async () => {
    let listener: ((event: { payload: unknown }) => void) | undefined;
    const invoke = vi.fn(async () => {
      queueMicrotask(() => listener?.({ payload: { version: 1, request_id: "models-1", type: "provider_models", models: [{ id: "model-a" }, { id: "model-b" }] } }));
      return "models-1";
    });
    const bridge = createProviderConnectionBridge(createTauriHostStub({ invoke, listen: async (_event, handler) => { listener = handler; return () => undefined; } }));

    await expect(bridge.discoverModels({ providerId: "OpenAI-Responses", baseUrl: "https://api.example.test/v1/" }))
      .resolves.toEqual(["model-a", "model-b"]);
    expect(invoke).toHaveBeenCalledWith("runtime_discover_provider_models", {
      providerId: "openai-responses",
      baseUrl: "https://api.example.test/v1"
    });
    expect(JSON.stringify(invoke.mock.calls)).not.toMatch(/secret|api.?key/i);
  });

  it("tests the selected model and exposes only safe status", async () => {
    let listener: ((event: { payload: unknown }) => void) | undefined;
    const invoke = vi.fn(async () => {
      queueMicrotask(() => listener?.({ payload: { version: 1, request_id: "connection-1", type: "provider_connection_result", ok: true, latency_ms: 82, model: "model-a", detail: "ignored" } }));
      return "connection-1";
    });
    const bridge = createProviderConnectionBridge(createTauriHostStub({ invoke, listen: async (_event, handler) => { listener = handler; return () => undefined; } }));

    await expect(bridge.testConnection({ providerId: "minimax", baseUrl: "https://api.example.test", model: "model-a" }))
      .resolves.toEqual({ ok: true, latencyMs: 82, model: "model-a" });
  });

  it("rejects credential-bearing URLs before invoking the host", async () => {
    const invoke = vi.fn();
    const bridge = createProviderConnectionBridge(createTauriHostStub({ invoke, listen: async () => () => undefined }));
    await expect(bridge.discoverModels({ providerId: "minimax", baseUrl: "https://user:pass@example.test" })).rejects.toThrow();
    expect(invoke).not.toHaveBeenCalled();
  });
});
