import { get, writable, type Writable } from "svelte/store";
import type { ProviderCatalogBridge } from "./providerCatalogBridge";
import { PROVIDER_CATALOG_UNAVAILABLE_MESSAGE } from "./providerCatalogBridge";
import type { ProviderConnectionBridge } from "./providerConnectionBridge";
import {
  safeDesktopSettingsError,
  type DesktopBridge,
  type DesktopStatus
} from "./desktopBridge";
import {
  fallbackProviderCatalog,
  providerOptionsFromRuntime,
  withConfiguredModels,
  type ProviderOption
} from "./providerCatalog";
import type { AppConfig, SecretStatus, SettingsApi } from "./settingsApi";

export type SettingsFlowDeps = {
  settingsApi: () => SettingsApi | null;
  providerCatalogBridge: () => ProviderCatalogBridge | null;
  providerConnectionBridge: () => ProviderConnectionBridge | null;
  desktopBridge: () => DesktopBridge | null;
  currentProviderModels: () => Record<string, string[]>;
};

export type SettingsFlow = {
  persistedConfig: Writable<AppConfig | null>;
  providerOptions: Writable<ProviderOption[]>;
  secretStatus: Writable<SecretStatus>;
  secretBusy: Writable<boolean>;
  secretNotice: Writable<string | null>;
  providerStatusError: Writable<boolean>;
  providerCatalogNotice: Writable<string | null>;
  providerConnectionBusy: Writable<"models" | "test" | null>;
  providerConnectionNotice: Writable<string | null>;
  settingsBusy: Writable<boolean>;
  settingsNotice: Writable<string | null>;
  desktopStatus: Writable<DesktopStatus>;
  loadConfig: () => Promise<AppConfig | null>;
  persistConfigPatch: (build: (latest: AppConfig) => AppConfig) => Promise<AppConfig>;
  refreshCatalog: () => Promise<void>;
  refreshDesktopStatus: () => Promise<void>;
  refreshSecretStatus: (providerId: string) => Promise<void>;
  saveSecret: (
    providerId: string,
    value: string,
    onByokSaved?: (providerId: string) => Promise<void>
  ) => Promise<void>;
  beginSecretDelete: () => boolean;
  performSecretDelete: (providerId: string) => Promise<void>;
  discoverModels: (providerId: string, baseUrl: string) => Promise<string[] | null>;
  testConnection: (providerId: string, baseUrl: string, model: string | null) => Promise<void>;
  applyConfiguredModels: (providerModels: Record<string, string[]>) => void;
};

const DEFAULT_SECRET_STATUS: SecretStatus = {
  providerId: "minimax",
  configured: false,
  maskedTail: null
};

