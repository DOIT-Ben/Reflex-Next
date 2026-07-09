import { describe, expect, it } from "vitest";
import {
  applyCoreEvent,
  createDraftRequest,
  createInitialSession,
  listPrototypeScenes,
  redactVisibleError
} from "./reflexSession";

describe("reflex host session", () => {
  it("creates an OptimizeRequest draft that matches the core contract", () => {
    const draft = createDraftRequest("写一封求职邮件");

    expect(draft).toEqual({
      text: "写一封求职邮件",
      mode: "content",
      style: "balanced",
      scene: null,
      scene_policy: "auto",
      provider: null,
      model: null,
      stream: true,
      metadata: {
        host: "tauri",
        surface: "quick-panel"
      }
    });
  });

  it("renders a core event stream without making routing decisions in the host", () => {
    let session = createInitialSession();

    session = applyCoreEvent(session, {
      type: "status",
      data: { message: "正在分析场景" }
    });
    session = applyCoreEvent(session, {
      type: "scene",
      data: { scene: "email", confidence: 0.82, method: "rule" }
    });
    session = applyCoreEvent(session, {
      type: "chunk",
      data: { text: "您好，" }
    });
    session = applyCoreEvent(session, {
      type: "chunk",
      data: { text: "这是优化后的邮件。" }
    });
    session = applyCoreEvent(session, {
      type: "done",
      data: { final_text: "您好，这是优化后的邮件。", elapsed_seconds: 1.2 }
    });

    expect(session.phase).toBe("complete");
    expect(session.statusMessage).toBe("已完成");
    expect(session.detectedScene?.scene).toBe("email");
    expect(session.output).toBe("您好，这是优化后的邮件。");
    expect(session.timeline.map((item) => item.type)).toEqual([
      "status",
      "scene",
      "chunk",
      "chunk",
      "done"
    ]);
  });

  it("accepts Python sidecar done events that use text as the final output field", () => {
    const session = applyCoreEvent(createInitialSession(), {
      type: "done",
      data: { text: "优化结果", scene: "email" }
    });

    expect(session.phase).toBe("complete");
    expect(session.output).toBe("优化结果");
  });

  it("redacts visible provider errors before showing them in the host", () => {
    expect(redactVisibleError("Bearer sk-1234567890abcdef 请求失败")).toBe(
      "Bearer [已隐藏] 请求失败"
    );
    expect(redactVisibleError("api_key=minimax-secret-token")).toBe(
      "api_key=[已隐藏]"
    );
  });

  it("keeps the prototype scene list aligned with the first migration slice", () => {
    expect(listPrototypeScenes().map((scene) => scene.id)).toEqual([
      "general",
      "article_writing",
      "email",
      "code_generation",
      "code_review",
      "doc_translation",
      "report_writing",
      "problem_diagnosis"
    ]);
  });
});
