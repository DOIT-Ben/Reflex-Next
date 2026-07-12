import type {
  CoreEvent,
  CoreEventEnvelope,
  OptimizeRequestDraft
} from "./coreBridge";
import {
  listSceneOptions,
  type OptimizeMode,
  type OptimizeStyle,
  type OutputLanguage,
  type ScenePolicy
} from "./reflexSession";
import type { AppConfig } from "./settingsApi";
import type { HostAction } from "./desktopBridge";
import { providerName } from "./providerCatalog";

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

export type Overlay = null | "clipboard_confirm" | "settings" | "plugin_manager" | "template_manager" | "result_compare";

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
export type ResultSaveStatus = "saving" | "saved" | "unsaved" | "private";
export type ResultStyle = OptimizeStyle | "precise";

export type CurrentResult = {
  requestId: string;
  historyId: string | null;
  sourceText: string | null;
  output: string;
  scene: string | null;
  style: ResultStyle;
  mode: OptimizeMode;
  provider: string | null;
  model: string | null;
  elapsedMs: number | null;
  saveStatus: ResultSaveStatus;
  rating: number | null;
};

export type HistoryReuseIntent = {
  version: 1;
  sequence: number;
  history_id: string;
  kind: "input" | "result";
  text: string;
  scene?: string | null;
  style?: ResultStyle;
  mode?: OptimizeMode;
  provider?: string;
  model?: string | null;
  elapsed_ms?: number | null;
  rating?: number | null;
};

export type HostSettingsDraft = {
  default_provider: string | null;
  default_model: string | null;
  default_mode: OptimizeMode;
  default_style: OptimizeStyle;
  scene_policy: ScenePolicy;
  clipboard_policy: ClipboardPolicy;
  hotkey: string;
  history_enabled: boolean;
  privacy_mode: boolean;
  history_redaction: AppConfig["history_redaction"];
  enabled_plugins: AppConfig["enabled_plugins"];
  language: AppConfig["language"];
  theme: AppConfig["theme"];
};

export const SETTINGS_PLUGIN_IDS = ["translator", "markdown-preview", "batch-runner", "semantic-detector"] as const;
export type SettingsPluginId = (typeof SETTINGS_PLUGIN_IDS)[number];

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
  recentOutput: string;
  currentResult: CurrentResult | null;
  recentResult: CurrentResult | null;
  lastHistoryReuseSequence: number;
  inputNotice: string | null;
  errorMessage: string | null;
  errorCode: string | null;
  errorRecoverable: boolean;
  errorAction: string | null;
  diagnosticId: string | null;
  canGenerate: boolean;
  copied: boolean;
};

export function createDefaultSettingsDraft(settings: RequestSettings): HostSettingsDraft {
  return {
    default_provider: settings.provider,
    default_model: settings.model,
    default_mode: settings.mode,
    default_style: settings.style,
    scene_policy: settings.scene_policy,
    clipboard_policy: "manual",
    hotkey: "Ctrl+Alt+R",
    history_enabled: false,
    privacy_mode: false,
    history_redaction: "secrets",
    enabled_plugins: ["translator", "markdown-preview"],
    language: "zh-CN",
    theme: "system"
  };
}

export function settingsDraftFromConfig(config: AppConfig): HostSettingsDraft {
  return {
    default_provider: config.provider,
    default_model: config.model,
    default_mode: config.mode,
    default_style: config.style,
    scene_policy: config.scene_policy,
    clipboard_policy: config.clipboard_policy,
    hotkey: config.hotkey,
    history_enabled: config.history_enabled,
    privacy_mode: config.privacy_mode,
    history_redaction: config.history_redaction,
    enabled_plugins: [...config.enabled_plugins],
    language: config.language,
    theme: config.theme
  };
}

export function configFromSettingsDraft(
  config: AppConfig,
  draft: HostSettingsDraft
): AppConfig {
  return {
    ...config,
    provider: draft.default_provider ?? "minimax",
    model: draft.default_model ?? "MiniMax-M2.7-highspeed",
    mode: draft.default_mode,
    style: draft.default_style,
    scene_policy: draft.scene_policy,
    clipboard_policy: draft.clipboard_policy,
    hotkey: draft.hotkey,
    history_enabled: draft.history_enabled,
    privacy_mode: draft.privacy_mode,
    history_redaction: draft.history_redaction,
    enabled_plugins: [...draft.enabled_plugins],
    language: draft.language,
    theme: draft.theme
  };
}

