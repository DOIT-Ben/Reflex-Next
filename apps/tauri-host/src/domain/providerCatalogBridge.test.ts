import { describe, expect, it } from "vitest";
import type { TauriHostApi, TauriEvent } from "./coreBridge";
import {
  PROVIDER_CATALOG_UNAVAILABLE_MESSAGE,
  RuntimeProviderCatalogBridge,
  parseProviderCatalogEnvelope
} from "./providerCatalogBridge";
import { createTauriHostStub } from "./testHost";

function validProviderCatalog(requestId = "host-provider-catalog-1") {
  return {
    version: 1,
    request_id: requestId,
    type: "provider_catalog",
    providers: [
      {
        id: "minimax",
        name: "MiniMax",
        models: ["MiniMax-M2.7-highspeed"],
        default_model: "MiniMax-M2.7-highspeed",
        release_status: "supported",
        session_configured: true
      },
      {
        id: "qwen",
        name: "通义千问",
        models: ["qwen-plus", "qwen-max"],
        default_model: "qwen-plus",
        release_status: "experimental",
        session_configured: false
      }
    ]
  };
}

describe("provider catalog bridge", () => {
  it("correlates the response with the Rust-generated request id and ignores stale events", async () => {
    let listener: ((event: TauriEvent<Record<string, unknown>>) => void) | null = null;
    const calls: string[] = [];
    const host: TauriHostApi = createTauriHostStub({
      invoke: async (command) => {
        calls.push(command);
        queueMicrotask(() => {
          listener?.({ payload: validProviderCatalog() });
          listener?.({ payload: validProviderCatalog("host-provider-catalog-old") });
        });
        return "host-provider-catalog-1";
      },
      listen: async (eventName, handler) => {
        calls.push(eventName);
        listener = handler;
        return () => {
          listener = null;
        };
      }
    });

    const bridge = new RuntimeProviderCatalogBridge(host);
    await expect(bridge.listProviders()).resolves.toEqual([
      {
        id: "minimax",
        name: "MiniMax",
        models: ["MiniMax-M2.7-highspeed"],
        defaultModel: "MiniMax-M2.7-highspeed",
        releaseStatus: "supported",
        sessionConfigured: true
      },
      {
        id: "qwen",
        name: "通义千问",
        models: ["qwen-plus", "qwen-max"],
        defaultModel: "qwen-plus",
        releaseStatus: "experimental",
        sessionConfigured: false
      }
    ]);
    expect(calls).toEqual(["reflex://provider-catalog", "runtime_list_providers"]);
  });

  it("rejects malformed catalogs and does not expose wire details", () => {
    expect(() =>
      parseProviderCatalogEnvelope({
        ...validProviderCatalog(),
        providers: [{
          ...validProviderCatalog().providers[0],
          api_key: "catalog-fixture-secret"
        }]
      })
    ).toThrow(PROVIDER_CATALOG_UNAVAILABLE_MESSAGE);
  });

  it("rejects a safe Runtime catalog error without exposing its code", async () => {
    let listener: ((event: TauriEvent<Record<string, unknown>>) => void) | null = null;
    const host: TauriHostApi = createTauriHostStub({
      invoke: async () => {
        queueMicrotask(() =>
          listener?.({
            payload: {
              version: 1,
              request_id: "host-provider-catalog-1",
              type: "provider_catalog_error",
              code: "runtime_unavailable"
            }
          })
        );
        return "host-provider-catalog-1";
      },
      listen: async (_eventName, handler) => {
        listener = handler;
        return () => undefined;
      }
    });

    await expect(new RuntimeProviderCatalogBridge(host).listProviders()).rejects.toThrow(
      PROVIDER_CATALOG_UNAVAILABLE_MESSAGE
    );
  });

  it("times out with a fixed user-facing error and cleans up the listener", async () => {
    let unlistenCalled = false;
    const host: TauriHostApi = createTauriHostStub({
      invoke: async () => "host-provider-catalog-1",
      listen: async () => () => {
        unlistenCalled = true;
      }
    });

    await expect(
      new RuntimeProviderCatalogBridge(host).listProviders({ timeoutMs: 5 })
    ).rejects.toThrow(PROVIDER_CATALOG_UNAVAILABLE_MESSAGE);
    expect(unlistenCalled).toBe(true);
  });
});
