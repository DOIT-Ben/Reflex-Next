import { describe, expect, it } from "vitest";
import { resolveProviderAvailability } from "./providerCatalog";

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
});
