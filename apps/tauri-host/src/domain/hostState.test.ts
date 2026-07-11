import { describe, expect, it } from "vitest";
import {
  applyCoreEnvelope,
  applyHostAction,
  applyAdjustDraft,
  applyClipboardError,
  applyClipboardText,
  applyPersistedConfig,
  applySettingsDraft,
  applySceneSelection,
  cancelGeneration,
  cancelAdjust,
  cancelSettings,
  configFromSettingsDraft,
  createDefaultSettingsDraft,
  createHostState,
  createRequestDraft,
  openAdjust,
  openSettings,
  resolveHostShortcut,
  retryAfterError,
  startGeneration,
  settingsDraftFromConfig,
  updateHistorySettingsDraft,
  updateInput,
  updatePluginSettingsDraft,
  type HostSettingsDraft
} from "./hostState";
import type { AppConfig } from "./settingsApi";

const persistedConfig: AppConfig = {
  version: 2,
  provider: "minimax",
  model: "MiniMax-M2.7-highspeed",
  mode: "prompt",
  style: "creative",
  scene_policy: "ask",
  clipboard_policy: "manual",
  clipboard_replace_confirmed: false,
  history_enabled: true,
  privacy_mode: false,
  history_redaction: "none",
  enabled_plugins: ["translator"],
  language: "zh-CN",
  theme: "system",
  hotkey: "Ctrl+Alt+R",
  tls_verify: true,
  ca_bundle_path: null
};

