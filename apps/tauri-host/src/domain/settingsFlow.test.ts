import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createSettingsFlow } from "./settingsFlow";
import type { ProviderConnectionBridge } from "./providerConnectionBridge";
import type { AppConfig, SettingsApi } from "./settingsApi";

type FlowDeps = Parameters<typeof createSettingsFlow>[0];

function createFakeApi(overrides: Partial<SettingsApi> = {}): SettingsApi {
  return {
    loadConfig: vi.fn(async () => ({ provider: "minimax" }) as unknown as AppConfig),
    saveConfig: vi.fn(async (config: AppConfig) => config),
    getProviderSecretStatus: vi.fn(async () => ({
      providerId: "minimax",
      configured: true,
      maskedTail: "****abcd"
    })),
    saveProviderSecret: vi.fn(async () => ({
      providerId: "minimax",
      configured: true,
      maskedTail: "****abcd"
    })),
    deleteProviderSecret: vi.fn(async () => ({
      providerId: "minimax",
      configured: false,
      maskedTail: null
    })),
    ...overrides
  };
}

function createDeps(overrides: Partial<FlowDeps> = {}) {
  return {
    settingsApi: () => createFakeApi(),
    providerCatalogBridge: () => null,
    providerConnectionBridge: () => null,
    desktopBridge: () => null,
    currentProviderModels: () => ({}),
    ...overrides
  } as FlowDeps;
}

describe("createSettingsFlow", () => {
  it("loads a config and keeps hydration busy until the caller finishes", async () => {
    const flow = createSettingsFlow(createDeps());

    const config = await flow.loadConfig();

    expect(config).not.toBeNull();
    expect(get(flow.persistedConfig)).not.toBeNull();
    expect(get(flow.settingsBusy)).toBe(true);
  });

  it("reports a load failure through notice and keeps no config", async () => {
    const flow = createSettingsFlow(
      createDeps({
        settingsApi: () =>
          createFakeApi({
            loadConfig: vi.fn(async () => {
              throw new Error("load failed");
            })
          })
      })
    );

    const config = await flow.loadConfig();

    expect(config).toBeNull();
    expect(get(flow.persistedConfig)).toBeNull();
    expect(get(flow.settingsNotice)).toBe("设置加载失败，请重试。");
    expect(get(flow.providerStatusError)).toBe(true);
  });

  it("persists patches serially and stores the saved result", async () => {
    const flow = createSettingsFlow(createDeps());
    await flow.loadConfig();

    const saved = await flow.persistConfigPatch((latest) => ({
      ...(latest as AppConfig),
      clipboard_replace_confirmed: true
    }));

    expect((saved as unknown as { clipboard_replace_confirmed: boolean }).clipboard_replace_confirmed).toBe(true);
    expect(
      (get(flow.persistedConfig) as unknown as { clipboard_replace_confirmed: boolean }).clipboard_replace_confirmed
    ).toBe(true);
  });

  it("saves a secret through the api and reports success", async () => {
    const flow = createSettingsFlow(createDeps());
    const onByokSaved = vi.fn(async () => undefined);

    await flow.saveSecret("minimax", "sk-test-value", onByokSaved);

    expect(get(flow.secretStatus).configured).toBe(true);
    expect(get(flow.secretNotice)).toBe("密钥已安全保存。");
    expect(onByokSaved).toHaveBeenCalledWith("minimax");
    expect(get(flow.secretBusy)).toBe(false);
  });

  it("rejects an empty secret without calling the api", async () => {
    const getProviderSecretStatus = vi.fn();
    const saveProviderSecret = vi.fn();
    const flow = createSettingsFlow(
      createDeps({
        settingsApi: () =>
          createFakeApi({ getProviderSecretStatus: getProviderSecretStatus as never, saveProviderSecret })
      })
    );

    await flow.saveSecret("minimax", "   ");

    expect(saveProviderSecret).not.toHaveBeenCalled();
    expect(get(flow.secretNotice)).toBe("请输入 API Key。");
  });

  it("treats reflex-cloud as configured without touching credential storage", async () => {
    const flow = createSettingsFlow(createDeps());

    await flow.refreshSecretStatus("reflex-cloud");

    expect(get(flow.secretStatus)).toEqual({
      providerId: "reflex-cloud",
      configured: true,
      maskedTail: null
    });
  });

  it("tests provider connections and reports latency", async () => {
    const flow = createSettingsFlow(
      createDeps({
        providerConnectionBridge: () =>
          ({
            testConnection: vi.fn(async () => ({ ok: true, latencyMs: 42 }))
          }) as unknown as ProviderConnectionBridge
      })
    );

    await flow.testConnection("minimax", "https://example.com", "m1");

    expect(get(flow.providerConnectionNotice)).toBe("连接成功，耗时 42 ms。");
  });
});