export function createSettingsFlow(deps: SettingsFlowDeps): SettingsFlow {
  const persistedConfig = writable<AppConfig | null>(null);
  const providerOptions = writable<ProviderOption[]>([...fallbackProviderCatalog]);
  const secretStatus = writable<SecretStatus>(DEFAULT_SECRET_STATUS);
  const secretBusy = writable(false);
  const secretNotice = writable<string | null>(null);
  const providerStatusError = writable(false);
  const providerCatalogNotice = writable<string | null>(null);
  const providerConnectionBusy = writable<"models" | "test" | null>(null);
  const providerConnectionNotice = writable<string | null>(null);
  const settingsBusy = writable(false);
  const settingsNotice = writable<string | null>(null);
  const desktopStatus = writable<DesktopStatus>({
    hotkey: "Ctrl+Alt+R",
    hotkeyActive: false,
    message: null
  });
  let configWriteChain: Promise<void> = Promise.resolve();

  async function loadConfig(): Promise<AppConfig | null> {
    const api = deps.settingsApi();
    if (!api) return null;
    settingsBusy.set(true);
    providerStatusError.set(false);
    settingsNotice.set(null);
    secretNotice.set(null);
    try {
      const config = await api.loadConfig();
      persistedConfig.set(config);
      return config;
    } catch {
      providerStatusError.set(true);
      settingsNotice.set("设置加载失败，请重试。");
      settingsBusy.set(false);
      return null;
    }
  }

  function persistConfigPatch(build: (latest: AppConfig) => AppConfig): Promise<AppConfig> {
    const api = deps.settingsApi();
    if (!api) return Promise.reject(new Error("settings-api-unavailable"));
    const write = configWriteChain.then(async () => {
      const latest = await api.loadConfig();
      const saved = await api.saveConfig(build(latest));
      persistedConfig.set(saved);
      return saved;
    });
    configWriteChain = write.then(() => undefined, () => undefined);
    return write;
  }

  async function refreshCatalog() {
    const bridge = deps.providerCatalogBridge();
    if (!bridge) return;
    try {
      const descriptors = await bridge.listProviders();
      providerOptions.set(
        withConfiguredModels(providerOptionsFromRuntime(descriptors), deps.currentProviderModels())
      );
      providerCatalogNotice.set(null);
    } catch {
      // Keep the browser-safe catalog visible while the Runtime recovers.
      providerCatalogNotice.set(PROVIDER_CATALOG_UNAVAILABLE_MESSAGE);
    }
  }

  async function refreshDesktopStatus() {
    const bridge = deps.desktopBridge();
    if (!bridge) return;
    try {
      desktopStatus.set(await bridge.status());
    } catch {
      desktopStatus.update((current) => ({ ...current, message: "快捷键状态暂不可用。" }));
    }
  }

  async function refreshSecretStatus(providerId: string) {
    if (providerId === "reflex-cloud") {
      secretStatus.set({ providerId, configured: true, maskedTail: null });
      providerStatusError.set(false);
      secretNotice.set(null);
      return;
    }
    const api = deps.settingsApi();
    if (!api) return;
    try {
      secretStatus.set(await api.getProviderSecretStatus(providerId));
      providerStatusError.set(false);
    } catch {
      providerStatusError.set(true);
      secretStatus.set({ providerId, configured: false, maskedTail: null });
      secretNotice.set("密钥状态读取失败，请重试。");
    }
  }

  async function saveSecret(
    providerId: string,
    value: string,
    onByokSaved?: (providerId: string) => Promise<void>
  ) {
    if (get(secretBusy)) return;
    const api = deps.settingsApi();
    if (!api) {
      secretNotice.set("当前环境无法保存密钥。");
      return;
    }
    if (!value) {
      secretNotice.set("请输入 API Key。");
      return;
    }
    secretBusy.set(true);
    secretNotice.set(null);
    try {
      secretStatus.set(await api.saveProviderSecret(providerId, value));
      providerStatusError.set(false);
      secretNotice.set("密钥已安全保存。");
      if (onByokSaved) {
        await onByokSaved(providerId);
      }
    } catch {
      providerStatusError.set(true);
      secretNotice.set("密钥保存失败，请重试。");
    } finally {
      secretBusy.set(false);
    }
  }

  function beginSecretDelete(): boolean {
    return get(secretStatus).configured && !get(secretBusy);
  }

  async function performSecretDelete(providerId: string) {
    const api = deps.settingsApi();
    if (!api) {
      secretNotice.set("当前环境无法删除密钥。");
      return;
    }
    secretBusy.set(true);
    secretNotice.set(null);
    try {
      secretStatus.set(await api.deleteProviderSecret(providerId));
      providerStatusError.set(false);
      secretNotice.set("密钥已删除。");
    } catch {
      providerStatusError.set(true);
      secretNotice.set("密钥删除失败，请重试。");
    } finally {
      secretBusy.set(false);
    }
  }

  async function discoverModels(
    providerId: string,
    baseUrl: string
  ): Promise<string[] | null> {
    const bridge = deps.providerConnectionBridge();
    if (!bridge || get(providerConnectionBusy)) return null;
    providerConnectionBusy.set("models");
    providerConnectionNotice.set(null);
    try {
      const models = await bridge.discoverModels({ providerId, baseUrl });
      const nextModels = { ...deps.currentProviderModels(), [providerId]: models };
      providerOptions.update((options) => withConfiguredModels(options, nextModels));
      providerConnectionNotice.set(`已获取 ${models.length} 个模型。`);
      return models;
    } catch (error) {
      providerConnectionNotice.set(error instanceof Error ? error.message : "无法获取模型列表，请重试。");
      return null;
    } finally {
      providerConnectionBusy.set(null);
    }
  }

  async function testConnection(providerId: string, baseUrl: string, model: string | null) {
    const bridge = deps.providerConnectionBridge();
    if (!bridge || get(providerConnectionBusy)) return;
    providerConnectionBusy.set("test");
    providerConnectionNotice.set(null);
    try {
      const result = await bridge.testConnection({ providerId, baseUrl, model });
      providerConnectionNotice.set(
        result.ok
          ? `连接成功${result.latencyMs === null ? "" : `，耗时 ${result.latencyMs} ms`}。`
          : "模型连接测试失败，请检查配置后重试。"
      );
    } catch (error) {
      providerConnectionNotice.set(
        error instanceof Error ? error.message : "模型连接测试失败，请重试。"
      );
    } finally {
      providerConnectionBusy.set(null);
    }
  }

  function applyConfiguredModels(providerModels: Record<string, string[]>) {
    providerOptions.update((options) => withConfiguredModels(options, providerModels));
  }

  return {
    persistedConfig,
    providerOptions,
    secretStatus,
    secretBusy,
    secretNotice,
    providerStatusError,
    providerCatalogNotice,
    providerConnectionBusy,
    providerConnectionNotice,
    settingsBusy,
    settingsNotice,
    desktopStatus,
    loadConfig,
    persistConfigPatch,
    refreshCatalog,
    refreshDesktopStatus,
    refreshSecretStatus,
    saveSecret,
    beginSecretDelete,
    performSecretDelete,
    discoverModels,
    testConnection,
    applyConfiguredModels
  };
}

export { safeDesktopSettingsError };
