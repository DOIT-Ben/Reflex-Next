export type HistorySummary = {
  id: string;
  created_at: string;
  scene: string;
  style: string;
  provider: string;
  rating: number | null;
};

export type HistoryPage = { items: HistorySummary[]; next_cursor: string | null };
export type HistoryQuery = { search?: string; scene?: string; style?: string; provider?: string };
export type HistoryPhase = "loading" | "loading-more" | "empty" | "error" | "ready";
export type HistoryBackup = { id: string; created_at: string; record_count: number };
export type HistoryBackupsState = {
  phase: "loading" | "ready" | "error";
  items: HistoryBackup[];
  selectedId: string;
  request: number;
};

export type HistoryState = {
  phase: HistoryPhase;
  items: HistorySummary[];
  cursor: string | null;
  query: HistoryQuery;
  selectedId: string | null;
  error: string | null;
  request: number;
  detailRequest: number;
  detail: Record<string, unknown> | null;
  operation: { phase: "idle" | "running" | "succeeded" | "failed" | "recovery"; kind: string | null };
};

export function createHistoryState(): HistoryState {
  return { phase: "loading", items: [], cursor: null, query: {}, selectedId: null, error: null, request: 0, detailRequest: 0, detail: null, operation: { phase: "idle", kind: null } };
}

export function createHistoryBackupsState(): HistoryBackupsState {
  return { phase: "loading", items: [], selectedId: "", request: 0 };
}

export function startHistoryBackupsLoad(state: HistoryBackupsState): { state: HistoryBackupsState; request: number } {
  const request = state.request + 1;
  return { request, state: { ...state, phase: "loading", selectedId: "", request } };
}

export function finishHistoryBackupsLoad(state: HistoryBackupsState, request: number, value: unknown): HistoryBackupsState {
  if (state.request !== request) return state;
  const items = normalizeHistoryBackups(value);
  const selectedId = items.some((backup) => backup.id === state.selectedId) ? state.selectedId : items[0]?.id ?? "";
  return { ...state, phase: "ready", items, selectedId };
}

export function failHistoryBackupsLoad(state: HistoryBackupsState, request: number): HistoryBackupsState {
  return state.request === request ? { ...state, phase: "error", items: [], selectedId: "" } : state;
}

export function startHistoryQuery(state: HistoryState, query: HistoryQuery): { state: HistoryState; request: number } {
  const request = state.request + 1;
  return { request, state: { ...state, phase: "loading", items: [], cursor: null, selectedId: null, query: cleanQuery(query), error: null, request } };
}

export function appendHistoryPage(state: HistoryState, request: number, page: HistoryPage): HistoryState {
  if (state.request !== request) return state;
  const known = new Set(state.items.map((item) => item.id));
  const items = [...state.items, ...page.items.filter((item) => !known.has(item.id))];
  return { ...state, items, cursor: page.next_cursor, phase: items.length ? "ready" : "empty", error: null };
}

export function failHistoryQuery(state: HistoryState, request: number, message: string): HistoryState {
  return state.request === request ? { ...state, phase: "error", error: message, cursor: null } : state;
}

export function selectHistoryItem(state: HistoryState, id: string | null): HistoryState {
  return { ...state, selectedId: id && state.items.some((item) => item.id === id) ? id : null, detail: null, detailRequest: state.detailRequest + 1 };
}

export function setHistoryDetail(state: HistoryState, request: number, detail: Record<string, unknown>): HistoryState {
  return state.detailRequest === request && detail.id === state.selectedId ? { ...state, detail } : state;
}

export function applyHistoryDetailFailure(
  state: HistoryState,
  detail: Record<string, unknown> | null,
  expectedId: string,
  expectedRequest: number
): Record<string, unknown> | null {
  if (state.selectedId !== expectedId || state.detailRequest !== expectedRequest) return detail;
  return { error: "无法加载这条历史记录。" };
}

