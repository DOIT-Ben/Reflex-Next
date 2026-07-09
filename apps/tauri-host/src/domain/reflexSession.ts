export type OptimizeMode = "content" | "prompt";
export type OptimizeStyle = "concise" | "balanced" | "detailed" | "creative";
export type ScenePolicy = "auto" | "manual" | "ask";
export type SessionPhase = "idle" | "running" | "complete" | "failed";

export type OptimizeRequestDraft = {
  text: string;
  mode: OptimizeMode;
  style: OptimizeStyle;
  scene: string | null;
  scene_policy: ScenePolicy;
  provider: string | null;
  model: string | null;
  stream: boolean;
  metadata: {
    host: "tauri";
    surface: "quick-panel";
  };
};

export type CoreEvent = {
  type: "status" | "scene" | "request" | "chunk" | "done" | "error" | "metric";
  data: Record<string, unknown>;
};

export type SceneOption = {
  id: string;
  label: string;
  hint: string;
};

export type DetectedScene = {
  scene: string;
  confidence: number;
  method: string;
};

export type TimelineItem = {
  type: CoreEvent["type"];
  label: string;
};

export type ReflexSession = {
  phase: SessionPhase;
  statusMessage: string;
  detectedScene: DetectedScene | null;
  output: string;
  errorMessage: string | null;
  elapsedSeconds: number | null;
  timeline: TimelineItem[];
};

const sceneOptions: SceneOption[] = [
  { id: "general", label: "通用", hint: "默认回退场景" },
  { id: "article_writing", label: "文章写作", hint: "结构、表达和读者吸引力" },
  { id: "email", label: "邮件", hint: "语气、目标和行动项" },
  { id: "code_generation", label: "代码生成", hint: "需求到实现提示词" },
  { id: "code_review", label: "代码审查", hint: "风险、缺陷和修复建议" },
  { id: "doc_translation", label: "文档翻译", hint: "保留结构与术语" },
  { id: "report_writing", label: "报告写作", hint: "结论、依据和格式" },
  { id: "problem_diagnosis", label: "问题诊断", hint: "事实、假设和下一步" }
];

export function createDraftRequest(text: string): OptimizeRequestDraft {
  return {
    text,
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
  };
}

export function createInitialSession(): ReflexSession {
  return {
    phase: "idle",
    statusMessage: "准备优化",
    detectedScene: null,
    output: "",
    errorMessage: null,
    elapsedSeconds: null,
    timeline: []
  };
}

export function applyCoreEvent(session: ReflexSession, event: CoreEvent): ReflexSession {
  const timeline = [...session.timeline, toTimelineItem(event)];

  if (event.type === "status") {
    return {
      ...session,
      phase: "running",
      statusMessage: stringFrom(event.data.message, "正在处理"),
      timeline
    };
  }

  if (event.type === "scene") {
    return {
      ...session,
      phase: "running",
      detectedScene: {
        scene: stringFrom(event.data.scene, "general"),
        confidence: numberFrom(event.data.confidence, 0),
        method: stringFrom(event.data.method, "unknown")
      },
      statusMessage: "已识别场景",
      timeline
    };
  }

  if (event.type === "chunk") {
    return {
      ...session,
      phase: "running",
      statusMessage: "正在生成",
      output: session.output + stringFrom(event.data.text, ""),
      timeline
    };
  }

  if (event.type === "done") {
    const finalText = stringFrom(event.data.final_text, stringFrom(event.data.text, session.output));
    return {
      ...session,
      phase: "complete",
      statusMessage: "已完成",
      output: finalText,
      elapsedSeconds: numberFrom(event.data.elapsed_seconds, session.elapsedSeconds ?? 0),
      timeline
    };
  }

  if (event.type === "error") {
    return {
      ...session,
      phase: "failed",
      statusMessage: "生成失败",
      errorMessage: redactVisibleError(stringFrom(event.data.message, "模型服务暂时不可用")),
      timeline
    };
  }

  return {
    ...session,
    timeline
  };
}

export function redactVisibleError(message: string): string {
  return message
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, "Bearer [已隐藏]")
    .replace(/(api[_-]?key=)[^\s&]+/gi, "$1[已隐藏]")
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "[已隐藏]");
}

export function listPrototypeScenes(): SceneOption[] {
  return sceneOptions.map((scene) => ({ ...scene }));
}

function toTimelineItem(event: CoreEvent): TimelineItem {
  const labels: Record<CoreEvent["type"], string> = {
    status: stringFrom(event.data.message, "状态更新"),
    scene: `场景：${stringFrom(event.data.scene, "general")}`,
    request: "请求已发送",
    chunk: "收到片段",
    done: "生成完成",
    error: "出现错误",
    metric: "指标更新"
  };

  return {
    type: event.type,
    label: labels[event.type]
  };
}

function stringFrom(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function numberFrom(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
