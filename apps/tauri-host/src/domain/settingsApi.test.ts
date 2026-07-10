import { describe, expect, it } from "vitest";
import { createSettingsApi, type AppConfig } from "./settingsApi";

const config: AppConfig = {
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
          secret: "must-not-cross-adapter"
        };
      },
      listen: async () => () => undefined
    });

    const status = await api.saveProviderSecret("minimax", "temporary-value");

    expect(status).toEqual({
      providerId: "minimax",
      configured: true,
      maskedTail: "9xyz"
    });
    expect(JSON.stringify(status)).not.toContain("must-not-cross-adapter");
    expect(calls).toEqual([
      {
        command: "save_provider_secret",
        args: { providerId: "minimax", secret: "temporary-value" }
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
});
