import { describe, expect, it } from "vitest";
import {
  applyCoreEnvelope,
  applyAdjustDraft,
  cancelAdjust,
  createHostState,
  createRequestDraft,
  openAdjust,
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
