import { describe, expect, it } from "vitest";
import { createSettingsApi, type AppConfig } from "./settingsApi";

const config: AppConfig = {
  version: 2,
  provider: "minimax",
  model: "MiniMax-M2.7-highspeed",
  mode: "content",
  style: "balanced",
  scene_policy: "auto",
  clipboard_policy: "manual",
  clipboard_replace_confirmed: false,
  history_enabled: false,
  privacy_mode: false,
  history_redaction: "secrets",
  enabled_plugins: ["translator", "markdown-preview"],
  language: "zh-CN",
  theme: "system",
  hotkey: "Ctrl+Alt+R",
  tls_verify: true,
  ca_bundle_path: null,
  provider_endpoints: {},
  provider_models: {}
};

describe("settings api", () => {
  it("loads and saves only non-sensitive application config", async () => {
    const calls: Array<{ command: string; args: unknown }> = [];
    const api = createSettingsApi({
      invoke: async (command, args) => {
        calls.push({ command, args });
        return config;
      },
      listen: async () => () => undefined
    });

    await expect(api.loadConfig()).resolves.toEqual(config);
    await expect(api.saveConfig(config)).resolves.toEqual(config);
    expect(calls).toEqual([
      { command: "load_app_config", args: undefined },
      { command: "save_app_config", args: { config } }
    ]);
    expect(JSON.stringify(config)).not.toContain("apiKey");
  });

  it("sends a transient secret once and returns only normalized status", async () => {
    const calls: Array<{ command: string; args: unknown }> = [];
    const api = createSettingsApi({
      invoke: async (command, args) => {
        calls.push({ command, args });
        return {
          provider_id: "minimax",
          configured: true,
          masked_tail: "9xyz",
          secret: "provider-fixture-key"
        };
      },
      listen: async () => () => undefined
    });

    const status = await api.saveProviderSecret("minimax", "provider-fixture-key");

    expect(status).toEqual({
      providerId: "minimax",
      configured: true,
      maskedTail: "9xyz"
    });
    expect(JSON.stringify(status)).not.toContain("provider-fixture-key");
    expect(calls).toEqual([
      {
        command: "save_provider_secret",
        args: { providerId: "minimax", secret: "provider-fixture-key" }
      }
    ]);
  });

  it("queries and deletes by normalized provider id", async () => {
    const calls: Array<{ command: string; args: unknown }> = [];
    const api = createSettingsApi({
      invoke: async (command, args) => {
        calls.push({ command, args });
        return { provider_id: "minimax", configured: false, masked_tail: null };
      },
      listen: async () => () => undefined
    });

    await expect(api.getProviderSecretStatus("MiniMax")).resolves.toMatchObject({
      providerId: "minimax",
      configured: false
    });
    await expect(api.deleteProviderSecret("MiniMax")).resolves.toMatchObject({
      providerId: "minimax",
      configured: false
    });
    expect(calls).toEqual([
      { command: "provider_secret_status", args: { providerId: "minimax" } },
      { command: "delete_provider_secret", args: { providerId: "minimax" } }
    ]);
  });

  it("normalizes legacy history consent and filters invalid plugin values", async () => {
    const api = createSettingsApi({
      invoke: async () => ({
        version: 1,
        history_enabled: true,
        history_redaction: "none",
        enabled_plugins: ["translator", "history-sqlite", "../unsafe"],
        api_key: "history-fixture-key"
      }),
      listen: async () => () => undefined
    });

    await expect(api.loadConfig()).resolves.toMatchObject({
      version: 2,
      history_enabled: false,
      history_redaction: "secrets",
      enabled_plugins: ["translator"]
    });
    await expect(api.loadConfig()).resolves.not.toHaveProperty("api_key");
  });

  it("preserves explicit v2 history policy and removes duplicate plugins", async () => {
    const api = createSettingsApi({
      invoke: async () => ({
        version: 2,
        history_enabled: true,
        privacy_mode: true,
        history_redaction: "none",
        enabled_plugins: ["markdown-preview", "translator", "translator"]
      }),
      listen: async () => () => undefined
    });

    await expect(api.loadConfig()).resolves.toMatchObject({
      version: 2,
      history_enabled: true,
      privacy_mode: true,
      history_redaction: "none",
      enabled_plugins: ["translator", "markdown-preview"]
    });
  });

  it("drops an unknown extension when it contains nested secret-like fields", async () => {
    const api = createSettingsApi({
      invoke: async () => ({
        version: 2,
        future_flag: true,
        future_provider: {
          credentials: { token: "history-fixture-key" }
        }
      }),
      listen: async () => () => undefined
    });

    const normalized = await api.loadConfig();

    expect(normalized.future_flag).toBe(true);
    expect(normalized).not.toHaveProperty("future_provider");
    expect(JSON.stringify(normalized)).not.toContain("history-fixture-key");
  });

  it("normalizes non-sensitive provider endpoints and discovered model candidates", async () => {
    const api = createSettingsApi({
      invoke: async () => ({
        version: 2,
        provider_endpoints: {
          "OpenAI-Responses": "https://api.example.test/v1/",
          unsafe: "https://user:pass@example.test"
        },
        provider_models: {
          "OpenAI-Responses": ["model-a", "model-a", "model-b"],
          invalid: ["\u0000bad"]
        }
      }),
      listen: async () => () => undefined
    });

    await expect(api.loadConfig()).resolves.toMatchObject({
      provider_endpoints: { "openai-responses": "https://api.example.test/v1" },
      provider_models: { "openai-responses": ["model-a", "model-b"] }
    });
  });
});
