import { describe, expect, it } from "vitest";
import {
  fallbackProviderCatalog,
  providerDefaultModel,
  providerModels,
  providerName,
  providerOptionsFromRuntime,
  resolveProviderAvailability,
  workbenchModelOptions,
  withConfiguredModels
} from "./providerCatalog";

describe("fallback provider catalog", () => {
  it("includes the three primary protocol providers and their model choices", () => {
    expect(
      fallbackProviderCatalog.find((provider) => provider.id === "openai-responses")
    ).toMatchObject({
      label: "OpenAI Responses",
      defaultModel: "gpt-5.6-luna",
      releaseStatus: "experimental"
    });
    expect(fallbackProviderCatalog.find((provider) => provider.id === "anthropic")).toMatchObject({
      label: "Anthropic",
      defaultModel: "claude-sonnet-4-20250514",
      releaseStatus: "experimental"
    });
    expect(fallbackProviderCatalog.find((provider) => provider.id === "gemini")).toMatchObject({
      label: "Google Gemini",
      defaultModel: "gemini-2.5-flash",
      releaseStatus: "experimental"
    });
    expect(providerName("anthropic", fallbackProviderCatalog)).toBe("Anthropic");
    expect(providerName("gemini", fallbackProviderCatalog)).toBe("Google Gemini");
    expect(providerName("openai-responses", fallbackProviderCatalog)).toBe("OpenAI Responses");
  });
});

describe("configured provider models", () => {
  it("replaces static candidates with discovered models for the matching provider", () => {
    const catalog = withConfiguredModels(fallbackProviderCatalog, {
      anthropic: ["claude-custom-a", "claude-custom-b"]
    });
    expect(providerModels("anthropic", catalog)).toEqual([
      { id: "claude-custom-a", label: "claude-custom-a" },
      { id: "claude-custom-b", label: "claude-custom-b" }
    ]);
    expect(providerDefaultModel("anthropic", catalog)).toBe("claude-custom-a");
  });
});

describe("workbench model choices", () => {
  it("uses only models explicitly added in settings and marks the default", () => {
    const choices = workbenchModelOptions({
      provider: "anthropic",
      model: "claude-custom",
      provider_models: {
        anthropic: ["claude-custom"],
        "openai-responses": ["gpt-custom"]
      }
    }, fallbackProviderCatalog);

    expect(choices.map(({ providerId, id }) => [providerId, id])).toEqual([
      ["openai-responses", "gpt-custom"],
      ["anthropic", "claude-custom"]
    ]);
    expect(choices.find((model) => model.id === "claude-custom")?.isDefault).toBe(true);
    expect(choices.some((model) => model.id === "gpt-5.6-luna")).toBe(false);
  });

  it("falls back to configured runtime providers when no saved model list exists", () => {
    const catalog = providerOptionsFromRuntime([{
      id: "minimax",
      name: "MiniMax",
      models: ["runtime-model"],
      defaultModel: "runtime-model",
      releaseStatus: "supported",
      sessionConfigured: true
    }]);
    expect(workbenchModelOptions(null, catalog).map(({ providerId, id }) => [providerId, id])).toEqual([
      ["reflex-cloud", "MiniMax-M2.7-highspeed"],
      ["minimax", "runtime-model"]
    ]);
  });

  it("keeps the current default provider selectable during legacy config migration", () => {
    const catalog = providerOptionsFromRuntime([{
      id: "anthropic",
      name: "Anthropic",
      models: ["claude-current"],
      defaultModel: "claude-current",
      releaseStatus: "experimental",
      sessionConfigured: false
    }]);
    expect(workbenchModelOptions({ provider: "anthropic", model: "claude-current" }, catalog))
      .toEqual(expect.arrayContaining([
        expect.objectContaining({ providerId: "anthropic", id: "claude-current", isDefault: true })
      ]));
  });
});

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

  it("reports Cloud readiness from a real Cloud probe instead of a fixed flag", () => {
    expect(
      resolveProviderAvailability("reflex-cloud", null, true, false, "checking")
    ).toBe("checking");
    expect(
      resolveProviderAvailability("reflex-cloud", null, true, false, "ready")
    ).toBe("ready");
    expect(
      resolveProviderAvailability("reflex-cloud", null, true, false, "unavailable")
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