describe("host state", () => {
  it("builds the App initial settings draft with safe history defaults", () => {
    const draft = createDefaultSettingsDraft(createHostState().requestDraft);

    expect(draft).toEqual({
      default_provider: "minimax",
      default_model: "MiniMax-M2.7-highspeed",
      default_mode: "content",
      default_style: "balanced",
      scene_policy: "auto",
      clipboard_policy: "manual",
      hotkey: "Ctrl+Alt+R",
      history_enabled: false,
      privacy_mode: false,
      history_redaction: "secrets",
      enabled_plugins: ["translator", "markdown-preview"]
    });
  });

  it("round-trips every App settings field through hydrate save and cancel data paths", () => {
    const hydrated = settingsDraftFromConfig(persistedConfig);
    const edited: HostSettingsDraft = {
      ...hydrated,
      history_enabled: false,
      privacy_mode: true,
      history_redaction: "secrets",
      enabled_plugins: ["markdown-preview"]
    };

    const saved = configFromSettingsDraft(
      { ...persistedConfig, future_flag: true },
      edited
    );
    const cancelledBackToPersisted = settingsDraftFromConfig(saved);

    expect(hydrated).toMatchObject({
      history_enabled: true,
      privacy_mode: false,
      history_redaction: "none",
      enabled_plugins: ["translator"]
    });
    expect(saved).toMatchObject({
      history_enabled: false,
      privacy_mode: true,
      history_redaction: "secrets",
      enabled_plugins: ["markdown-preview"],
      future_flag: true
    });
    expect(cancelledBackToPersisted).toEqual(edited);
  });

  it("updates history and privacy controls without dropping other draft fields", () => {
    const hydrated = settingsDraftFromConfig(persistedConfig);

    const updated = updateHistorySettingsDraft(hydrated, {
      history_enabled: false,
      privacy_mode: true,
      history_redaction: "secrets"
    });

    expect(updated).toEqual({
      ...hydrated,
      history_enabled: false,
      privacy_mode: true,
      history_redaction: "secrets"
    });
    expect(hydrated).toMatchObject({
      history_enabled: true,
      privacy_mode: false,
      history_redaction: "none"
    });
  });

  it("toggles only supported plugins in stable configuration order", () => {
    const hydrated = settingsDraftFromConfig(persistedConfig);
    const markdownEnabled = updatePluginSettingsDraft(
      hydrated,
      "markdown-preview",
      true
    );
    const translatorDisabled = updatePluginSettingsDraft(
      markdownEnabled,
      "translator",
      false
    );
    const invalidIgnored = updatePluginSettingsDraft(
      translatorDisabled,
      "../unsafe",
      true
    );

    expect(markdownEnabled.enabled_plugins).toEqual([
      "translator",
      "markdown-preview"
    ]);
    expect(translatorDisabled.enabled_plugins).toEqual(["markdown-preview"]);
    expect(invalidIgnored).toEqual(translatorDisabled);
    expect(hydrated.enabled_plugins).toEqual(["translator"]);
  });

  it("moves between empty and ready from input text", () => {
    let state = createHostState();

    expect(state.phase).toBe("empty");

    state = updateInput(state, "帮我把这段产品说明改得更清晰。");
    expect(state.phase).toBe("ready");
    expect(state.canGenerate).toBe(true);

    state = updateInput(state, "   ");
    expect(state.phase).toBe("empty");
    expect(state.canGenerate).toBe(false);
  });

  it("applies explicit clipboard text without keeping stale errors", () => {
    const failed = applyClipboardError(createHostState(), "无法读取剪贴板，请确认权限后重试。");

    const next = applyClipboardText(failed, "从剪贴板读取的一段产品说明。");

    expect(next.inputText).toBe("从剪贴板读取的一段产品说明。");
    expect(next.phase).toBe("ready");
    expect(next.canGenerate).toBe(true);
    expect(next.inputNotice).toBeNull();
  });

  it("stores a safe clipboard error without changing the current input", () => {
    const ready = updateInput(createHostState(), "原有内容");

    const next = applyClipboardError(ready, "无法读取剪贴板，请确认权限后重试。");

    expect(next.inputText).toBe("原有内容");
    expect(next.phase).toBe("ready");
    expect(next.canGenerate).toBe(true);
    expect(next.inputNotice).toBe("无法读取剪贴板，请确认权限后重试。");
  });

  it("opens adjust with a draft and applies changes back to the request draft", () => {
    const state = updateInput(createHostState(), "整理这段话");
    const adjusting = openAdjust(state);

    expect(adjusting.phase).toBe("adjusting");
    expect(adjusting.adjustDraft?.style).toBe("balanced");

    const applied = applyAdjustDraft(adjusting, {
      mode: "prompt",
      style: "creative",
      scene: "email",
      scene_policy: "manual",
      provider: "MiniMax",
      model: "abab6.5"
    });

    expect(applied.phase).toBe("ready");
    expect(applied.requestDraft).toMatchObject({
      mode: "prompt",
      style: "creative",
      scene: "email",
      scene_policy: "manual",
      provider: "MiniMax",
      model: "abab6.5"
    });
  });

  it("cancels adjust without mutating the active request draft", () => {
    const state = openAdjust(updateInput(createHostState(), "整理这段话"));
    const cancelled = cancelAdjust(state);

    expect(cancelled.phase).toBe("ready");
    expect(cancelled.requestDraft.style).toBe("balanced");
    expect(cancelled.adjustDraft).toBeNull();
  });

  it("maps core events to stable host phases", () => {
    let state = startGeneration(updateInput(createHostState(), "写一封邮件"), "req-1");

    state = applyCoreEnvelope(state, {
      version: 1,
      request_id: "req-1",
      event: { type: "status", data: { phase: "analyzing_scene", message: "正在分析场景" } }
    });
    expect(state.phase).toBe("analyzing_scene");

    state = applyCoreEnvelope(state, {
      version: 1,
      request_id: "req-1",
      event: { type: "request", data: { provider: "mock", model: "mock-stream" } }
    });
    expect(state.phase).toBe("connecting_provider");

    state = applyCoreEnvelope(state, {
      version: 1,
      request_id: "req-1",
      event: { type: "chunk", data: { text: "第一段" } }
    });
    expect(state.phase).toBe("streaming");

    state = applyCoreEnvelope(state, {
      version: 1,
      request_id: "req-1",
      event: { type: "done", data: { text: "完成内容", scene: "email" } }
    });
    expect(state.phase).toBe("completed");
    expect(state.output).toBe("完成内容");
  });

  it("drops stale events from an older request id", () => {
    const state = startGeneration(updateInput(createHostState(), "写一封邮件"), "active");
    const next = applyCoreEnvelope(state, {
      version: 1,
      request_id: "old",
      event: { type: "done", data: { text: "旧结果" } }
    });

    expect(next).toBe(state);
    expect(next.output).toBe("");
  });

  it("returns to the executable input state after cancelling a generation", () => {
    const ready = updateInput(createHostState(), "写一封邮件");
    const generating = startGeneration(ready, "req-1");

    const cancelled = cancelGeneration(generating);

    expect(cancelled.phase).toBe("ready");
    expect(cancelled.activeRequestId).toBeNull();
    expect(cancelled.canGenerate).toBe(true);
    expect(cancelled.output).toBe("");
  });

  it("resolves window shortcuts without starting duplicate generations", () => {
    const ready = updateInput(createHostState(), "写一封邮件");
    const generating = startGeneration(ready, "req-1");
    const adjusting = openAdjust(ready);
    const withOverlay = { ...ready, overlay: "clipboard_confirm" as const };
    const settings = openSettings(ready);
    const plugins = { ...ready, overlay: "plugin_manager" as const };

    expect(resolveHostShortcut(ready, { key: "Enter", ctrlKey: true })).toBe("generate");
    expect(resolveHostShortcut(generating, { key: "Enter", ctrlKey: true })).toBe("none");
    expect(resolveHostShortcut(generating, { key: "Escape" })).toBe("cancel_generation");
    expect(resolveHostShortcut(withOverlay, { key: "Escape" })).toBe("close_overlay");
    expect(resolveHostShortcut(settings, { key: "Escape" })).toBe("close_overlay");
    expect(resolveHostShortcut(withOverlay, { key: "Enter", ctrlKey: true })).toBe("none");
    expect(resolveHostShortcut(settings, { key: "Enter", ctrlKey: true })).toBe("none");
    expect(resolveHostShortcut(plugins, { key: "Enter", ctrlKey: true })).toBe("none");
    expect(resolveHostShortcut(adjusting, { key: "Escape" })).toBe("leave_adjust");
    expect(resolveHostShortcut(ready, { key: "Escape" })).toBe("hide_window");
  });

  it("stores recoverable error details without leaking secrets", () => {
    const generating = startGeneration(updateInput(createHostState(), "写一封邮件"), "req-1");

    const failed = applyCoreEnvelope(generating, {
      version: 1,
      request_id: "req-1",
      event: {
        type: "error",
        data: {
          code: "provider_unavailable",
          message: "模型服务暂时不可用 Bearer sk-history-fixture-key",
          recoverable: true,
          action: "retry",
          diagnostic_id: "diag-42"
        }
      }
    });

    expect(failed.phase).toBe("error");
    expect(failed.activeRequestId).toBeNull();
    expect(failed.errorMessage).toBe("模型服务暂时不可用 Bearer [已隐藏]");
    expect(failed.errorCode).toBe("provider_unavailable");
    expect(failed.errorRecoverable).toBe(true);
    expect(failed.errorAction).toBe("retry");
    expect(failed.diagnosticId).toBe("diag-42");

    const ready = retryAfterError(failed);
    expect(ready.phase).toBe("ready");
    expect(ready.errorMessage).toBeNull();
    expect(ready.canGenerate).toBe(true);
  });

  it("opens settings as an overlay and saves defaults without storing secrets", () => {
    const ready = updateInput(createHostState(), "写一封邮件");
    const settings = openSettings(ready);

    expect(settings.phase).toBe("ready");
    expect(settings.overlay).toBe("settings");
    expect(settings.settingsDraft).toMatchObject({
      default_provider: "minimax",
      default_model: "MiniMax-M2.7-highspeed",
      default_mode: "content",
      default_style: "balanced",
      scene_policy: "auto",
      clipboard_policy: "manual",
      hotkey: "Ctrl+Alt+R",
      history_enabled: false,
      privacy_mode: false,
      history_redaction: "secrets",
      enabled_plugins: ["translator", "markdown-preview"]
    });
    expect(settings).not.toHaveProperty("apiKey");

    const saved = applySettingsDraft(settings, {
      default_provider: "MiniMax",
      default_model: "abab6.5-chat",
      default_mode: "prompt",
      default_style: "creative",
      scene_policy: "ask",
      clipboard_policy: "manual",
      hotkey: "Ctrl+Shift+K",
      history_enabled: true,
      privacy_mode: true,
      history_redaction: "none",
      enabled_plugins: ["translator"]
    });

    expect(saved.overlay).toBeNull();
    expect(saved.requestDraft).toMatchObject({
      mode: "prompt",
      style: "creative",
      scene_policy: "ask",
      provider: "MiniMax",
      model: "abab6.5-chat"
    });
    expect(createRequestDraft(saved)).toMatchObject({
      mode: "prompt",
      style: "creative",
      scene_policy: "ask",
      provider: "MiniMax",
      model: "abab6.5-chat"
    });

    expect(cancelSettings(settings).overlay).toBeNull();
  });

  it("applies persisted config to requests without adding secret state", () => {
    const state = applyPersistedConfig(createHostState(), persistedConfig);

    expect(state.requestDraft).toMatchObject({
      provider: "minimax",
      model: "MiniMax-M2.7-highspeed",
      mode: "prompt",
      style: "creative",
      scene_policy: "ask"
    });
    expect(state).not.toHaveProperty("apiKey");
    expect(JSON.stringify(state)).not.toContain("secret");
    expect(state.providerSummary).toBe("MiniMax");
  });

  it("creates an OptimizeRequest draft from host state", () => {
    const state = applyAdjustDraft(openAdjust(updateInput(createHostState(), "写一封邮件")), {
      mode: "content",
      style: "concise",
      scene: "email",
      scene_policy: "manual",
      provider: "MiniMax",
      model: "abab6.5"
    });

    expect(createRequestDraft(state, "en-US")).toEqual({
      text: "写一封邮件",
      mode: "content",
      style: "concise",
      scene: "email",
      scene_policy: "manual",
      provider: "MiniMax",
      model: "abab6.5",
      stream: true,
      metadata: {
        host: "tauri",
        surface: "quick-panel",
        language: "en-US"
      }
    });
  });

  it("makes automatic and concrete scene selection explicit", () => {
    const initial = createHostState().requestDraft;

    expect(applySceneSelection(initial, "")).toMatchObject({
      scene: null,
      scene_policy: "auto"
    });
    expect(applySceneSelection(initial, "code_review")).toMatchObject({
      scene: "code_review",
      scene_policy: "manual"
    });
  });

  it("maps tray actions to recent result, settings, and plugin views", () => {
    const ready = updateInput(createHostState(), "待优化内容");

    expect(applyHostAction(ready, "plugins").overlay).toBe("plugin_manager");
    expect(applyHostAction(ready, "settings").overlay).toBe("settings");
    expect(applyHostAction(ready, "recent").inputNotice).toBe("暂无最近结果。");

    const completed = applyCoreEnvelope(startGeneration(ready, "recent-1"), {
      version: 1,
      request_id: "recent-1",
      event: { type: "done", data: { text: "最近生成的结果" } }
    });
    const reopened = applyHostAction({ ...completed, phase: "ready" }, "recent");

    expect(reopened.phase).toBe("completed");
    expect(reopened.output).toBe("最近生成的结果");

    const cancelledNextRun = cancelGeneration(startGeneration(completed, "recent-2"));
    const reopenedAfterCancel = applyHostAction(cancelledNextRun, "recent");

    expect(cancelledNextRun.output).toBe("");
    expect(reopenedAfterCancel.phase).toBe("completed");
    expect(reopenedAfterCancel.output).toBe("最近生成的结果");

    const activeNextRun = startGeneration(completed, "recent-3");
    expect(applyHostAction(activeNextRun, "recent")).toBe(activeNextRun);
  });
});
