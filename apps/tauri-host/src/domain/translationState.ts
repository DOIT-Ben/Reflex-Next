import type { CurrentResult } from "./hostState";

export type TranslationTarget = "auto" | "zh" | "en";
export type TranslationLanguage = "zh" | "en";
export type TranslationPhase =
  | "closed"
  | "idle"
  | "streaming"
  | "completed"
  | "cancelled"
  | "error";

export type TranslationState = {
  phase: TranslationPhase;
  request: number;
  sourceText: string;
  translatedText: string;
  target: TranslationTarget;
  sourceLanguage: TranslationLanguage | null;
  targetLanguage: TranslationLanguage | null;
  error: string | null;
};

export type TranslationRoute = Pick<CurrentResult, "provider" | "model">;

export function createTranslationState(): TranslationState {
  return {
    phase: "closed",
    request: 0,
    sourceText: "",
    translatedText: "",
    target: "auto",
    sourceLanguage: null,
    targetLanguage: null,
    error: null
  };
}

export function openTranslation(state: TranslationState, sourceText: string): TranslationState {
  const normalized = sanitizeVisibleText(sourceText).trim();
  if (!normalized) return state;
  return {
    ...createTranslationState(),
    request: state.request,
    phase: "idle",
    sourceText: normalized
  };
}

export function selectTranslationTarget(
  state: TranslationState,
  target: string
): TranslationState {
  if (state.phase === "streaming" || !isTarget(target) || target === state.target) return state;
  return {
    ...state,
    phase: "idle",
    target,
    translatedText: "",
    sourceLanguage: null,
    targetLanguage: null,
    error: null
  };
}

export function startTranslation(
  state: TranslationState
): { state: TranslationState; request: number } {
  const request = state.request + 1;
  return {
    request,
    state: {
      ...state,
      phase: "streaming",
      request,
      translatedText: "",
      sourceLanguage: null,
      targetLanguage: null,
      error: null
    }
  };
}

export function appendTranslationChunk(
  state: TranslationState,
  request: number,
  value: unknown
): TranslationState {
  if (state.phase !== "streaming" || state.request !== request || typeof value !== "string") {
    return state;
  }
  const chunk = sanitizeVisibleText(value);
  return chunk ? { ...state, translatedText: state.translatedText + chunk } : state;
}

export function completeTranslation(
  state: TranslationState,
  request: number,
  value: unknown
): TranslationState {
  if (state.request !== request || state.phase === "closed" || !isRecord(value)) return state;
  const text = typeof value.text === "string" ? sanitizeVisibleText(value.text).trim() : "";
  if (
    !text ||
    text.length > 1_000_000 ||
    !isLanguage(value.source_language) ||
    !isLanguage(value.target_language)
  ) {
    return { ...state, phase: "error", error: "翻译结果不可用，请重试。" };
  }
  return {
    ...state,
    phase: "completed",
    translatedText: text,
    sourceLanguage: value.source_language,
    targetLanguage: value.target_language,
    error: null
  };
}

export function cancelTranslation(
  state: TranslationState,
  request: number
): TranslationState {
  return state.request === request && state.phase !== "closed"
    ? { ...state, phase: "cancelled", error: null }
    : state;
}

export function failTranslation(
  state: TranslationState,
  request: number,
  message: string
): TranslationState {
  return state.request === request && state.phase !== "closed"
    ? { ...state, phase: "error", error: message }
    : state;
}

export function closeTranslation(state: TranslationState): TranslationState {
  return { ...createTranslationState(), request: state.request + 1 };
}

export function buildTranslationInput(
  state: TranslationState,
  current: Partial<TranslationRoute>,
  fallback: Partial<TranslationRoute>
): Record<string, unknown> | null {
  if (state.phase === "closed" || !state.sourceText) return null;
  return {
    text: state.sourceText,
    target: state.target,
    provider: current.provider ?? fallback.provider ?? null,
    model: current.model ?? fallback.model ?? null
  };
}

export function translationErrorMessage(code: unknown): string {
  if (code === "provider_unconfigured") return "请先在设置中配置当前 Provider。";
  if (code === "provider_auth_failed" || code === "provider_authentication_failed") {
    return "Provider 认证失败，请检查 API Key。";
  }
  if (code === "provider_rate_limited") return "Provider 请求较多，请稍后重试。";
  if (code === "provider_timeout" || code === "provider_network_error") {
    return "模型服务响应超时，请重试。";
  }
  if (code === "plugin_disabled") return "翻译功能已关闭，可在设置中重新启用。";
  if (code === "provider_empty_response") return "模型没有返回可用译文，请重试。";
  return "翻译暂时不可用，请重试。";
}

function sanitizeVisibleText(value: string): string {
  const normalized = value.replace(/\r\n?/g, "\n").replace(/\0/g, "");
  return Array.from(normalized)
    .filter((character) => character === "\n" || character === "\t" || character >= " ")
    .join("");
}

function isTarget(value: unknown): value is TranslationTarget {
  return value === "auto" || value === "zh" || value === "en";
}

function isLanguage(value: unknown): value is TranslationLanguage {
  return value === "zh" || value === "en";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