export function applyHistoryDetailTerminal(
  state: HistoryState,
  detail: Record<string, unknown> | null,
  expectedId: string,
  expectedRequest: number,
  status: "error" | "cancelled"
): Record<string, unknown> | null {
  if (status !== "error" && status !== "cancelled") return detail;
  return applyHistoryDetailFailure(state, detail, expectedId, expectedRequest);
}

export function updateHistoryRating(state: HistoryState, id: string, rating: number | null): HistoryState {
  return { ...state, items: state.items.map((item) => item.id === id ? { ...item, rating } : item) };
}

export function startHistoryOperation(state: HistoryState, kind: string): { state: HistoryState; operation: HistoryState["operation"] } {
  const operation = { phase: "running" as const, kind };
  return { state: { ...state, operation }, operation };
}

export function finishHistoryOperation(state: HistoryState, phase: "succeeded" | "failed" | "recovery"): HistoryState {
  return { ...state, operation: { ...state.operation, phase } };
}

export function removeHistoryItem(state: HistoryState, id: string): HistoryState {
  const index = state.items.findIndex((item) => item.id === id);
  const items = state.items.filter((item) => item.id !== id);
  const selectedId = state.selectedId === id ? items[index]?.id ?? items[index - 1]?.id ?? null : state.selectedId;
  return { ...state, items, selectedId, phase: items.length ? "ready" : "empty" };
}

export function historyExportFilters(query: HistoryQuery): Record<string, string> | null {
  if (query.search?.trim()) return null;
  const { scene, style, provider } = cleanQuery(query);
  return Object.fromEntries(Object.entries({ scene, style, provider }).filter(([, value]) => value)) as Record<string, string>;
}

export function historyListInput(query: HistoryQuery, cursor: string | null = null): Record<string, unknown> {
  const { search, scene, style, provider } = cleanQuery(query);
  return {
    ...(search ? { keyword: search } : {}),
    filters: Object.fromEntries(Object.entries({ scene, style, provider }).filter(([, value]) => value)),
    page_size: 30,
    sort: "created_at",
    direction: "desc",
    ...(cursor ? { cursor } : {})
  };
}

export function normalizeHistoryBackups(value: unknown): HistoryBackup[] {
  if (!isRecord(value) || !Array.isArray(value.items)) return [];
  return value.items.flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = item.id;
    const createdAt = item.created_at;
    const recordCount = item.record_count;
    if (typeof id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) return [];
    if (typeof createdAt !== "string" || !createdAt.endsWith("Z") || createdAt.length > 40) return [];
    if (!Number.isInteger(recordCount) || (recordCount as number) < 0) return [];
    return [{ id, created_at: createdAt, record_count: recordCount as number }];
  });
}

export function historyElapsedLabel(detail: Record<string, unknown>): string {
  const elapsed = detail.elapsed_ms;
  return typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0 ? `${Math.round(elapsed)} ms` : "-";
}

export function historyScanMessage(value: unknown): string {
  if (!isRecord(value) || !Number.isInteger(value.corrupted_records) || (value.corrupted_records as number) < 0) {
    return "历史记录检查结果暂时不可用。";
  }
  const corrupted = value.corrupted_records as number;
  return corrupted > 0 ? `发现 ${corrupted} 条需要修复的记录。` : "历史记录检查完成，未发现问题。";
}

export function applyHistoryRatingToDetail(
  state: HistoryState,
  detail: Record<string, unknown> | null,
  expectedId: string,
  expectedRequest: number,
  rating: number
): Record<string, unknown> | null {
  if (!detail || state.selectedId !== expectedId || state.detailRequest !== expectedRequest) return detail;
  return { ...detail, rating };
}

function cleanQuery(query: HistoryQuery): HistoryQuery {
  return Object.fromEntries(
    Object.entries(query).flatMap(([key, value]) => {
      if (typeof value !== "string" || !value.trim()) return [];
      return [[key, value.trim()]];
    })
  ) as HistoryQuery;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
