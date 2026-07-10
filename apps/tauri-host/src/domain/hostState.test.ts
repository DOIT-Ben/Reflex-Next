import { describe, expect, it } from "vitest";
import {
  applyCoreEnvelope,
  applyAdjustDraft,
  applyClipboardError,
  applyClipboardText,
  applySettingsDraft,
  cancelGeneration,
  cancelAdjust,
  cancelSettings,
  createHostState,
  createRequestDraft,
  openAdjust,
  openSettings,
  resolveHostShortcut,
  retryAfterError,
  startGeneration,
  updateInput
} from "./hostState";

describe("host state", () => {
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

    expect(resolveHostShortcut(ready, { key: "Enter", ctrlKey: true })).toBe("generate");
    expect(resolveHostShortcut(generating, { key: "Enter", ctrlKey: true })).toBe("none");
    expect(resolveHostShortcut(generating, { key: "Escape" })).toBe("cancel_generation");
    expect(resolveHostShortcut(withOverlay, { key: "Escape" })).toBe("close_overlay");
    expect(resolveHostShortcut(settings, { key: "Escape" })).toBe("close_overlay");
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
          message: "模型服务暂时不可用 Bearer sk-1234567890abcdef",
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
      default_provider: "MiniMax",
      default_model: "abab6.5",
      default_mode: "content",
      default_style: "balanced",
      scene_policy: "auto",
      clipboard_policy: "manual"
    });
    expect(settings).not.toHaveProperty("apiKey");

    const saved = applySettingsDraft(settings, {
      default_provider: "MiniMax",
      default_model: "abab6.5-chat",
      default_mode: "prompt",
      default_style: "creative",
      scene_policy: "ask",
      clipboard_policy: "manual"
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

  it("creates an OptimizeRequest draft from host state", () => {
    const state = applyAdjustDraft(openAdjust(updateInput(createHostState(), "写一封邮件")), {
      mode: "content",
      style: "concise",
      scene: "email",
      scene_policy: "manual",
      provider: "MiniMax",
      model: "abab6.5"
    });

    expect(createRequestDraft(state)).toEqual({
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
        surface: "quick-panel"
      }
    });
  });
});