export function updateHistorySettingsDraft(
  draft: HostSettingsDraft,
  changes: Partial<
    Pick<HostSettingsDraft, "history_enabled" | "privacy_mode" | "history_redaction">
  >
): HostSettingsDraft {
  return {
    ...draft,
    ...(typeof changes.history_enabled === "boolean"
      ? { history_enabled: changes.history_enabled }
      : {}),
    ...(typeof changes.privacy_mode === "boolean"
      ? { privacy_mode: changes.privacy_mode }
      : {}),
    ...(changes.history_redaction === "secrets" || changes.history_redaction === "none"
      ? { history_redaction: changes.history_redaction }
      : {})
  };
}

export function updatePluginSettingsDraft(
  draft: HostSettingsDraft,
  pluginId: string,
  enabled: boolean
): HostSettingsDraft {
  if (!SETTINGS_PLUGIN_IDS.includes(pluginId as SettingsPluginId)) {
    return { ...draft, enabled_plugins: [...draft.enabled_plugins] };
  }
  const enabledPlugins = new Set(
    draft.enabled_plugins.filter((candidate) =>
      SETTINGS_PLUGIN_IDS.includes(candidate as SettingsPluginId)
    )
  );
  if (enabled) {
    enabledPlugins.add(pluginId);
  } else {
    enabledPlugins.delete(pluginId);
  }
  return {
    ...draft,
    enabled_plugins: SETTINGS_PLUGIN_IDS.filter((candidate) => enabledPlugins.has(candidate))
  };
}

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
    recentOutput: "",
    currentResult: null,
    recentResult: null,
    lastHistoryReuseSequence: 0,
    inputNotice: null,
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
    inputNotice: null,
    errorMessage: null,
    errorCode: null,
    errorRecoverable: false,
    errorAction: null,
    diagnosticId: null
  };
}

export function applyClipboardText(state: HostState, text: string): HostState {
  return {
    ...updateInput(state, text),
    inputNotice: null
  };
}

