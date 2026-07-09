import type {
  CoreEvent,
  CoreEventEnvelope,
  OptimizeRequestDraft
} from "./coreBridge";
import type { OptimizeMode, OptimizeStyle, ScenePolicy } from "./reflexSession";

export type HostPhase =
  | "empty"
  | "ready"
  | "adjusting"
  | "analyzing_scene"
  | "connecting_provider"
  | "streaming"
  | "completed"
  | "cancelled"
  | "error";

export type Overlay = null | "clipboard_confirm" | "settings";

export type HostShortcutAction =
  | "none"
  | "generate"
  | "cancel_generation"
  | "close_overlay"
  | "leave_adjust"
  | "hide_window";

export type HostShortcutInput = {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
};

export type RequestSettings = {
  mode: OptimizeMode;
  style: OptimizeStyle;
  scene: string | null;
  scene_policy: ScenePolicy;
  provider: string | null;
  model: string | null;
};

export type ClipboardPolicy = "startup" | "manual" | "auto_replace";

export type HostSettingsDraft = {
  default_provider: string | null;
  default_model: string | null;
  default_mode: OptimizeMode;
  default_style: OptimizeStyle;
  scene_policy: ScenePolicy;
  clipboard_policy: ClipboardPolicy;
};

export type HostState = {
  phase: HostPhase;
  overlay: Overlay;
  inputText: string;
  requestDraft: RequestSettings;
  adjustDraft: RequestSettings | null;
  settingsDraft: HostSettingsDraft | null;
  activeRequestId: string | null;
  detectedScene: string | null;
  providerSummary: string;
  output: string;
  errorMessage: string | null;
  errorCode: string | null;
  errorRecoverable: boolean;
  errorAction: string | null;
  diagnosticId: string | null;
  canGenerate: boolean;
  copied: boolean;
};

export function createHostState(): HostState {
  const requestDraft = createDefaultSettings();
  return {
    phase: "empty",
    overlay: null,
    inputText: "",
    requestDraft,
    adjustDraft: null,
    settingsDraft: null,
    activeRequestId: null,
    detectedScene: null,
    providerSummary: providerLabel(requestDraft),
    output: "",
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null,
    canGenerate: false,
    copied: false
  };
}

export function updateInput(state: HostState, inputText: string): HostState {
  const trimmed = inputText.trim();
  return {
    ...state,
    inputText,
    phase: trimmed ? "ready" : "empty",
    canGenerate: Boolean(trimmed),
    output: trimmed ? state.output : "",
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null
  };
}

export function openAdjust(state: HostState): HostState {
  return {
    ...state,
    phase: "adjusting",
    adjustDraft: { ...state.requestDraft }
  };
}

export function cancelAdjust(state: HostState): HostState {
  return {
    ...state,
    phase: state.inputText.trim() ? "ready" : "empty",
    adjustDraft: null
  };
}

export function applyAdjustDraft(state: HostState, draft: RequestSettings): HostState {
  return {
    ...state,
    phase: state.inputText.trim() ? "ready" : "empty",
    requestDraft: { ...draft },
    adjustDraft: null,
    providerSummary: providerLabel(draft)
  };
}

export function openSettings(state: HostState): HostState {
  return {
    ...state,
    overlay: "settings",
    settingsDraft: createSettingsDraft(state)
  };
}

export function cancelSettings(state: HostState): HostState {
  return {
    ...state,
    overlay: null,
    settingsDraft: null
  };
}

export function applySettingsDraft(
  state: HostState,
  draft: HostSettingsDraft
): HostState {
  const nextRequestDraft = {
    ...state.requestDraft,
    mode: draft.default_mode,
    style: draft.default_style,
    scene_policy: draft.scene_policy,
    provider: draft.default_provider,
    model: draft.default_model
  };
  return {
    ...state,
    overlay: null,
    settingsDraft: null,
    requestDraft: nextRequestDraft,
    providerSummary: providerLabel(nextRequestDraft)
  };
}

export function startGeneration(state: HostState, requestId: string): HostState {
  return {
    ...state,
    phase: "analyzing_scene",
    overlay: null,
    activeRequestId: requestId,
    output: "",
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null,
    copied: false
  };
}

export function cancelGeneration(state: HostState): HostState {
  return {
    ...state,
    phase: state.inputText.trim() ? "ready" : "empty",
    activeRequestId: null,
    output: "",
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null,
    copied: false
  };
}

