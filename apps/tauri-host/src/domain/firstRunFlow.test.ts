import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createFirstRunFlow } from "./firstRunFlow";
import type { AppConfig } from "./settingsApi";

type FlowDeps = Parameters<typeof createFirstRunFlow>[0];

function createDeps(overrides: Partial<FlowDeps> = {}) {
  const savedConfig: { value: AppConfig | null } = { value: { provider: "minimax" } as AppConfig };
  return {
    deps: {
      persistConfigPatch: vi.fn(async (build: (latest: AppConfig) => AppConfig) => {
        savedConfig.value = build(savedConfig.value as AppConfig);
        return savedConfig.value;
      }),
      hasPersistedConfig: () => savedConfig.value !== null,
      routeForProvider: (providerId: string) =>
        providerId === "reflex-cloud" ? ("cloud" as const) : ("byok" as const),
      currentProviderId: () => "minimax",
      ...overrides
    } as FlowDeps
  };
}

describe("createFirstRunFlow", () => {
  it("opens on hydrate when activation is incomplete and stays closed after completion", () => {
    const { deps } = createDeps();
    const flow = createFirstRunFlow(deps);

    flow.hydrate({ first_run_activation: { version: 1, completed: true, route: "byok" } } as unknown as AppConfig);
    expect(get(flow.open)).toBe(false);

    flow.hydrate({ first_run_activation: { version: 1, completed: false, route: null } } as unknown as AppConfig);
    expect(get(flow.open)).toBe(true);
  });

  it("rejects unavailable routes", async () => {
    const { deps } = createDeps();
    const flow = createFirstRunFlow(deps);

    const persisted = await flow.chooseRoute("cloud", ["byok"]);

    expect(persisted).toBe(false);
    expect(get(flow.state).route).toBeNull();
  });

  it("persists the chosen route", async () => {
    const { deps } = createDeps();
    const flow = createFirstRunFlow(deps);

    const persisted = await flow.chooseRoute("byok", ["byok", "cloud"]);

    expect(persisted).toBe(true);
    expect(get(flow.state).route).toBe("byok");
  });

  it("completes activation for the current provider route and closes", async () => {
    const { deps } = createDeps();
    const flow = createFirstRunFlow(deps);
    flow.hydrate({ first_run_activation: { version: 1, completed: false, route: null } } as unknown as AppConfig);

    const persisted = await flow.complete();

    expect(persisted).toBe(true);
    expect(get(flow.state).completed).toBe(true);
    expect(get(flow.open)).toBe(false);
    expect(deps.persistConfigPatch).toHaveBeenCalled();
  });

  it("keeps the dialog open with a notice when persistence fails", async () => {
    const { deps } = createDeps({
      hasPersistedConfig: () => false
    });
    const flow = createFirstRunFlow(deps);
    flow.hydrate({ first_run_activation: { version: 1, completed: false, route: null } } as unknown as AppConfig);

    const persisted = await flow.complete();

    expect(persisted).toBe(false);
    expect(get(flow.open)).toBe(true);
    expect(get(flow.notice)).toBe("首次使用状态暂未保存，本次仍可继续使用。");
  });

  it("postpone closes without persisting", () => {
    const { deps } = createDeps();
    const flow = createFirstRunFlow(deps);
    flow.hydrate({ first_run_activation: { version: 1, completed: false, route: null } } as unknown as AppConfig);

    flow.postpone();

    expect(get(flow.open)).toBe(false);
    expect(deps.persistConfigPatch).not.toHaveBeenCalled();
  });
});
