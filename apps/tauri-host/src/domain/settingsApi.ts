import type { TauriHostApi } from "./coreBridge";
import type { ClipboardPolicy } from "./hostState";
import type { OptimizeMode, OptimizeStyle, ScenePolicy } from "./reflexSession";

export type AppConfig = {
  version: number;
  provider: string;
  model: string;
  mode: OptimizeMode;
  style: OptimizeStyle;
  scene_policy: ScenePolicy;
  clipboard_policy: ClipboardPolicy;
  history_enabled: boolean;
  privacy_mode: boolean;
  language: "zh-CN" | "en-US";
  theme: "light" | "dark" | "system";
  hotkey: string;
  tls_verify: true;
  ca_bundle_path: string | null;
  [key: string]: unknown;
};

export type SecretStatus = {
  providerId: string;
  configured: boolean;
  maskedTail: string | null;
};

export type SettingsApi = {
  loadConfig(): Promise<AppConfig>;
  saveConfig(config: AppConfig): Promise<AppConfig>;
  getProviderSecretStatus(providerId: string): Promise<SecretStatus>;
  saveProviderSecret(providerId: string, secret: string): Promise<SecretStatus>;
  deleteProviderSecret(providerId: string): Promise<SecretStatus>;
};

export function createSettingsApi(host: TauriHostApi): SettingsApi {
  return {
    async loadConfig() {
      return normalizeConfig(await host.invoke("load_app_config"));
    },
    async saveConfig(config) {
      return normalizeConfig(await host.invoke("save_app_config", { config }));
    },
    async getProviderSecretStatus(providerId) {
      return normalizeSecretStatus(
        await host.invoke("provider_secret_status", {
          providerId: normalizeProviderId(providerId)
        })
      );
    },
    async saveProviderSecret(providerId, secret) {
      return normalizeSecretStatus(
        await host.invoke("save_provider_secret", {
          providerId: normalizeProviderId(providerId),
          secret
        })
      );
    },
    async deleteProviderSecret(providerId) {
      return normalizeSecretStatus(
        await host.invoke("delete_provider_secret", {
          providerId: normalizeProviderId(providerId)
        })
      );
    }
  };
}

const defaults: AppConfig = {
  version: 1,
  provider: "minimax",
  model: "MiniMax-M2.7-highspeed",
  mode: "content",
  style: "balanced",
  scene_policy: "auto",
  clipboard_policy: "manual",
  history_enabled: true,
  privacy_mode: false,
  language: "zh-CN",
  theme: "system",
  hotkey: "Ctrl+Alt+R",
  tls_verify: true,
  ca_bundle_path: null
};

function normalizeConfig(value: unknown): AppConfig {
  const raw = isRecord(value) ? value : {};
  const safeExtensions = Object.fromEntries(
    Object.entries(raw).filter(([key]) => !isSensitiveKey(key))
  );
  return {
    ...safeExtensions,
    version: 1,
    provider: normalizeProviderId(stringValue(raw.provider, defaults.provider)),
    model: stringValue(raw.model, defaults.model),
    mode: choiceValue(raw.mode, ["content", "prompt"], defaults.mode),
    style: choiceValue(
      raw.style,
      ["concise", "balanced", "detailed", "creative"],
      defaults.style
    ),
    scene_policy: choiceValue(
      raw.scene_policy,
      ["auto", "manual", "ask"],
      defaults.scene_policy
    ),
    clipboard_policy: choiceValue(
      raw.clipboard_policy,
      ["startup", "manual", "auto_replace"],
      defaults.clipboard_policy
    ),
    history_enabled: booleanValue(raw.history_enabled, defaults.history_enabled),
    privacy_mode: booleanValue(raw.privacy_mode, defaults.privacy_mode),
    language: choiceValue(raw.language, ["zh-CN", "en-US"], defaults.language),
    theme: choiceValue(raw.theme, ["light", "dark", "system"], defaults.theme),
    hotkey: stringValue(raw.hotkey, defaults.hotkey),
    tls_verify: true,
    ca_bundle_path:
      typeof raw.ca_bundle_path === "string" && raw.ca_bundle_path.trim()
        ? raw.ca_bundle_path.trim()
        : null
  };
}

function normalizeSecretStatus(value: unknown): SecretStatus {
  const raw = isRecord(value) ? value : {};
  const providerId = normalizeProviderId(stringValue(raw.provider_id, "minimax"));
  const configured = raw.configured === true;
  const tail = typeof raw.masked_tail === "string" ? raw.masked_tail.slice(-4) : null;
  return {
    providerId,
    configured,
    maskedTail: configured && tail ? tail : null
  };
}

function normalizeProviderId(value: string): string {
  const normalized = value.trim().toLowerCase();
  return /^[a-z0-9._-]{1,64}$/.test(normalized) ? normalized : "minimax";
}

function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase().replaceAll("-", "_");
  return ["api_key", "apikey", "token", "secret", "authorization", "password"].some(
    (part) => normalized.includes(part)
  );
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function choiceValue<T extends string>(value: unknown, choices: readonly T[], fallback: T): T {
  return typeof value === "string" && choices.includes(value as T) ? (value as T) : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