export function retryAfterError(state: HostState): HostState {
  return {
    ...state,
    phase: state.inputText.trim() ? "ready" : "empty",
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null
  };
}

export function applyCoreEnvelope(state: HostState, envelope: CoreEventEnvelope): HostState {
  if (state.activeRequestId && envelope.request_id !== state.activeRequestId) {
    return state;
  }
  return applyCoreEvent(state, envelope.event);
}

export function createRequestDraft(state: HostState): OptimizeRequestDraft {
  return {
    text: state.inputText.trim(),
    ...state.requestDraft,
    stream: true,
    metadata: {
      host: "tauri",
      surface: "quick-panel"
    }
  };
}

export function resolveHostShortcut(
  state: HostState,
  input: HostShortcutInput
): HostShortcutAction {
  const isPrimaryEnter = input.key === "Enter" && (input.ctrlKey || input.metaKey);
  if (isPrimaryEnter) {
    return state.canGenerate && !isActiveGeneration(state.phase) ? "generate" : "none";
  }
  if (input.key !== "Escape") {
    return "none";
  }
  if (state.overlay) {
    return "close_overlay";
  }
  if (state.phase === "adjusting") {
    return "leave_adjust";
  }
  if (isActiveGeneration(state.phase)) {
    return "cancel_generation";
  }
  return "hide_window";
}

function applyCoreEvent(state: HostState, event: CoreEvent): HostState {
  if (event.type === "status") {
    return {
      ...state,
      phase: phaseFromStatus(event.data.phase, state.phase),
      errorMessage: null,
      errorCode: null,
      errorRecoverable: false,
      errorAction: null,
      diagnosticId: null
    };
  }
  if (event.type === "scene") {
    return {
      ...state,
      detectedScene: stringFrom(event.data.scene, state.detectedScene ?? "general")
    };
  }
  if (event.type === "request") {
    const provider = stringFrom(event.data.provider, state.requestDraft.provider ?? "MiniMax");
    const model = stringFrom(event.data.model, state.requestDraft.model ?? "");
    return {
      ...state,
      phase: "connecting_provider",
      providerSummary: model ? `${provider} / ${model}` : provider
    };
  }
  if (event.type === "chunk") {
    return {
      ...state,
      phase: "streaming",
      output: state.output + stringFrom(event.data.text, "")
    };
  }
  if (event.type === "done") {
    return {
      ...state,
      phase: "completed",
      activeRequestId: null,
      output: stringFrom(event.data.text, stringFrom(event.data.final_text, state.output))
    };
  }
  if (event.type === "error") {
    return {
      ...state,
      phase: "error",
      activeRequestId: null,
      errorMessage: redactVisibleError(stringFrom(event.data.message, "模型服务暂时不可用")),
      errorCode: stringOrNull(event.data.code),
      errorRecoverable: event.data.recoverable === true,
      errorAction: stringOrNull(event.data.action),
      diagnosticId: stringOrNull(event.data.diagnostic_id)
    };
  }
  return state;
}

function isActiveGeneration(phase: HostPhase): boolean {
  return phase === "analyzing_scene" || phase === "connecting_provider" || phase === "streaming";
}

function createDefaultSettings(): RequestSettings {
  return {
    mode: "content",
    style: "balanced",
    scene: "report_writing",
    scene_policy: "auto",
    provider: "MiniMax",
    model: "abab6.5"
  };
}

function createSettingsDraft(state: HostState): HostSettingsDraft {
  return {
    default_provider: state.requestDraft.provider,
    default_model: state.requestDraft.model,
    default_mode: state.requestDraft.mode,
    default_style: state.requestDraft.style,
    scene_policy: state.requestDraft.scene_policy,
    clipboard_policy: "manual"
  };
}

function providerLabel(settings: RequestSettings): string {
  return settings.provider ?? "未配置";
}

function phaseFromStatus(value: unknown, fallback: HostPhase): HostPhase {
  if (value === "analyzing_scene") return "analyzing_scene";
  if (value === "connecting_provider") return "connecting_provider";
  if (value === "streaming") return "streaming";
  if (value === "cancelled") return "cancelled";
  if (value === "error") return "error";
  if (value === "completed") return "completed";
  return fallback;
}

function redactVisibleError(message: string): string {
  return message
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, "Bearer [已隐藏]")
    .replace(/(api[_-]?key=)[^\s&]+/gi, "$1[已隐藏]")
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "[已隐藏]");
}

function stringFrom(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
