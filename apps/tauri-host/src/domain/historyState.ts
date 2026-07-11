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

function cleanQuery(query: HistoryQuery): HistoryQuery {
  return Object.fromEntries(Object.entries(query).filter(([, value]) => typeof value === "string" && value.trim())) as HistoryQuery;
}
