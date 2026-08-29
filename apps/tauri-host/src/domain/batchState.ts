import type { OptimizeStyle } from "./reflexSession";

export type BatchFormat = "csv" | "txt";
export type BatchItemStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type BatchPhase = "closed" | "idle" | "parsing" | "ready" | "running" | "cancelled" | "completed" | "error";

export type BatchItem = {
  id: number;
  prompt: string;
  status: BatchItemStatus;
  result: string;
  error: string | null;
};

export type BatchState = {
  phase: BatchPhase;
  request: number;
  format: BatchFormat;
  sourceText: string;
  items: BatchItem[];
  style: OptimizeStyle;
  scene: string | null;
  concurrency: number;
  error: string | null;
};

export type BatchParseStart = { state: BatchState; request: number };

const MAX_ITEMS = 200;

export function createBatchState(): BatchState {
  return {
    phase: "closed",
    request: 0,
    format: "txt",
    sourceText: "",
    items: [],
    style: "balanced",
    scene: null,
    concurrency: 1,
    error: null
  };
}

export function openBatch(state: BatchState): BatchState {
  if (state.phase !== "closed") return state;
  return { ...state, phase: state.items.length ? "ready" : "idle", error: null };
}

export function closeBatch(state: BatchState): BatchState {
  return {
    ...state,
    phase: "closed",
    request: state.request + 1,
    error: null,
    items: state.items.map((item) =>
      item.status === "pending" || item.status === "running"
        ? { ...item, status: "cancelled", error: null }
        : item
    )
  };
}

export function setBatchFormat(state: BatchState, format: BatchFormat): BatchState {
  if (state.phase === "parsing" || state.phase === "running" || (format !== "csv" && format !== "txt")) {
    return state;
  }
  if (state.format === format) return { ...state, error: null };
  return {
    ...state,
    phase: state.phase === "closed" ? "closed" : "idle",
    format,
    items: [],
    error: null
  };
}

export function setBatchSourceText(state: BatchState, sourceText: string): BatchState {
  if (state.phase === "parsing" || state.phase === "running") return state;
  return {
    ...state,
    phase: state.phase === "closed" ? "closed" : "idle",
    sourceText: sourceText.slice(0, 2_000_000),
    items: [],
    error: null
  };
}

export function setBatchStyle(state: BatchState, style: OptimizeStyle): BatchState {
  if (state.phase === "running") return state;
  return { ...state, style };
}

export function setBatchScene(state: BatchState, scene: string | null): BatchState {
  if (state.phase === "running") return state;
  return { ...state, scene: scene?.trim() || null };
}

export function setBatchConcurrency(state: BatchState, value: number): BatchState {
  if (state.phase === "running") return state;
  return { ...state, concurrency: normalizeConcurrency(value) };
}

export function beginBatchParse(state: BatchState): BatchParseStart | null {
  if (state.phase === "closed" || state.phase === "parsing" || state.phase === "running" || !state.sourceText.trim()) {
    return null;
  }
  const request = state.request + 1;
  return { state: { ...state, phase: "parsing", request, error: null }, request };
}

export function completeBatchParse(state: BatchState, request: number, data: unknown): BatchState {
  if (state.phase !== "parsing" || state.request !== request) return state;
  const items = parseItems(data);
  if (!items) return { ...state, phase: "error", error: "导入内容格式不正确，请检查后重试。" };
  return { ...state, phase: "ready", items, error: null };
}

export function failBatchParse(state: BatchState, request: number, message: string): BatchState {
  if (state.phase !== "parsing" || state.request !== request) return state;
  return { ...state, phase: "error", error: message };
}

export function beginBatchRun(state: BatchState): BatchParseStart | null {
  if (state.phase === "closed" || state.phase === "parsing" || state.phase === "running" || !state.items.length) {
    return null;
  }
  const request = state.request + 1;
  return {
    request,
    state: {
      ...state,
      phase: "running",
      request,
      error: null,
      items: state.items.map((item) => ({ ...item, status: "pending", result: "", error: null }))
    }
  };
}

export function startBatchItem(state: BatchState, request: number, id: number): BatchState {
  if (state.phase !== "running" || state.request !== request) return state;
  return updateItem(state, id, (item) =>
    item.status === "pending" ? { ...item, status: "running" } : item
  );
}

export function completeBatchItem(state: BatchState, request: number, id: number, result: string): BatchState {
  if (state.phase !== "running" || state.request !== request) return state;
  const normalized = normalizeText(result);
  return updateItem(state, id, (item) =>
    item.status === "running"
      ? normalized
        ? { ...item, status: "completed", result: normalized, error: null }
        : { ...item, status: "failed", error: "未收到可用结果。" }
      : item
  );
}

export function failBatchItem(state: BatchState, request: number, id: number, message: string): BatchState {
  if (state.phase !== "running" || state.request !== request) return state;
  return updateItem(state, id, (item) =>
    item.status === "running" ? { ...item, status: "failed", error: message, result: "" } : item
  );
}

export function cancelBatch(state: BatchState): BatchState {
  if (state.phase !== "running") return state;
  return {
    ...state,
    phase: "cancelled",
    request: state.request + 1,
    items: state.items.map((item) =>
      item.status === "pending" || item.status === "running"
        ? { ...item, status: "cancelled", error: null }
        : item
    )
  };
}

export function finalizeBatchRun(state: BatchState, request: number): BatchState {
  if (state.phase !== "running" || state.request !== request) return state;
  return { ...state, phase: "completed" };
}

export function batchCompletedCount(state: BatchState): number {
  return state.items.filter((item) => item.status === "completed").length;
}

export function batchProcessedCount(state: BatchState): number {
  return state.items.filter((item) => item.status !== "pending" && item.status !== "running").length;
}

export function batchCanExport(state: BatchState): boolean {
  return state.items.some((item) => item.status === "completed");
}

export async function runBatchWorkerPool<T>(
  items: readonly T[],
  concurrency: number,
  signal: AbortSignal,
  worker: (item: T) => Promise<void>
): Promise<void> {
  let next = 0;
  const workerCount = Math.min(normalizeConcurrency(concurrency), items.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (!signal.aborted) {
        const index = next;
        next += 1;
        if (index >= items.length) return;
        await worker(items[index]);
      }
    })
  );
}

export function normalizeConcurrency(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(4, Math.max(1, Math.trunc(value)));
}

function parseItems(data: unknown): BatchItem[] | null {
  if (!isRecord(data) || !Array.isArray(data.items) || !data.items.length || data.items.length > MAX_ITEMS) return null;
  const seen = new Set<number>();
  const items: BatchItem[] = [];
  for (const value of data.items) {
    if (!isRecord(value)) return null;
    const id = value.id;
    if (typeof id !== "number" || !Number.isInteger(id) || id < 1 || seen.has(id)) return null;
    const prompt = normalizeText(value.prompt);
    if (!prompt) return null;
    seen.add(id);
    items.push({ id, prompt, status: "pending", result: "", error: null });
  }
  return items;
}

function updateItem(state: BatchState, id: number, update: (item: BatchItem) => BatchItem): BatchState {
  const index = state.items.findIndex((item) => item.id === id);
  if (index < 0) return state;
  const items = [...state.items];
  items[index] = update(items[index]);
  return { ...state, items };
}

function normalizeText(value: unknown): string {
  return typeof value === "string"
    ? value.replace(/\u0000/g, "").replace(/\r\n?/g, "\n").split("\n").map((line) => line.trimEnd()).join("\n").trim()
    : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
