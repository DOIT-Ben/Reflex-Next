import { describe, expect, it } from "vitest";
import {
  providerDefaultModel,
  providerModels,
  providerName,
  providerOptionsFromRuntime,
  resolveProviderAvailability
} from "./providerCatalog";

describe("provider availability", () => {
  it("waits until the persisted settings and matching secret status are ready", () => {
    expect(
      resolveProviderAvailability("minimax", { providerId: "minimax", configured: false }, false, false)
    ).toBe("checking");
    expect(
      resolveProviderAvailability("minimax", { providerId: "deepseek", configured: true }, true, false)
    ).toBe("checking");
  });

  it("distinguishes configured, missing, and unavailable providers", () => {
    expect(
      resolveProviderAvailability("MiniMax", { providerId: "minimax", configured: true }, true, false)
    ).toBe("ready");
    expect(
      resolveProviderAvailability("minimax", { providerId: "minimax", configured: false }, true, false)
    ).toBe("missing");
    expect(
      resolveProviderAvailability("minimax", { providerId: "minimax", configured: true }, true, true)
    ).toBe("unavailable");
  });

  it("maps the Runtime catalog to UI options and keeps the cloud route explicit", () => {
    const catalog = providerOptionsFromRuntime([
      {
        id: "minimax",
        name: "MiniMax 官方目录",
        models: ["runtime-model"],
        defaultModel: "runtime-model",
        releaseStatus: "supported",
        sessionConfigured: true
      }
    ]);

    expect(catalog.map((provider) => provider.id)).toEqual(["reflex-cloud", "minimax"]);
    expect(catalog[1]).toMatchObject({
      label: "MiniMax 官方目录",
      source: "runtime",
      sessionConfigured: true
    });
    expect(providerModels("MINIMAX", catalog)).toEqual([
      { id: "runtime-model", label: "runtime-model" }
    ]);
    expect(providerDefaultModel("MINIMAX", catalog)).toBe("runtime-model");
    expect(providerName("MINIMAX", catalog)).toBe("MiniMax 官方目录");
  });
});
