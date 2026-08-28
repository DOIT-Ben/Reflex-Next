export type OptimizeMode = "content" | "prompt";
export type OptimizeStyle = "concise" | "balanced" | "detailed" | "creative";
export type ScenePolicy = "auto" | "manual" | "ask";
export type OutputLanguage = "zh-CN" | "en-US";
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
    language: OutputLanguage;
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
  category: SceneCategoryId;
};

export type SceneCategoryId =
  | "general"
  | "writing"
  | "development"
  | "research"
  | "learning"
  | "work"
  | "creative"
  | "translation"
  | "problem_solving";

export type SceneCategory = {
  id: SceneCategoryId;
  label: string;
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

const sceneCategories: SceneCategory[] = [
  { id: "general", label: "通用" },
  { id: "writing", label: "内容与沟通" },
  { id: "development", label: "软件研发" },
  { id: "research", label: "研究与分析" },
  { id: "learning", label: "学习与教学" },
  { id: "work", label: "工作与决策" },
  { id: "creative", label: "创意叙事" },
  { id: "translation", label: "翻译与本地化" },
  { id: "problem_solving", label: "问题解决与风险" }
];

const sceneOptions: SceneOption[] = [
  { id: "general", label: "通用", hint: "默认回退场景", category: "general" },
  { id: "article_writing", label: "文章写作", hint: "结构、表达和读者吸引力", category: "writing" },
  { id: "social_media", label: "社媒文案", hint: "平台语气和传播效率", category: "writing" },
  { id: "email", label: "邮件", hint: "语气、目标和行动项", category: "writing" },
  { id: "ad_creative", label: "广告创意", hint: "卖点、记忆点和行动号召", category: "writing" },
  { id: "product_desc", label: "产品描述", hint: "价值、特性和使用场景", category: "writing" },
  { id: "paper_writing", label: "论文写作", hint: "论点、证据和学术表达", category: "research" },
  { id: "code_generation", label: "代码生成", hint: "需求到实现提示词", category: "development" },
  { id: "code_review", label: "代码审查", hint: "风险、缺陷和修复建议", category: "development" },
  { id: "bug_fix", label: "Bug 修复", hint: "复现、根因和验证", category: "development" },
  { id: "code_refactor", label: "代码重构", hint: "保持行为并改善结构", category: "development" },
  { id: "tech_doc", label: "技术文档", hint: "接口、示例和失败行为", category: "development" },
  { id: "data_analysis", label: "数据分析", hint: "指标、方法和结论", category: "research" },
  { id: "market_research", label: "市场调研", hint: "市场、用户和证据", category: "research" },
  { id: "competitor_analysis", label: "竞品分析", hint: "差异、优势和风险", category: "research" },
  { id: "literature_review", label: "文献综述", hint: "研究脉络和证据缺口", category: "research" },
  { id: "trend_prediction", label: "趋势预测", hint: "信号、假设和不确定性", category: "research" },
  { id: "knowledge_explain", label: "知识讲解", hint: "概念、示例和理解路径", category: "learning" },
  { id: "study_plan", label: "学习计划", hint: "目标、节奏和复盘", category: "learning" },
  { id: "exam_prep", label: "考试备考", hint: "考纲、练习和时间安排", category: "learning" },
  { id: "course_design", label: "课程设计", hint: "目标、活动和评价", category: "learning" },
  { id: "homework_help", label: "作业辅导", hint: "思路、步骤和检查", category: "learning" },
  { id: "report_writing", label: "报告写作", hint: "结论、依据和格式", category: "writing" },
  { id: "decision_analysis", label: "决策分析", hint: "选项、权衡和建议", category: "work" },
  { id: "project_planning", label: "项目规划", hint: "范围、里程碑和依赖", category: "work" },
  { id: "process_optimization", label: "流程优化", hint: "步骤、控制和指标", category: "work" },
  { id: "meeting_summary", label: "会议纪要", hint: "决策、行动和负责人", category: "work" },
  { id: "story_writing", label: "故事创作", hint: "人物、冲突和节奏", category: "creative" },
  { id: "script_writing", label: "剧本创作", hint: "场景、对白和镜头", category: "creative" },
  { id: "poetry_creation", label: "诗歌创作", hint: "意象、节奏和语言", category: "creative" },
  { id: "game_plot", label: "游戏剧情", hint: "任务、冲突和反馈", category: "creative" },
  { id: "world_building", label: "世界观构建", hint: "规则、历史和一致性", category: "creative" },
  { id: "doc_translation", label: "文档翻译", hint: "保留结构与术语", category: "translation" },
  { id: "localization", label: "本地化适配", hint: "文化、界面和语境", category: "translation" },
  { id: "literary_translation", label: "文学翻译", hint: "风格、语义和韵律", category: "translation" },
  { id: "term_unification", label: "术语统一", hint: "术语表和一致性", category: "translation" },
  { id: "interpreting_notes", label: "口译笔记", hint: "信息压缩和可读性", category: "translation" },
  { id: "problem_diagnosis", label: "问题诊断", hint: "事实、假设和下一步", category: "problem_solving" },
  { id: "solution_generation", label: "解决方案", hint: "选项、步骤和可行性", category: "problem_solving" },
  { id: "root_cause", label: "根因分析", hint: "证据链和系统原因", category: "problem_solving" },
  { id: "risk_assessment", label: "风险评估", hint: "概率、影响和缓解", category: "problem_solving" },
  { id: "emergency_plan", label: "应急预案", hint: "触发、响应和恢复", category: "problem_solving" }
];

export function createDraftRequest(
  text: string,
  language: OutputLanguage = "zh-CN"
): OptimizeRequestDraft {
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
      surface: "quick-panel",
      language: language === "en-US" ? "en-US" : "zh-CN"
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
    const phase = stringFrom(event.data.phase, "");
    if (phase === "completed") {
      return {
        ...session,
        phase: "complete",
        statusMessage: stringFrom(event.data.message, "已完成"),
        elapsedSeconds: numberFrom(event.data.elapsed_seconds, session.elapsedSeconds ?? 0),
        timeline
      };
    }
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

export function listSceneOptions(): SceneOption[] {
  return sceneOptions.map((scene) => ({ ...scene }));
}

export function listSceneCategories(): SceneCategory[] {
  return sceneCategories.map((category) => ({ ...category }));
}

export function filterSceneOptions(
  query: string,
  category: SceneCategoryId | null = null
): SceneOption[] {
  const normalized = query.trim().toLocaleLowerCase();
  const categoryLabels = new Map(sceneCategories.map((item) => [item.id, item.label]));
  return sceneOptions
    .filter((scene) => !category || scene.category === category)
    .filter((scene) => {
      if (!normalized) return true;
      return [scene.id, scene.label, scene.hint, categoryLabels.get(scene.category) ?? ""]
        .some((value) => value.toLocaleLowerCase().includes(normalized));
    })
    .map((scene) => ({ ...scene }));
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
