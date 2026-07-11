export type MarkdownPreviewPhase = "closed" | "loading" | "completed" | "error";
export type MarkdownPreviewMode = "split" | "source" | "preview";

export interface MarkdownPreviewState {
  phase: MarkdownPreviewPhase;
  mode: MarkdownPreviewMode;
  sourceText: string;
  html: string;
  error: string | null;
  request: number;
}

const unsafeHtml = /<(?:script|style|iframe|object|embed|img|svg|math)\b|\son[a-z]+\s*=|\sstyle\s*=|javascript\s*:/i;

export function createMarkdownPreviewState(): MarkdownPreviewState {
  return { phase: "closed", mode: "split", sourceText: "", html: "", error: null, request: 0 };
}

export function openMarkdownPreview(
  state: MarkdownPreviewState,
  sourceText: string
): MarkdownPreviewState {
  const source = typeof sourceText === "string" ? sourceText.trim() : "";
  if (!source || source.length > 1_000_000) return state;
  return { ...state, phase: "loading", sourceText: source, html: "", error: null, request: state.request + 1 };
}

export function completeMarkdownPreview(
  state: MarkdownPreviewState,
  request: number,
  value: unknown
): MarkdownPreviewState {
  if (state.phase === "closed" || request !== state.request || !value || typeof value !== "object") return state;
  const html = (value as { html?: unknown }).html;
  if (typeof html !== "string" || html.length > 2_000_000 || unsafeHtml.test(html)) {
    return failMarkdownPreview(state, request);
  }
  return { ...state, phase: "completed", html, error: null };
}

export function failMarkdownPreview(
  state: MarkdownPreviewState,
  request: number
): MarkdownPreviewState {
  if (state.phase === "closed" || request !== state.request) return state;
  return { ...state, phase: "error", html: "", error: "Markdown 预览暂时不可用，请重试。" };
}

export function selectMarkdownPreviewMode(
  state: MarkdownPreviewState,
  mode: MarkdownPreviewMode
): MarkdownPreviewState {
  return ["split", "source", "preview"].includes(mode) ? { ...state, mode } : state;
}

export function closeMarkdownPreview(state: MarkdownPreviewState): MarkdownPreviewState {
  return { ...createMarkdownPreviewState(), mode: state.mode, request: state.request };
}
