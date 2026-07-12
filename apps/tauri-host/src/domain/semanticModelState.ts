import type { PluginEventEnvelope } from "./capabilityBridge";

export type SemanticModelPhase =
  | "idle"
  | "loading"
  | "missing"
  | "ready"
  | "downloading"
  | "deleting"
  | "error";

export type SemanticModelState = {
  phase: SemanticModelPhase;
  modelId: string | null;
  runtimeReady: boolean;
  sizeBytes: number;
  percent: number;
  errorCode: string | null;
};

export function createSemanticModelState(): SemanticModelState {
  return {
    phase: "idle",
    modelId: null,
    runtimeReady: false,
    sizeBytes: 0,
    percent: 0,
    errorCode: null
  };
}

export function beginSemanticModelOperation(
  state: SemanticModelState,
  operation: "status" | "download" | "delete"
): SemanticModelState {
  return {
    ...state,
    phase: operation === "status" ? "loading" : operation === "download" ? "downloading" : "deleting",
    percent: operation === "download" ? 0 : state.percent,
    errorCode: null
  };
}

export function applySemanticModelEvent(
  state: SemanticModelState,
  event: PluginEventEnvelope
): SemanticModelState {
  if (event.status === "progress") {
    const percent = boundedInteger(event.data.percent, 0, 100);
    return { ...state, phase: "downloading", percent };
  }
  if (event.status === "error") {
    return { ...state, phase: "error", errorCode: event.code ?? "plugin_failed" };
  }
  if (event.status !== "result") return state;

  const modelId = stringValue(event.data.model_id);
  const modelState = event.data.model_state;
  const runtimeState = event.data.runtime_state;
  const sizeBytes = boundedInteger(event.data.size_bytes, 0, Number.MAX_SAFE_INTEGER);
  if (!modelId || !["ready", "missing"].includes(String(modelState)) || !["ready", "missing"].includes(String(runtimeState))) {
    return { ...state, phase: "error", errorCode: "plugin_invalid_result" };
  }
  return {
    phase: modelState === "ready" ? "ready" : "missing",
    modelId,
    runtimeReady: runtimeState === "ready",
    sizeBytes,
    percent: modelState === "ready" ? 100 : 0,
    errorCode: null
  };
}

export function failSemanticModelOperation(state: SemanticModelState): SemanticModelState {
  return { ...state, phase: "error", errorCode: "plugin_unavailable" };
}

export function semanticModelSizeLabel(sizeBytes: number): string {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return "0 MB";
  return `${Math.max(0.1, sizeBytes / 1024 / 1024).toFixed(1)} MB`;
}

function boundedInteger(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return minimum;
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
