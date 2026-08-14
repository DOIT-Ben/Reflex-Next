import { describe, expect, it } from "vitest";
import {
  applyCoreEvent,
  createDraftRequest,
  createInitialSession,
  filterSceneOptions,
  listSceneCategories,
  listSceneOptions,
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
        surface: "quick-panel",
        language: "zh-CN"
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

  it("lists all 42 builtin scenes with unique stable ids", () => {
    const scenes = listSceneOptions();

    expect(scenes.map((scene) => scene.id)).toEqual([
      "general",
      "article_writing",
      "social_media",
      "email",
      "ad_creative",
      "product_desc",
      "paper_writing",
      "code_generation",
      "code_review",
      "bug_fix",
      "code_refactor",
      "tech_doc",
      "data_analysis",
      "market_research",
      "competitor_analysis",
      "literature_review",
      "trend_prediction",
      "knowledge_explain",
      "study_plan",
      "exam_prep",
      "course_design",
      "homework_help",
      "report_writing",
      "decision_analysis",
      "project_planning",
      "process_optimization",
      "meeting_summary",
      "story_writing",
      "script_writing",
      "poetry_creation",
      "game_plot",
      "world_building",
      "doc_translation",
      "localization",
      "literary_translation",
      "term_unification",
      "interpreting_notes",
      "problem_diagnosis",
      "solution_generation",
      "root_cause",
      "risk_assessment",
      "emergency_plan"
    ]);
    expect(new Set(scenes.map((scene) => scene.id)).size).toBe(42);
    expect(scenes.every((scene) => scene.label && scene.hint && scene.category)).toBe(true);
  });

  it("groups every builtin scene and supports category-aware search", () => {
    const categories = listSceneCategories();
    const scenes = listSceneOptions();

    expect(categories.map((category) => category.id)).toEqual([
      "general",
      "writing",
      "development",
      "research",
      "learning",
      "work",
      "creative",
      "translation",
      "problem_solving"
    ]);
    expect(new Set(scenes.map((scene) => scene.category))).toEqual(
      new Set(categories.map((category) => category.id))
    );
    expect(filterSceneOptions("代码", "development").map((scene) => scene.id)).toEqual([
      "code_generation",
      "code_review",
      "code_refactor"
    ]);
    expect(filterSceneOptions("email").map((scene) => scene.id)).toEqual(["email"]);
    expect(filterSceneOptions("风险", "translation")).toEqual([]);
  });

  it("adds a whitelisted output language to request metadata", () => {
    expect(createDraftRequest("Translate this", "en-US").metadata.language).toBe("en-US");
  });
});