export function applyClipboardError(state: HostState, message: string): HostState {
  return {
    ...state,
    inputNotice: message
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

export function applySceneSelection(
  draft: RequestSettings,
  sceneId: string
): RequestSettings {
  const normalized = sceneId.trim();
  if (!normalized) {
    return { ...draft, scene: null, scene_policy: "auto" };
  }
  const knownScene = listSceneOptions().some((scene) => scene.id === normalized);
  return knownScene
    ? { ...draft, scene: normalized, scene_policy: "manual" }
    : { ...draft, scene: null, scene_policy: "auto" };
}

export function openSettings(state: HostState): HostState {
  return {
    ...state,
    overlay: "settings",
    settingsDraft: createSettingsDraft(state)
  };
}

export function applyHostAction(state: HostState, action: HostAction): HostState {
  if (action === "plugins") {
    return {
      ...state,
      overlay: "plugin_manager",
      inputNotice: null
    };
  }
  if (action === "settings") {
    return openSettings(state);
  }
  if (action === "recent") {
    if (isActiveGeneration(state.phase)) {
      return state;
    }
    if (!state.recentResult?.output.trim()) {
      return {
        ...state,
        overlay: null,
        inputNotice: "暂无最近结果。"
      };
    }
    return {
      ...state,
      phase: "completed",
      overlay: null,
      output: state.recentResult.output,
      currentResult: state.recentResult,
      inputNotice: null
    };
  }
  return state;
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

export function applyPersistedConfig(state: HostState, config: AppConfig): HostState {
  const requestDraft: RequestSettings = {
    ...state.requestDraft,
    provider: config.provider,
    model: config.model,
    mode: config.mode,
    style: config.style,
    scene_policy: config.scene_policy
  };
  const settingsDraft: HostSettingsDraft | null = state.settingsDraft
    ? settingsDraftFromConfig(config)
    : null;
  return {
    ...state,
    requestDraft,
    settingsDraft,
    providerSummary: providerLabel(requestDraft)
  };
}

export function startGeneration(state: HostState, requestId: string): HostState {
  return {
    ...state,
    phase: "analyzing_scene",
    overlay: null,
    activeRequestId: requestId,
    output: "",
    currentResult: null,
    inputNotice: null,
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
    currentResult: null,
    inputNotice: null,
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
  if (
    envelope.event.type === "error" &&
    state.phase === "completed" &&
    state.currentResult?.requestId === envelope.request_id
  ) {
    const currentResult = {
      ...state.currentResult,
      saveStatus: state.currentResult.saveStatus === "saving" ? "unsaved" as const : state.currentResult.saveStatus
    };
    return { ...state, currentResult, recentResult: currentResult };
  }
  if (
    envelope.event.type === "metric" &&
    (!state.currentResult || state.currentResult.requestId !== envelope.request_id)
  ) {
    return state;
  }
  return applyCoreEvent(state, envelope.event);
}

export function createRequestDraft(
  state: HostState,
  language: OutputLanguage = "zh-CN"
): OptimizeRequestDraft {
  return {
    text: state.inputText.trim(),
    ...state.requestDraft,
    stream: true,
    metadata: {
      host: "tauri",
      surface: "quick-panel",
      language: language === "en-US" ? "en-US" : "zh-CN"
    }
  };
}

export function resolveHostShortcut(
  state: HostState,
  input: HostShortcutInput
): HostShortcutAction {
  if (state.overlay) {
    return input.key === "Escape" ? "close_overlay" : "none";
  }
  const isPrimaryEnter = input.key === "Enter" && (input.ctrlKey || input.metaKey);
  if (isPrimaryEnter) {
    return state.canGenerate && !isActiveGeneration(state.phase) ? "generate" : "none";
  }
  if (input.key !== "Escape") {
    return "none";
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
    const output = stringFrom(event.data.text, stringFrom(event.data.final_text, state.output));
    const currentResult = createCurrentResult(state, event.data, output);
    return {
      ...state,
      phase: "completed",
      activeRequestId: null,
      output,
      recentOutput: output,
      currentResult,
      recentResult: currentResult
    };
  }
  if (event.type === "metric") {
    if (!state.currentResult) return state;
    const currentResult: CurrentResult = {
      ...state.currentResult,
      historyId: stringOrNull(event.data.history_id) ?? state.currentResult.historyId,
      elapsedMs: integerOrNull(event.data.elapsed_ms) ?? state.currentResult.elapsedMs,
      saveStatus: saveStatusFrom(event.data.save_status, state.currentResult.saveStatus)
    };
    return { ...state, currentResult, recentResult: currentResult };
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

export function applyCurrentResultRating(
  state: HostState,
  expectedHistoryId: string,
  rating: number
): HostState {
  const current = state.currentResult;
  if (
    !current ||
    current.historyId !== expectedHistoryId ||
    !Number.isInteger(rating) ||
    rating < 1 ||
    rating > 5
  ) {
    return state;
  }
  const next = { ...current, rating };
  return { ...state, currentResult: next, recentResult: next };
}

export function applyTranslationAsCurrentResult(
  state: HostState,
  translatedText: string,
  requestSequence: number,
  sourceResult: CurrentResult | null = state.currentResult
): HostState {
  const source = sourceResult;
  const output = typeof translatedText === "string" ? translatedText.trim() : "";
  if (
    !source ||
    !output ||
    output.length > 1_000_000 ||
    !Number.isSafeInteger(requestSequence) ||
    requestSequence < 1
  ) {
    return state;
  }
  const currentResult: CurrentResult = {
    requestId: `translation-${source.requestId}-${requestSequence}`,
    historyId: null,
    sourceText: source.output,
    output,
    scene: "doc_translation",
    style: "precise",
    mode: "content",
    provider: source.provider,
    model: source.model,
    elapsedMs: null,
    saveStatus: "unsaved",
    rating: null
  };
  return {
    ...state,
    phase: "completed",
    activeRequestId: null,
    output,
    recentOutput: output,
    currentResult,
    recentResult: currentResult
  };
}

export function applyHistoryReuseIntent(
  state: HostState,
  value: unknown
): HostState {
  if (!isRecord(value)) return state;
  const intent = value as Partial<HistoryReuseIntent>;
  if (
    intent.version !== 1 ||
    !Number.isSafeInteger(intent.sequence) ||
    (intent.sequence ?? 0) <= state.lastHistoryReuseSequence ||
    typeof intent.history_id !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(intent.history_id) ||
    typeof intent.text !== "string" ||
    !intent.text ||
    intent.text.length > 1_000_000 ||
    (intent.kind !== "input" && intent.kind !== "result")
  ) {
    return state;
  }
  const sequencedState = {
    ...state,
    lastHistoryReuseSequence: intent.sequence as number
  };
  if (isActiveGeneration(state.phase)) return sequencedState;
  if (intent.kind === "input") {
    return updateInput(sequencedState, intent.text);
  }
  if (
    !boundedStringOrNull(intent.scene) ||
    !isResultStyle(intent.style) ||
    (intent.mode !== "content" && intent.mode !== "prompt") ||
    !safeMetadataId(intent.provider) ||
    !boundedStringOrNull(intent.model) ||
    !integerOrNullValue(intent.elapsed_ms) ||
    !ratingOrNull(intent.rating)
  ) {
    return state;
  }
  const currentResult: CurrentResult = {
    requestId: `history-reuse-${intent.history_id}`,
    historyId: intent.history_id,
    sourceText: null,
    output: intent.text,
    scene: intent.scene ?? null,
    style: intent.style,
    mode: intent.mode,
    provider: intent.provider,
    model: intent.model ?? null,
    elapsedMs: intent.elapsed_ms ?? null,
    saveStatus: "saved",
    rating: intent.rating ?? null
  };
  return {
    ...sequencedState,
    phase: "completed",
    activeRequestId: null,
    output: intent.text,
    recentOutput: intent.text,
    currentResult,
    recentResult: currentResult
  };
}

function createCurrentResult(
  state: HostState,
  data: Record<string, unknown>,
  output: string
): CurrentResult {
  return {
    requestId: state.activeRequestId ?? "",
    historyId: stringOrNull(data.history_id),
    sourceText: state.inputText.trim() || null,
    output,
    scene: stringFrom(data.scene, state.detectedScene ?? "general"),
    style: styleFrom(data.style, state.requestDraft.style),
    mode: modeFrom(data.mode, state.requestDraft.mode),
    provider: stringOrNull(data.provider) ?? state.requestDraft.provider,
    model: stringOrNull(data.model) ?? state.requestDraft.model,
    elapsedMs: integerOrNull(data.elapsed_ms),
    saveStatus: saveStatusFrom(data.save_status, "unsaved"),
    rating: null
  };
}

function isActiveGeneration(phase: HostPhase): boolean {
  return phase === "analyzing_scene" || phase === "connecting_provider" || phase === "streaming";
}

function createDefaultSettings(): RequestSettings {
  return {
    mode: "content",
    style: "balanced",
    scene: null,
    scene_policy: "auto",
    provider: "minimax",
    model: "MiniMax-M2.7-highspeed"
  };
}

function createSettingsDraft(state: HostState): HostSettingsDraft {
  return createDefaultSettingsDraft(state.requestDraft);
}

function providerLabel(settings: RequestSettings): string {
  return providerDisplayName(settings.provider);
}

export function providerDisplayName(provider: string | null): string {
  return providerName(provider);
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

function integerOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function saveStatusFrom(value: unknown, fallback: ResultSaveStatus): ResultSaveStatus {
  return value === "saving" || value === "saved" || value === "unsaved" || value === "private"
    ? value
    : fallback;
}

function styleFrom(value: unknown, fallback: ResultStyle): ResultStyle {
  return isResultStyle(value)
    ? value
    : fallback;
}

function modeFrom(value: unknown, fallback: OptimizeMode): OptimizeMode {
  return value === "content" || value === "prompt" ? value : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isResultStyle(value: unknown): value is ResultStyle {
  return value === "concise" || value === "balanced" || value === "detailed" || value === "creative" || value === "precise";
}

function safeMetadataId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);
}

function boundedStringOrNull(value: unknown): value is string | null {
  return value === null || (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 128 &&
    !Array.from(value).some((character) => character < " ")
  );
}

function integerOrNullValue(value: unknown): value is number | null {
  return value === null || (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 2 ** 31 - 1
  );
}

function ratingOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 5);
}
