<script lang="ts">
  import { onMount, tick } from "svelte";
  import { setTranslator } from "./domain/i18nStore";
  import FeedbackDialog from "./components/feedback/FeedbackDialog.svelte";
  import FeedbackPromptDialog from "./components/feedback/FeedbackPromptDialog.svelte";
  import FirstRunDialog from "./components/onboarding/FirstRunDialog.svelte";
  import SettingsDialog from "./components/settings/SettingsDialog.svelte";
  import type { SettingsSection } from "./components/settings/types";
  import ClipboardConfirmDialog from "./components/overlays/ClipboardConfirmDialog.svelte";
  import CommandPalette from "./components/overlays/CommandPalette.svelte";
  import ConfirmDialog from "./components/overlays/ConfirmDialog.svelte";
  import type { CommandItem } from "./components/overlays/CommandPalette.svelte";
  import PluginDialog from "./components/overlays/PluginDialog.svelte";
  import ResultCompareDialog from "./components/overlays/ResultCompareDialog.svelte";
  import Toast from "./components/overlays/Toast.svelte";
  import MarkdownPreviewDialog from "./components/tools/MarkdownPreviewDialog.svelte";
  import TranslationDialog from "./components/tools/TranslationDialog.svelte";
  import TemplateManagerDialog from "./components/tools/TemplateManagerDialog.svelte";
  import BatchDialog from "./components/tools/BatchDialog.svelte";
  import NavRail from "./components/shell/NavRail.svelte";
  import ReflexTitleBar from "./components/shell/ReflexTitleBar.svelte";
  import StatusBar from "./components/shell/StatusBar.svelte";
  import type { NavRailItem, StatusTone } from "./components/shell/types";
  import ConfigSummary from "./components/workbench/ConfigSummary.svelte";
  import AdjustPanel from "./components/workbench/AdjustPanel.svelte";
  import InputPane from "./components/workbench/InputPane.svelte";
  import ResultPane from "./components/workbench/ResultPane.svelte";
  import ScenePromptDialog from "./components/workbench/ScenePromptDialog.svelte";
  import type {
    ConfigSummaryItem,
    ResultMetaItem,
    WorkbenchPhase
  } from "./components/workbench/types";
  import { CapabilityBridge } from "./domain/capabilityBridge";
  import {
    activationRouteForProvider,
    availableActivationRoutes,
    completeActivation,
    createActivationState,
    normalizeActivationState,
    selectActivationRoute,
    type ActivationRoute,
    type ActivationState
  } from "./domain/activationState";
  import { createDiagnosticBundleBridge, type DiagnosticBundleBridge } from "./domain/diagnosticBundleBridge";
  import {
    createPromptFeedbackPayload,
    createFeedbackBridge,
    feedbackSubmitErrorMessage,
    type CloudConsent,
    type CloudQualityRelease,
    type CloudQuota,
    type FeedbackBridge,
    type FeedbackContext,
    type FeedbackFormValue,
    type FeedbackScreenshot,
    type FeedbackSentiment
  } from "./domain/feedbackBridge";
  import {
    createFeedbackPromptState,
    disableFeedbackPrompt,
    normalizeFeedbackPromptState,
    recordSuccessfulGeneration,
    snoozeFeedbackPrompt,
    type FeedbackPromptState
  } from "./domain/feedbackPrompt";
  import {
    createDefaultCoreBridge,
    createDemoCoreBridge,
    isSuccessfulCompletionEvent,
    UnavailableCoreBridge
  } from "./domain/coreBridge";
  import {
    applyAdjustDraft,
    applyClipboardError,
    applyClipboardText,
    applyCoreEnvelope,
    applyCurrentResultRating,
    applyHistoryReuseIntent,
    applyHostAction,
    applyPersistedConfig,
    applySettingsDraft,
    cancelGeneration,
    cancelAdjust,
    cancelSettings,
    configFromSettingsDraft,
    createDefaultSettingsDraft,
    createHostState,
    createRequestDraft,
    createRequestDraftWithSceneChoice,
    openAdjust,
    openSettings,
    resolveHostShortcut,
    retryAfterError,
    selectRequestModel,
    settingsDraftFromConfig,
    startGeneration,
    updateInput,
    updatePluginSettingsDraft,
    type HostState,
    type HistoryReuseIntent,
    type HostSettingsDraft,
    type CurrentResult,
    type RequestSettings,
    type ResultStyle,
    type SettingsPluginId
  } from "./domain/hostState";
  import {
    clipboardActionAfterCompletion,
    clipboardActionForManualReplace,
    createClipboardReader,
    createClipboardWriter,
    readClipboardText,
    shouldReadClipboardOnStartup,
    writeClipboardText,
    type ClipboardAction,
    type ClipboardReader,
    type ClipboardWriter
  } from "./domain/clipboardBridge";
  import {
    createDesktopBridge,
    safeDesktopSettingsError,
    type DesktopBridge,
    type DesktopStatus,
    type HostAction
  } from "./domain/desktopBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import { createTranslationFlow } from "./domain/translationFlow";
  import { createMarkdownPreviewFlow } from "./domain/markdownPreviewFlow";
  import { createBatchFlow } from "./domain/batchFlow";
  import type { TranslationLanguage, TranslationTarget } from "./domain/translationState";
  import {
    createProviderCatalogBridge,
    PROVIDER_CATALOG_UNAVAILABLE_MESSAGE,
    type ProviderCatalogBridge
  } from "./domain/providerCatalogBridge";
  import {
    createProviderConnectionBridge,
    type ProviderConnectionBridge
  } from "./domain/providerConnectionBridge";
  import {
    type WindowSizePreset
  } from "./domain/viewControls";
  import {
    createSettingsApi,
    type AppConfig,
    type SecretStatus,
    type SettingsApi
  } from "./domain/settingsApi";
  import type { CoreBridge, TauriHostApi } from "./domain/coreBridge";
  import {
    createTemplateDraft,
    filterTemplates,
    readCustomTemplates,
    removeCustomTemplate,
    renderTemplate,
    saveCustomTemplate,
    templateVariables,
    type PromptTemplate,
    type TemplateDraft
  } from "./domain/templateLibrary";
  import {
    fallbackProviderCatalog,
    providerDefaultModel,
    providerName,
    providerOptionsFromRuntime,
    providerModels,
    workbenchModelOptions,
    resolveProviderAvailability,
    withConfiguredModels,
    type ProviderOption,
    type ProviderAvailability
  } from "./domain/providerCatalog";
  import {
    applyQuickAction,
    generationTrustSummary,
    preferredByokProvider,
    quickActions
  } from "./domain/productExperience";
  import {
    applySemanticModelEvent,
    beginSemanticModelOperation,
    createSemanticModelState,
    failSemanticModelOperation,
    semanticModelSizeLabel
  } from "./domain/semanticModelState";
  import { t, translate } from "./domain/i18n";
  import { resultMarkdownContent, resultMarkdownFilename } from "./domain/resultExport";
  import { triggerDownload, TEXT_MARKDOWN_MIME } from "./domain/downloads";
  import { createToastController } from "./domain/toastState";
  import { createViewScaleStore, type ViewScaleStorage } from "./domain/viewScaleStore";
  import {
    listSceneOptions,
    type OptimizeMode,
    type OptimizeStyle
  } from "./domain/reflexSession";

  const modes: Array<{ id: OptimizeMode; label: string }> = [
    { id: "content", label: "内容优化" },
    { id: "prompt", label: "提示词生成" }
  ];
  const styles: Array<{ id: OptimizeStyle; label: string }> = [
    { id: "concise", label: "简洁" },
    { id: "balanced", label: "平衡" },
    { id: "detailed", label: "详细" },
    { id: "creative", label: "创意" }
  ];
  const scenes = listSceneOptions();
  let coreBridge: CoreBridge = new UnavailableCoreBridge();
  let coreBridgeState: "initializing" | "ready" | "unavailable" = "initializing";
  let bridgeReady = false;
  let bridgeUnavailable = false;
  let capabilityBridge: CapabilityBridge | null = null;
  let diagnosticBundleBridge: DiagnosticBundleBridge | null = null;
  let feedbackBridge: FeedbackBridge | null = null;
  let providerCatalogBridge: ProviderCatalogBridge | null = null;
  let providerConnectionBridge: ProviderConnectionBridge | null = null;
  let hostApi: TauriHostApi | null = null;
  let settingsApi: SettingsApi | null = null;
  let configWriteChain: Promise<void> = Promise.resolve();
  let desktopBridge: DesktopBridge | null = null;
  let clipboardReader: ClipboardReader = createClipboardReader();
  let clipboardWriter: ClipboardWriter = createClipboardWriter();
  let state: HostState = createHostState();
  let draft: RequestSettings = { ...state.requestDraft };
  let settingsDraft: HostSettingsDraft = createDefaultSettingsDraft(state.requestDraft);
  let activeRun: AbortController | null = null;
  let semanticModel = createSemanticModelState();
  let semanticModelRun: AbortController | null = null;
  let customTemplates: PromptTemplate[] = [];
  let templateDraft: TemplateDraft = createTemplateDraft();
  let selectedTemplateId: string | null = null;
  let templateQuery = "";
  let templateCategory: string | null = null;
  let templateValues: Record<string, string> = {};
  let templateNotice: string | null = null;
  let templateBusy = false;
  let templateCategories: string[] = [];
  let visibleTemplates: PromptTemplate[] = [];
  let persistedConfig: AppConfig | null = null;
  let activationState: ActivationState = createActivationState();
  let activationOpen = false;
  let activationNotice = "";
  let secretInput = "";
  let secretStatus: SecretStatus = {
    providerId: "minimax",
    configured: false,
    maskedTail: null
  };
  let settingsSection: SettingsSection = "provider";
  let settingsBusy = false;
  let secretBusy = false;
  let providerConnectionBusy: "models" | "test" | null = null;
  let providerConnectionNotice: string | null = null;
  let providerStatusError = false;
  let providerCatalogNotice: string | null = null;
  let providerOptions: ProviderOption[] = [...fallbackProviderCatalog];
  let providerStatus: ProviderAvailability = "checking";
  let activeProviderId = "minimax";
  let providerStatusText = "";
  let settingsNotice: string | null = null;
  let diagnosticExportBusy = false;
  let diagnosticExportNotice: string | null = null;
  let secretNotice: string | null = null;
  let clipboardReading = false;
  let startupClipboardRead = false;
  let clipboardNotice: string | null = null;
  let desktopStatus: DesktopStatus = {
    hotkey: "Ctrl+Alt+R",
    hotkeyActive: false,
    message: null
  };
  const toast = createToastController({ translate: (message) => tr(message) });
  const showToast = toast.show;
  let resultRatingBusy = false;
  let feedbackOpen = false;
  let feedbackPromptOpen = false;
  let feedbackPromptBusy = false;
  let feedbackPromptNotice: string | null = null;
  let feedbackPromptState: FeedbackPromptState = createFeedbackPromptState();
  let feedbackPromptEnabledDraft = feedbackPromptState.enabled;
  let feedbackSource: "manual" | "prompt" = "manual";
  let feedbackSentiment: FeedbackSentiment = "negative";
  let feedbackScreenshot: FeedbackScreenshot | null = null;
  let feedbackCaptureNotice: string | null = null;
  let feedbackSubmitBusy = false;
  let feedbackSubmitNotice: string | null = null;
  let cloudConsent: CloudConsent = {
    usage_metrics: false,
    improvement_data: false,
    feedback_attachments: false,
    policy_version: "2026-07-14",
    updated_at: null
  };
  let cloudUsageMetricsDraft = false;
  let cloudImprovementDraft = false;
  let cloudQualityRelease: CloudQualityRelease | null = null;
  let cloudQuota: CloudQuota | null = null;
  let cloudPrivacyBusy = false;
  let cloudPrivacyNotice: string | null = null;
  let cloudFeedbackAvailable = false;
  let cloudAvailability: ProviderAvailability = "checking";
  let appVersion = __REFLEX_APP_VERSION__;
  let windowSizePreset: WindowSizePreset = "default";
  let commandPaletteOpen = false;
  let scenePromptOpen = false;
  let scenePromptSelection = "";
  let commandItems: CommandItem[] = [];
  let confirmation: {
    title: string;
    description: string;
    confirmLabel: string;
    danger?: boolean;
    run: () => void | Promise<void>;
  } | null = null;
  let activeNavId = "workbench";
  let workbenchPhase: WorkbenchPhase = "empty";
  let workbenchSurfaceEl: HTMLElement | null = null;
  let lastScrollPhase = state.phase;
  let workbenchStatusMessage = "准备就绪";
  let statusTone: StatusTone = "idle";
  let navItems: NavRailItem[] = [];
  let configSummaryItems: ConfigSummaryItem[] = [];
  let resultMetaItems: ResultMetaItem[] = [];
  let tr: (source: string, values?: Record<string, string | number>) => string = (source) => source;

  function safeLocalStorage(): ViewScaleStorage | null {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  const viewScale = createViewScaleStore(safeLocalStorage());

  const translationFlow = createTranslationFlow({
    coreBridge: () => coreBridge,
    capabilityBridge: () => capabilityBridge,
    currentResult: () => state.currentResult ?? null,
    fallbackRoute: () => ({ provider: state.requestDraft.provider, model: state.requestDraft.model }),
    updateHostState: (updater) => {
      state = updater(state);
    },
    writeClipboardValue: (text, successMessage) => writeClipboardValue(text, successMessage),
    showToast
  });
  const translation = translationFlow.state;

  const markdownPreviewFlow = createMarkdownPreviewFlow({
    capabilityBridge: () => capabilityBridge
  });
  const markdownPreview = markdownPreviewFlow.state;

  const batchFlow = createBatchFlow({
    coreBridge: () => coreBridge,
    capabilityBridge: () => capabilityBridge,
    requestContext: () => ({
      mode: state.requestDraft.mode,
      provider: state.requestDraft.provider,
      model: state.requestDraft.model
    }),
    language: () => (persistedConfig?.language === "en-US" ? "en-US" : "zh-CN"),
    translate: (source, values) => tr(source, values),
    showToast
  });
  const batch = batchFlow.state;
  const batchFileNotice = batchFlow.fileNotice;

  function workbenchScrollSurface(): HTMLElement | null {
    const surface = workbenchSurfaceEl;
    if (!surface || surface.scrollHeight <= surface.clientHeight) return null;
    return surface;
  }

  function revealResultPane() {
    const surface = workbenchScrollSurface();
    const resultPane = workbenchSurfaceEl?.querySelector<HTMLElement>(".result-pane") ?? null;
    if (!surface || !resultPane) return;
    const delta = resultPane.getBoundingClientRect().top - surface.getBoundingClientRect().top;
    if (Math.abs(delta) < 4) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    surface.scrollTo({
      top: surface.scrollTop + delta,
      behavior: reduceMotion ? "auto" : "smooth"
    });
  }

  function revealRunControls() {
    const surface = workbenchScrollSurface();
    if (!surface || surface.scrollTop <= 0) return;
    surface.scrollTo({ top: 0 });
  }

  function syncWorkbenchScroll(phase: HostState["phase"]) {
    if (phase === lastScrollPhase) return;
    lastScrollPhase = phase;
    if (phase === "completed" || phase === "error") {
      void tick().then(revealResultPane);
    } else if (isGenerating(phase)) {
      revealRunControls();
    }
  }

  onMount(() => {
    let disposed = false;
    let stopListening: (() => void) | null = null;
    let stopHistoryReuseListening: (() => void) | null = null;

    void createTauriHostApi().then(async (host) => {
      if (disposed) return;
      if (!host) {
        if (import.meta.env.DEV) {
          coreBridge = createDemoCoreBridge();
          coreBridgeState = "ready";
        } else {
          coreBridgeState = "unavailable";
        }
        return;
      }

      hostApi = host;
      capabilityBridge = new CapabilityBridge(host);
      providerCatalogBridge = createProviderCatalogBridge(host);
      providerConnectionBridge = createProviderConnectionBridge(host);
      diagnosticBundleBridge = createDiagnosticBundleBridge(host);
      feedbackBridge = createFeedbackBridge(host);
      void hydrateCloudPrivacy();
      settingsApi = createSettingsApi(host);
      clipboardReader = createClipboardReader(host);
      clipboardWriter = createClipboardWriter(host);
      const desktop = createDesktopBridge(host);
      desktopBridge = desktop;

      void import("@tauri-apps/api/app")
        .then(({ getVersion }) => getVersion())
        .then((version) => (appVersion = version))
        .catch(() => undefined);

      void desktop
        .listen(handleHostAction)
        .then((unlisten) => {
          if (disposed) {
            unlisten();
          } else {
            stopListening = unlisten;
          }
        })
        .catch(() => {
          if (disposed) return;
          desktopStatus = {
            ...desktopStatus,
            message: "桌面入口暂不可用。"
          };
        });

      void host
        .listen<HistoryReuseIntent>("reflex://history-reuse", ({ payload }) => {
          if (!disposed) state = applyHistoryReuseIntent(state, payload);
        })
        .then((unlisten) => {
          if (disposed) unlisten();
          else stopHistoryReuseListening = unlisten;
        })
        .catch(() => undefined);

      void createDefaultCoreBridge(host)
        .then((initialized) => {
          if (disposed) return;
          coreBridge = initialized.bridge;
          coreBridgeState = initialized.runtimeAvailable ? "ready" : "unavailable";
        })
        .catch(() => {
          if (!disposed) coreBridgeState = "unavailable";
        });

      await Promise.all([hydrateSettings(), refreshDesktopStatus(), refreshProviderCatalog()]);
      if (disposed) return;
      await readStartupClipboard();
    });

    return () => {
      disposed = true;
      stopListening?.();
      stopHistoryReuseListening?.();
      activeRun?.abort();
      translationFlow.close();
      markdownPreviewFlow.close();
      batchFlow.close();
      semanticModelRun?.abort();
    };
  });

  $: bridgeReady = coreBridgeState === "ready" || (
    coreBridgeState === "unavailable" &&
    hostApi !== null &&
    activeProviderId === "reflex-cloud"
  );
  $: bridgeUnavailable = coreBridgeState === "unavailable" && !bridgeReady;
  $: canGenerate = state.canGenerate && activeRun === null && !isGenerating(state.phase) && bridgeReady;
  $: translatorEnabled = persistedConfig?.enabled_plugins.includes("translator") ?? true;
  $: markdownPreviewEnabled = persistedConfig?.enabled_plugins.includes("markdown-preview") ?? true;
  $: batchRunnerEnabled = persistedConfig?.enabled_plugins.includes("batch-runner") ?? true;
  $: semanticDetectorEnabled = settingsDraft.enabled_plugins.includes("semantic-detector");
  $: semanticDetectorActive = persistedConfig?.enabled_plugins.includes("semantic-detector") ?? false;
  $: uiLanguage = settingsDraft.language === "en-US" || persistedConfig?.language === "en-US"
    ? "en-US"
    : "zh-CN";
  $: tr = (source, values = {}) => translate(uiLanguage, source, values);
  $: setTranslator(tr);
  $: templateCategories = [...new Set(customTemplates.map((template) => template.category))].sort((left, right) => left.localeCompare(right, "zh-CN"));
  $: visibleTemplates = filterTemplates(customTemplates, templateQuery, templateCategory);
  $: settingsProviderModels = providerModels(settingsDraft.default_provider, providerOptions);
  $: selectableModels = workbenchModelOptions(persistedConfig, providerOptions);
  $: activeProviderId = (state.requestDraft.provider ?? "minimax").trim().toLowerCase();
  $: providerStatus = resolveProviderAvailability(
    activeProviderId,
    secretStatus,
    persistedConfig !== null,
    providerStatusError,
    cloudAvailability
  );
  $: providerStatusText = providerAvailabilityLabel(providerStatus);
  $: activationRoutes = availableActivationRoutes(cloudAvailability);
  $: activationProviderReady = providerStatus === "ready";
  $: activeProviderLabel = tr(providerName(activeProviderId, providerOptions));
  $: generationTrust = generationTrustSummary(
    {
      route: activationRouteForProvider(activeProviderId),
      providerLabel: activeProviderLabel,
      historyEnabled: persistedConfig?.history_enabled ?? false,
      privacyMode: persistedConfig?.privacy_mode ?? false,
      quota: activeProviderId === "reflex-cloud" && cloudQuota
        ? { requestsUsed: cloudQuota.requests_used, requestsLimit: cloudQuota.requests_limit }
        : null
    },
    uiLanguage
  );
  $: workbenchPhase = isGenerating(state.phase)
    ? "running"
    : state.phase === "completed"
      ? "completed"
      : state.phase === "error"
        ? "error"
        : state.phase === "cancelled"
          ? "cancelled"
          : state.output
            ? "completed"
            : "empty";
  $: syncWorkbenchScroll(state.phase);
  $: workbenchStatusMessage = coreBridgeState === "initializing" && !isGenerating(state.phase)
    ? tr("正在连接运行服务")
    : bridgeUnavailable && !isGenerating(state.phase)
      ? tr("运行服务暂不可用")
      : state.phase === "analyzing_scene"
    ? tr("正在分析场景")
    : state.phase === "connecting_provider"
      ? tr("正在连接模型服务")
      : state.phase === "streaming"
        ? tr("正在生成结果")
        : state.phase === "completed"
          ? tr("生成完成")
          : state.phase === "error"
            ? tr("生成失败")
            : state.phase === "cancelled"
              ? tr("已取消生成")
              : tr("准备就绪");
  $: statusTone = bridgeUnavailable && !isGenerating(state.phase)
    ? "warning"
    : isGenerating(state.phase)
    ? "working"
    : state.phase === "completed"
      ? "success"
      : state.phase === "error"
        ? "error"
        : state.phase === "cancelled"
          ? "warning"
          : "idle";
  $: activeNavId = state.overlay === "template_manager"
    ? "templates"
    : state.overlay === "plugin_manager"
      ? "plugins"
      : state.overlay === "settings"
        ? "settings"
        : $batch.phase !== "closed"
          ? "batch"
          : $translation.phase !== "closed"
            ? "translation"
            : $markdownPreview.phase !== "closed"
              ? "markdown"
              : commandPaletteOpen
                ? "tools"
                : "workbench";
  $: navItems = [
    { id: "workbench", label: tr("工作台"), symbol: "" },
    { id: "tools", label: tr("更多工具"), symbol: "" },
    { id: "history", label: tr("历史记录"), symbol: "", group: "utility" },
    { id: "settings", label: tr("设置"), symbol: "", shortcut: "Ctrl+,", group: "utility" }
  ];
  $: commandItems = [
    { id: "adjust", label: "调整生成方案", run: () => { closeCommandPalette(); beginAdjust(); } },
    { id: "templates", label: "模板管理", run: () => { closeCommandPalette(); openTemplateManager(); } },
    { id: "batch", label: "批量处理", disabled: !batchRunnerEnabled, run: () => { closeCommandPalette(); openBatchView(); } },
    { id: "translate", label: "翻译当前结果", disabled: !translatorEnabled || !state.currentResult?.output, run: () => { closeCommandPalette(); openTranslationView(); } },
    { id: "markdown", label: "预览 Markdown", disabled: !markdownPreviewEnabled || !state.currentResult?.output, run: () => { closeCommandPalette(); openMarkdownPreviewView(); } },
    { id: "history", label: "打开历史记录", run: () => { closeCommandPalette(); openHistoryWindow(); } },
    { id: "settings", label: "打开设置", run: () => { closeCommandPalette(); beginSettings(); } }
  ];
  $: configSummaryItems = [
    { id: "mode", label: tr("模式"), value: modeLabel(state.requestDraft.mode) },
    { id: "style", label: tr("风格"), value: styleLabel(state.requestDraft.style) },
    { id: "scene", label: tr("场景"), value: sceneLabel(state.requestDraft.scene) },
  ];
  $: resultMetaItems = [
    { id: "mode", label: tr("模式"), value: modeLabel(state.currentResult?.mode ?? state.requestDraft.mode) },
    { id: "style", label: tr("风格"), value: styleLabel(state.currentResult?.style ?? state.requestDraft.style) },
    {
      id: "provider",
      label: "Provider",
      value: tr(providerName(state.currentResult?.provider ?? state.requestDraft.provider, providerOptions))
    }
  ];

  function setInput(value: string) {
    state = updateInput(state, value);
  }

  function applyQuickActionToDraft(actionId: string) {
    state = { ...state, requestDraft: applyQuickAction(state.requestDraft, actionId) };
    draft = { ...state.requestDraft };
  }

  function clearInput() {
    setInput("");
  }

  function openCommandPalette() {
    commandPaletteOpen = true;
  }

  function closeCommandPalette() {
    commandPaletteOpen = false;
  }

  function returnToWorkbench() {
    commandPaletteOpen = false;
    if (state.phase === "adjusting") cancelAdjustView();
    if (state.overlay === "template_manager") closeTemplateManager();
    else if (state.overlay !== null) closeOverlay();
    if ($batch.phase !== "closed") closeBatchView();
    if ($translation.phase !== "closed") closeTranslationView();
    if ($markdownPreview.phase !== "closed") closeMarkdownPreviewView();
  }

  function handleNavigation(id: string) {
    commandPaletteOpen = false;
    if (id === "workbench") returnToWorkbench();
    else if (id === "tools") openCommandPalette();
    else if (id === "history") openHistoryWindow();
    else if (id === "settings") beginSettings();
  }

  async function hideMainWindow() {
    try {
      await hostApi?.invoke("hide_main_window");
    } catch {
      showToast("窗口操作暂不可用。");
    }
  }

  async function readClipboard() {
    if (clipboardReading) return;
    clipboardReading = true;
    const result = await readClipboardText(clipboardReader);
    clipboardReading = false;
    if (result.ok) {
      state = applyClipboardText(state, result.text);
      return;
    }
    state = applyClipboardError(state, result.message);
  }

  async function readStartupClipboard() {
    const policy = persistedConfig?.clipboard_policy;
    if (!policy || !shouldReadClipboardOnStartup(policy, startupClipboardRead)) return;
    startupClipboardRead = true;
    await readClipboard();
  }

  function handleHostAction(action: HostAction) {
    if ($markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if ($translation.phase !== "closed") closeTranslationView();
    if (action === "settings") {
      beginSettings();
      return;
    }
    state = applyHostAction(state, action);
  }

  function beginAdjust() {
    if ($markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if ($translation.phase !== "closed") closeTranslationView();
    state = openAdjust(state);
    draft = { ...(state.adjustDraft ?? state.requestDraft) };
  }

  function applyAdjust() {
    state = applyAdjustDraft(state, draft);
  }

  function switchWorkbenchModel(providerId: string, modelId: string) {
    if (!selectableModels.some((model) => model.providerId === providerId && model.id === modelId)) return;
    state = selectRequestModel(state, providerId, modelId);
    draft = { ...state.requestDraft };
    void refreshProviderSecretStatus(providerId);
  }

  function cancelAdjustView() {
    state = cancelAdjust(state);
    draft = { ...state.requestDraft };
  }

  function beginSettings(preferredProviderId: string | null = null) {
    if ($markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if ($translation.phase !== "closed") closeTranslationView();
    state = openSettings(state);
    settingsDraft = { ...(state.settingsDraft ?? settingsDraft) };
    feedbackPromptEnabledDraft = feedbackPromptState.enabled;
    settingsSection = "provider";
    secretInput = "";
    settingsNotice = null;
    secretNotice = null;
    void hydrateSettings(preferredProviderId);
    void refreshProviderCatalog();
    void hydrateCloudPrivacy();
  }

  async function hydrateCloudPrivacy() {
    const bridge = feedbackBridge;
    if (!bridge || cloudPrivacyBusy) return;
    cloudPrivacyBusy = true;
    cloudAvailability = "checking";
    cloudPrivacyNotice = null;
    try {
      const [consent, quota, qualityRelease] = await Promise.all([
        bridge.getConsent(),
        bridge.getQuota(),
        bridge.getQualityRelease().catch(() => null)
      ]);
      cloudConsent = consent;
      cloudUsageMetricsDraft = consent.usage_metrics;
      cloudImprovementDraft = consent.improvement_data;
      cloudQualityRelease = qualityRelease;
      cloudQuota = quota;
      cloudFeedbackAvailable = true;
      cloudAvailability = "ready";
    } catch {
      cloudFeedbackAvailable = false;
      cloudAvailability = "unavailable";
      cloudPrivacyNotice = "云端隐私设置暂不可用。";
    } finally {
      cloudPrivacyBusy = false;
    }
  }

  async function saveCloudPrivacyDraft(): Promise<boolean> {
    if (
      cloudUsageMetricsDraft === cloudConsent.usage_metrics &&
      cloudImprovementDraft === cloudConsent.improvement_data
    ) return true;
    const bridge = feedbackBridge;
    if (!bridge) {
      cloudPrivacyNotice = "当前环境无法保存云端隐私设置。";
      return false;
    }
    cloudPrivacyBusy = true;
    cloudPrivacyNotice = null;
    try {
      cloudConsent = await bridge.updateConsent({
        ...cloudConsent,
        usage_metrics: cloudUsageMetricsDraft,
        improvement_data: cloudImprovementDraft,
        policy_version: cloudConsent.policy_version
      });
      cloudUsageMetricsDraft = cloudConsent.usage_metrics;
      cloudImprovementDraft = cloudConsent.improvement_data;
      cloudPrivacyNotice = "云端隐私设置已更新。";
      return true;
    } catch {
      cloudUsageMetricsDraft = cloudConsent.usage_metrics;
      cloudImprovementDraft = cloudConsent.improvement_data;
      cloudPrivacyNotice = "云端隐私设置保存失败，请重试。";
      return false;
    } finally {
      cloudPrivacyBusy = false;
    }
  }

  function confirmDeleteCloudData() {
    confirmation = {
      title: "删除全部云端数据？",
      description: "将删除当前安装身份、反馈附件和改进计划数据。此操作无法撤销。",
      confirmLabel: "删除云端数据",
      danger: true,
      run: performDeleteCloudData
    };
  }

  async function performDeleteCloudData() {
    const bridge = feedbackBridge;
    if (!bridge || cloudPrivacyBusy) return;
    cloudPrivacyBusy = true;
    cloudPrivacyNotice = null;
    try {
      await bridge.deleteCloudData();
      cloudConsent = {
        usage_metrics: false,
        improvement_data: false,
        feedback_attachments: false,
        policy_version: "2026-07-14",
        updated_at: null
      };
      cloudUsageMetricsDraft = false;
      cloudImprovementDraft = false;
      cloudQuota = null;
      cloudPrivacyNotice = "云端数据已删除。";
      showToast("云端数据已删除。", "success");
    } catch {
      cloudPrivacyNotice = "云端数据删除失败，请重试。";
    } finally {
      cloudPrivacyBusy = false;
    }
  }

  async function saveConfigSerial(
    api: SettingsApi,
    buildConfig: (latest: AppConfig) => AppConfig
  ): Promise<AppConfig> {
    const write = configWriteChain.then(async () => {
      const latest = await api.loadConfig();
      return api.saveConfig(buildConfig(latest));
    });
    configWriteChain = write.then(() => undefined, () => undefined);
    return write;
  }

  async function saveSettings() {
    if (settingsBusy) return;
    if (!settingsApi || !persistedConfig) {
      settingsNotice = "当前环境无法保存设置。";
      return;
    }
    settingsBusy = true;
    settingsNotice = null;
    try {
      const nextFeedbackPromptState = {
        ...feedbackPromptState,
        enabled: feedbackPromptEnabledDraft
      };
      const draftToSave = settingsDraft;
      const saved = await saveConfigSerial(settingsApi, (latest) => ({
        ...configFromSettingsDraft(latest, draftToSave),
        feedback_prompt: nextFeedbackPromptState
      }));
      persistedConfig = saved;
      feedbackPromptState = normalizeFeedbackPromptState(saved.feedback_prompt);
      feedbackPromptEnabledDraft = feedbackPromptState.enabled;
      settingsDraft = settingsDraftFromConfig(saved);
      state = applySettingsDraft(applyPersistedConfig(state, saved), settingsDraft);
      draft = { ...state.requestDraft };
      await refreshDesktopStatus();
      await refreshProviderSecretStatus(saved.provider);
      if (saved.enabled_plugins.includes("semantic-detector")) {
        await runSemanticModelOperation("status");
      } else {
        semanticModelRun?.abort();
        semanticModel = createSemanticModelState();
      }
      const cloudSaved = await saveCloudPrivacyDraft();
      showToast(cloudSaved ? "✓ 设置已保存" : "本地设置已保存，云端授权未更新。", cloudSaved ? "success" : "error");
      if (providerReadyForActivation(saved.provider)) {
        await finishFirstRunFromSettings(saved.provider);
      }
    } catch (error) {
      settingsNotice = safeDesktopSettingsError(error);
    } finally {
      settingsBusy = false;
    }
  }

  async function exportDiagnosticBundle() {
    if (diagnosticExportBusy) return;
    if (!diagnosticBundleBridge) {
      diagnosticExportNotice = "当前环境无法导出诊断包。";
      return;
    }
    diagnosticExportBusy = true;
    diagnosticExportNotice = "正在导出诊断包...";
    try {
      const result = await diagnosticBundleBridge.exportBundle();
      diagnosticExportNotice = result === "completed" ? "诊断包已导出。" : "诊断包导出已取消。";
    } catch (error) {
      diagnosticExportNotice = error instanceof Error ? error.message : "诊断包导出失败，请重试。";
    } finally {
      diagnosticExportBusy = false;
    }
  }

  async function cancelDiagnosticBundleExport() {
    if (!diagnosticExportBusy || !diagnosticBundleBridge) return;
    try {
      await diagnosticBundleBridge.cancel();
      diagnosticExportNotice = "正在取消诊断包导出...";
    } catch (error) {
      diagnosticExportNotice = error instanceof Error ? error.message : "诊断包导出失败，请重试。";
    }
  }

  function cancelSettingsView() {
    state = cancelSettings(state);
    settingsDraft = persistedConfig
      ? settingsDraftFromConfig(persistedConfig)
      : createDefaultSettingsDraft(state.requestDraft);
    secretInput = "";
    settingsNotice = null;
    secretNotice = null;
    feedbackPromptEnabledDraft = feedbackPromptState.enabled;
    void refreshProviderSecretStatus(state.requestDraft.provider ?? "minimax");
  }

  async function hydrateSettings(preferredProviderId: string | null = null) {
    if (!settingsApi) return;
    settingsBusy = true;
    providerStatusError = false;
    settingsNotice = null;
    secretNotice = null;
    let config: AppConfig;
    try {
      config = await settingsApi.loadConfig();
      persistedConfig = config;
      activationState = normalizeActivationState(config.first_run_activation);
      activationOpen = !activationState.completed;
      feedbackPromptState = normalizeFeedbackPromptState(config.feedback_prompt);
      feedbackPromptEnabledDraft = feedbackPromptState.enabled;
      customTemplates = readCustomTemplates(config.custom_templates);
      state = applyPersistedConfig(state, config);
      settingsDraft = settingsDraftFromConfig(config);
      providerOptions = withConfiguredModels(providerOptions, config.provider_models);
    } catch {
      providerStatusError = true;
      settingsNotice = "设置加载失败，请重试。";
      settingsBusy = false;
      return;
    }
    const preferredProvider = preferredProviderId?.trim().toLowerCase();
    if (preferredProvider && providerOptions.some((provider) => provider.id === preferredProvider)) {
      const models = providerModels(preferredProvider, providerOptions);
      settingsDraft = {
        ...settingsDraft,
        default_provider: preferredProvider,
        default_model: providerDefaultModel(preferredProvider, providerOptions) ?? models[0]?.id ?? null
      };
    }
    await refreshProviderSecretStatus(settingsDraft.default_provider ?? config.provider);
    settingsBusy = false;
  }

  async function refreshProviderCatalog() {
    const bridge = providerCatalogBridge;
    if (!bridge) return;
    try {
      const descriptors = await bridge.listProviders();
      providerOptions = withConfiguredModels(
        providerOptionsFromRuntime(descriptors),
        settingsDraft.provider_models
      );
      providerCatalogNotice = null;
    } catch {
      // Keep the browser-safe catalog visible while the Runtime recovers.
      providerCatalogNotice = PROVIDER_CATALOG_UNAVAILABLE_MESSAGE;
    }
  }

  async function refreshDesktopStatus() {
    if (!desktopBridge) return;
    try {
      desktopStatus = await desktopBridge.status();
    } catch {
      desktopStatus = {
        ...desktopStatus,
        message: "快捷键状态暂不可用。"
      };
    }
  }

  async function refreshProviderSecretStatus(providerId: string) {
    if (providerId === "reflex-cloud") {
      secretStatus = { providerId, configured: true, maskedTail: null };
      providerStatusError = false;
      secretNotice = null;
      return;
    }
    const api = settingsApi;
    if (!api) return;
    try {
      secretStatus = await api.getProviderSecretStatus(providerId);
      providerStatusError = false;
    } catch {
      providerStatusError = true;
      secretStatus = { providerId, configured: false, maskedTail: null };
      secretNotice = "密钥状态读取失败，请重试。";
    }
  }

  async function saveSecret() {
    if (secretBusy) return;
    const api = settingsApi;
    const value = secretInput.trim();
    if (!api) {
      secretNotice = "当前环境无法保存密钥。";
      secretInput = "";
      return;
    }
    if (!value) {
      secretNotice = "请输入 API Key。";
      return;
    }
    secretBusy = true;
    secretNotice = null;
    try {
      secretStatus = await api.saveProviderSecret(
        settingsDraft.default_provider ?? "minimax",
        value
      );
      providerStatusError = false;
      secretNotice = "密钥已安全保存。";
      if (activationOpen && activationState.route === "byok") {
        const savedProvider = settingsDraft.default_provider ?? "minimax";
        const savedModel = settingsDraft.default_model ?? providerDefaultModel(savedProvider, providerOptions);
        if (savedModel) state = selectRequestModel(state, savedProvider, savedModel);
        let defaultProviderSaved = true;
        if (persistedConfig) {
          try {
            const draftToSave = settingsDraft;
            persistedConfig = await saveConfigSerial(api, (latest) =>
              configFromSettingsDraft(latest, draftToSave)
            );
          } catch {
            defaultProviderSaved = false;
          }
        }
        if (defaultProviderSaved && providerReadyForActivation(savedProvider)) {
          await finishFirstRunFromSettings(savedProvider);
        }
        showToast(
          defaultProviderSaved
            ? "✓ 密钥已保存，可以开始生成"
            : "密钥已保存，本次可继续生成；默认 Provider 尚未保存。",
          defaultProviderSaved ? "success" : "error"
        );
      }
    } catch {
      providerStatusError = true;
      secretNotice = "密钥保存失败，请重试。";
    } finally {
      secretInput = "";
      secretBusy = false;
    }
  }

  async function deleteSecret() {
    if (secretBusy || !secretStatus.configured) return;
    confirmation = {
      title: tr("删除已保存的 API Key？"),
      description: tr("删除后当前 Provider 将无法调用，之后仍可重新保存。"),
      confirmLabel: tr("删除密钥"),
      run: performDeleteSecret
    };
  }

  async function performDeleteSecret() {
    const api = settingsApi;
    if (!api) {
      secretNotice = "当前环境无法删除密钥。";
      return;
    }
    secretBusy = true;
    secretNotice = null;
    try {
      secretStatus = await api.deleteProviderSecret(
        settingsDraft.default_provider ?? "minimax"
      );
      providerStatusError = false;
      secretNotice = "密钥已删除。";
    } catch {
      providerStatusError = true;
      secretNotice = "密钥删除失败，请重试。";
    } finally {
      secretInput = "";
      secretBusy = false;
    }
  }

  async function selectSettingsProvider(provider: string) {
    const models = providerModels(provider, providerOptions);
    settingsDraft = {
      ...settingsDraft,
      default_provider: provider,
      default_model: providerDefaultModel(provider, providerOptions) ?? models[0]?.id ?? null
    };
    secretInput = "";
    secretNotice = null;
    providerConnectionNotice = null;
    await refreshProviderSecretStatus(provider);
  }

  function updateProviderBaseUrl(value: string) {
    const providerId = settingsDraft.default_provider ?? "minimax";
    settingsDraft = {
      ...settingsDraft,
      provider_endpoints: { ...settingsDraft.provider_endpoints, [providerId]: value }
    };
    providerConnectionNotice = null;
  }

  async function discoverProviderModels() {
    const bridge = providerConnectionBridge;
    const providerId = settingsDraft.default_provider ?? "minimax";
    if (!bridge || providerConnectionBusy) return;
    providerConnectionBusy = "models";
    providerConnectionNotice = null;
    try {
      const models = await bridge.discoverModels({
        providerId,
        baseUrl: settingsDraft.provider_endpoints[providerId] ?? ""
      });
      settingsDraft = {
        ...settingsDraft,
        default_model: models.includes(settingsDraft.default_model ?? "")
          ? settingsDraft.default_model
          : models[0],
        provider_models: { ...settingsDraft.provider_models, [providerId]: models }
      };
      providerOptions = withConfiguredModels(providerOptions, settingsDraft.provider_models);
      providerConnectionNotice = `已获取 ${models.length} 个模型。`;
    } catch (error) {
      providerConnectionNotice = error instanceof Error ? error.message : "无法获取模型列表，请重试。";
    } finally {
      providerConnectionBusy = null;
    }
  }

  async function testProviderConnection() {
    const bridge = providerConnectionBridge;
    const providerId = settingsDraft.default_provider ?? "minimax";
    if (!bridge || providerConnectionBusy) return;
    providerConnectionBusy = "test";
    providerConnectionNotice = null;
    try {
      const result = await bridge.testConnection({
        providerId,
        baseUrl: settingsDraft.provider_endpoints[providerId] ?? "",
        model: settingsDraft.default_model
      });
      providerConnectionNotice = result.ok
        ? `连接成功${result.latencyMs === null ? "" : `，耗时 ${result.latencyMs} ms`}。`
        : "模型连接测试失败，请检查配置后重试。";
    } catch (error) {
      providerConnectionNotice = error instanceof Error ? error.message : "模型连接测试失败，请重试。";
    } finally {
      providerConnectionBusy = null;
    }
  }

  async function persistFeedbackPrompt(next: FeedbackPromptState): Promise<boolean> {
    feedbackPromptState = next;
    feedbackPromptEnabledDraft = next.enabled;
    const api = settingsApi;
    const config = persistedConfig;
    if (!api || !config) return false;
    const pending = { ...config, feedback_prompt: next };
    persistedConfig = pending;
    try {
      const saved = await saveConfigSerial(api, (latest) => ({
        ...latest,
        feedback_prompt: next
      }));
      persistedConfig = saved;
      feedbackPromptState = normalizeFeedbackPromptState(saved.feedback_prompt);
      feedbackPromptEnabledDraft = feedbackPromptState.enabled;
      return true;
    } catch {
      // Keep the in-memory schedule for this session; a later settings save retries persistence.
      return false;
    }
  }

  async function recordFeedbackPromptCompletion() {
    if (!cloudFeedbackAvailable || !state.currentResult?.output.trim()) return;
    const promptAvailable =
      !feedbackOpen &&
      !feedbackPromptOpen &&
      !feedbackPromptBusy &&
      !confirmation &&
      !commandPaletteOpen &&
      !scenePromptOpen &&
      state.overlay === null &&
      $batch.phase === "closed" &&
      $translation.phase === "closed" &&
      $markdownPreview.phase === "closed" &&
      state.phase === "completed";
    const decision = recordSuccessfulGeneration(
      feedbackPromptState,
      Date.now(),
      Math.random,
      promptAvailable
    );
    const promptPersisted = await persistFeedbackPrompt(decision.state);
    if (decision.shouldPrompt && promptPersisted) {
      feedbackPromptNotice = null;
      feedbackPromptOpen = true;
    }
  }

  async function runOptimization() {
    if (!canGenerate) return;
    if (state.requestDraft.scene_policy === "ask") {
      scenePromptSelection = state.requestDraft.scene ?? "";
      scenePromptOpen = true;
      return;
    }
    await executeOptimization(createRequestDraft(state, persistedConfig?.language ?? "zh-CN"));
  }

  function cancelScenePrompt() {
    scenePromptOpen = false;
  }

  async function confirmScenePrompt() {
    if (!canGenerate) {
      scenePromptOpen = false;
      return;
    }
    const request = createRequestDraftWithSceneChoice(
      state,
      scenePromptSelection,
      persistedConfig?.language ?? "zh-CN"
    );
    scenePromptOpen = false;
    await executeOptimization(request);
  }

  async function executeOptimization(request = createRequestDraft(state, persistedConfig?.language ?? "zh-CN")) {
    if (activeRun !== null || !canGenerate) return;
    const requestId = `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = new AbortController();
    activeRun = controller;
    state = startGeneration(state, requestId);
    let completionHandled = false;

    try {
      for await (const event of coreBridge.optimize(request, {
        signal: controller.signal
      })) {
        if (controller.signal.aborted) break;
        state = applyCoreEnvelope(state, {
          version: 1,
          request_id: requestId,
          event
        });
        if (
          !completionHandled &&
          isSuccessfulCompletionEvent(event) &&
          state.phase === "completed" &&
          Boolean(state.currentResult?.output.trim())
        ) {
          completionHandled = true;
          await handleCompletionClipboard();
          await completeFirstRunActivation();
          await recordFeedbackPromptCompletion();
        }
      }
    } catch {
      if (!controller.signal.aborted && state.phase !== "completed") {
        state = applyCoreEnvelope(state, {
          version: 1,
          request_id: requestId,
          event: {
            type: "error",
            data: {
              code: "runtime_stream_failed",
              message: "生成服务连接中断，请重试。",
              recoverable: true,
              action: "retry"
            }
          }
        });
      }
    } finally {
      if (activeRun === controller) {
        activeRun = null;
      }
    }
  }

  function cancelRun() {
    activeRun?.abort();
    activeRun = null;
    state = cancelGeneration(state);
  }

  async function copyResult() {
    if (!state.output) return;
    const copied = await writeClipboardValue(state.output, "✓ 已复制到剪贴板");
    if (!copied) return;
    state = { ...state, copied: true };
    window.setTimeout(() => {
      state = { ...state, copied: false };
    }, 1400);
  }

  function exportResultMarkdown() {
    if (!state.output) return;
    triggerDownload(
      document,
      resultMarkdownContent(state.output),
      resultMarkdownFilename(),
      TEXT_MARKDOWN_MIME,
      window
    );
    showToast("结果已导出为 Markdown");
  }

  function openResultCompare() {
    if (!state.output || !state.currentResult?.sourceText?.trim()) return;
    state = { ...state, overlay: "result_compare" };
  }

  async function copyComparisonSource() {
    const source = state.currentResult?.sourceText;
    if (!source) return;
    await writeClipboardValue(source, tr("原文已复制"));
  }

  async function copyComparisonResult() {
    if (!state.output) return;
    await writeClipboardValue(state.output, tr("优化结果已复制"));
  }

  function openTranslationView() {
    translationFlow.open(state.currentResult ?? null, translatorEnabled);
  }

  function runTranslation() {
    void translationFlow.run();
  }

  function chooseTranslationTarget(target: TranslationTarget) {
    translationFlow.chooseTarget(target);
  }

  function cancelTranslationRun() {
    translationFlow.cancel();
  }

  function closeTranslationView() {
    translationFlow.close();
  }

  function copyTranslation() {
    void translationFlow.copy();
  }

  function useTranslationAsCurrentResult() {
    translationFlow.useAsCurrentResult();
  }

  function openMarkdownPreviewView() {
    markdownPreviewFlow.open(state.currentResult?.output ?? "", markdownPreviewEnabled);
  }

  function runMarkdownPreview() {
    void markdownPreviewFlow.run();
  }

  function closeMarkdownPreviewView() {
    markdownPreviewFlow.close();
  }

  function openBatchView() {
    if (!batchRunnerEnabled) return;
    if ($markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if ($translation.phase !== "closed") closeTranslationView();
    batchFlow.open();
  }

  function closeBatchView() {
    batchFlow.close();
  }

  function openTemplateManager() {
    if ($batch.phase !== "closed") closeBatchView();
    selectedTemplateId = null;
    templateDraft = createTemplateDraft();
    templateValues = {};
    templateNotice = null;
    state = { ...state, overlay: "template_manager" };
  }

  function closeTemplateManager() {
    state = { ...state, overlay: null };
    templateNotice = null;
  }

  function selectTemplate(template: PromptTemplate) {
    selectedTemplateId = template.id;
    templateDraft = createTemplateDraft(template);
    templateValues = Object.fromEntries(templateVariables(template.content).map((name) => [name, ""]));
    templateNotice = null;
  }

  async function saveTemplate() {
    if (templateBusy || !persistedConfig || !settingsApi) {
      templateNotice = "模板暂时无法保存，请重试。";
      return;
    }
    const next = saveCustomTemplate(customTemplates, templateDraft, selectedTemplateId ?? undefined);
    if (!next) {
      templateNotice = "请填写名称、分类和模板内容。";
      return;
    }
    templateBusy = true;
    try {
      const saved = await saveConfigSerial(settingsApi, (latest) => ({
        ...latest,
        custom_templates: next
      }));
      persistedConfig = saved;
      customTemplates = readCustomTemplates(saved.custom_templates);
      const selected = customTemplates.find((template) => template.id === (selectedTemplateId ?? next.at(-1)?.id));
      if (selected) selectTemplate(selected);
      templateNotice = "模板已保存。";
    } catch {
      templateNotice = "模板暂时无法保存，请重试。";
    } finally {
      templateBusy = false;
    }
  }

  async function deleteTemplate() {
    if (!selectedTemplateId || templateBusy || !persistedConfig || !settingsApi) return;
    confirmation = {
      title: tr("删除当前模板？"),
      description: tr("删除后无法恢复，但不会影响已经生成的内容。"),
      confirmLabel: tr("删除模板"),
      run: performDeleteTemplate
    };
  }

  async function performDeleteTemplate() {
    if (!selectedTemplateId || templateBusy || !persistedConfig || !settingsApi) return;
    templateBusy = true;
    try {
      const next = removeCustomTemplate(customTemplates, selectedTemplateId);
      const saved = await saveConfigSerial(settingsApi, (latest) => ({
        ...latest,
        custom_templates: next
      }));
      persistedConfig = saved;
      customTemplates = readCustomTemplates(saved.custom_templates);
      selectedTemplateId = null;
      templateDraft = createTemplateDraft();
      templateValues = {};
      templateNotice = "模板已删除。";
    } catch {
      templateNotice = "模板暂时无法删除，请重试。";
    } finally {
      templateBusy = false;
    }
  }

  function applyTemplate() {
    const rendered = renderTemplate(templateDraft.content, templateValues);
    if (!rendered) {
      templateNotice = "请填写全部变量后再应用。";
      return;
    }
    state = updateInput(state, rendered);
    closeTemplateManager();
    showToast("模板已应用到输入区");
  }

  function parseBatchSource() {
    return batchFlow.parse();
  }

  function importBatchFile(file: File) {
    return batchFlow.importFile(file);
  }

  function downloadBatchTemplate() {
    batchFlow.downloadTemplate();
  }

  function runBatch() {
    return batchFlow.run();
  }

  function cancelBatchRun() {
    batchFlow.cancel();
  }

  function exportBatch() {
    return batchFlow.export();
  }

  async function rateCurrentResult(rating: number) {
    const historyId = state.currentResult?.historyId;
    if (!historyId || state.currentResult?.saveStatus !== "saved" || resultRatingBusy) return;
    const bridge = capabilityBridge;
    if (!bridge) {
      showToast("评分未保存，请稍后重试。");
      return;
    }
    resultRatingBusy = true;
    let saved = false;
    try {
      for await (const event of bridge.invoke("history-sqlite", "rate", { id: historyId, rating })) {
        if (event.status === "result") saved = true;
        if (event.status === "error" || event.status === "cancelled") break;
      }
    } catch {
      saved = false;
    } finally {
      resultRatingBusy = false;
    }
    if (!saved) {
      showToast("评分未保存，请稍后重试。");
      return;
    }
    state = applyCurrentResultRating(state, historyId, rating);
    showToast("评分已保存");
  }

  function openHistoryWindow() {
    void hostApi?.invoke("show_history_window").catch(() => showToast("历史记录暂时不可用。"));
  }

  function saveStatusLabel(): string {
    const status = state.currentResult?.saveStatus ?? "unsaved";
    if (status === "saved") return "已保存到本机";
    if (status === "private") return "隐私模式";
    if (status === "saving") return "正在保存";
    return "未保存";
  }

  function askReplaceClipboard() {
    if (!state.output) return;
    void executeClipboardAction(
      clipboardActionForManualReplace(persistedConfig?.clipboard_replace_confirmed === true)
    );
  }

  async function confirmReplaceClipboard() {
    const replaced = await writeClipboardValue(state.output, "✓ 已替换剪贴板");
    if (!replaced) return;
    await rememberClipboardConfirmation();
    state = { ...state, overlay: null };
    clipboardNotice = null;
  }

  async function copyDiagnosticId() {
    if (!state.diagnosticId) return;
    await writeClipboardValue(state.diagnosticId, "✓ 诊断 ID 已复制");
  }

  function beginFeedback(sentiment: FeedbackSentiment) {
    if (!state.currentResult?.output) return;
    feedbackPromptOpen = false;
    confirmation = {
      title: sentiment === "negative" ? "反馈这次不满意的结果？" : "反馈这次满意的结果？",
      description: "继续后只截取 Reflex 当前窗口，并在发送前显示预览。输入、结果和截图都可以单独移除。",
      confirmLabel: "继续反馈",
      danger: false,
      run: () => openFeedback(sentiment, "manual", true)
    };
  }

  async function openFeedback(
    sentiment: FeedbackSentiment,
    source: "manual" | "prompt",
    captureScreenshot: boolean
  ) {
    feedbackSentiment = sentiment;
    feedbackSource = source;
    feedbackScreenshot = null;
    feedbackCaptureNotice = null;
    feedbackSubmitNotice = null;
    await tick();
    if (captureScreenshot && feedbackBridge) {
      try {
        feedbackScreenshot = await feedbackBridge.captureWindow();
      } catch {
        feedbackCaptureNotice = "窗口截图失败，可以不附加截图继续反馈。";
      }
    } else if (captureScreenshot) {
      feedbackCaptureNotice = "当前环境无法截取应用窗口。";
    }
    feedbackOpen = true;
  }

  async function answerFeedbackPrompt(sentiment: FeedbackSentiment) {
    const result = state.currentResult;
    const bridge = feedbackBridge;
    if (feedbackPromptBusy) return;
    if (!result || !bridge) {
      feedbackPromptNotice = "反馈服务暂不可用，请稍后重试。";
      return;
    }

    feedbackPromptBusy = true;
    feedbackPromptNotice = null;
    try {
      const latestConsent = await bridge.getConsent();
      cloudConsent = latestConsent;
      await bridge.submit(createPromptFeedbackPayload({
        sentiment,
        context: feedbackContextFor(result),
        consentVersion: latestConsent.policy_version
      }));
      feedbackPromptOpen = false;
      showToast("反馈已记录，谢谢。", "success");
    } catch (error) {
      feedbackPromptNotice = feedbackSubmitErrorMessage(error);
    } finally {
      feedbackPromptBusy = false;
    }
  }

  function postponeFeedbackPrompt() {
    if (feedbackPromptBusy) return;
    feedbackPromptOpen = false;
    feedbackPromptNotice = null;
    void persistFeedbackPrompt(snoozeFeedbackPrompt(feedbackPromptState));
  }

  function turnOffFeedbackPrompt() {
    if (feedbackPromptBusy) return;
    feedbackPromptOpen = false;
    feedbackPromptNotice = null;
    void persistFeedbackPrompt(disableFeedbackPrompt(feedbackPromptState));
    showToast("已关闭主动反馈询问");
  }

  function feedbackContextFor(result: CurrentResult): FeedbackContext {
    return {
      app_version: appVersion,
      os_version: navigator.userAgent.slice(0, 128),
      provider: result.provider ?? state.requestDraft.provider ?? "",
      model: result.model ?? state.requestDraft.model ?? "",
      mode: result.mode,
      style: result.style,
      scene: result.scene ?? state.detectedScene ?? "",
      request_id: result.requestId,
      diagnostic_id: state.diagnosticId ?? "",
      error_code: state.errorCode ?? "",
      elapsed_ms: result.elapsedMs
    };
  }

  function closeFeedback() {
    if (feedbackSubmitBusy) return;
    feedbackOpen = false;
    feedbackScreenshot = null;
    feedbackCaptureNotice = null;
    feedbackSubmitNotice = null;
    feedbackSource = "manual";
  }

  function removeFeedbackScreenshot() {
    feedbackScreenshot = null;
  }

  async function submitFeedback(form: FeedbackFormValue) {
    const result = state.currentResult;
    if (!result || !feedbackBridge || feedbackSubmitBusy) {
      feedbackSubmitNotice = "反馈服务暂不可用，请稍后重试。";
      return;
    }
    feedbackSubmitBusy = true;
    feedbackSubmitNotice = null;
    const sourceText = result.sourceText ?? state.inputText;
    try {
      const latestConsent = await feedbackBridge.getConsent();
      cloudConsent = latestConsent;
      await feedbackBridge.submit({
        source: feedbackSource,
        sentiment: feedbackSentiment,
        category: form.category,
        message: form.message,
        expected_output: form.expectedOutput,
        contact: form.contact,
        context: feedbackContextFor(result),
        include_prompt: form.includePrompt,
        include_result: form.includeResult,
        include_screenshot: form.includeScreenshot && feedbackScreenshot !== null,
        prompt_text: form.includePrompt ? sourceText : null,
        result_text: form.includeResult ? result.output : null,
        screenshot: form.includeScreenshot ? feedbackScreenshot : null,
        consent_version: latestConsent.policy_version
      });
      feedbackOpen = false;
      feedbackScreenshot = null;
      feedbackSource = "manual";
      showToast("反馈已发送，谢谢。", "success");
    } catch (error) {
      feedbackSubmitNotice = feedbackSubmitErrorMessage(error);
    } finally {
      feedbackSubmitBusy = false;
    }
  }

  async function handleCompletionClipboard() {
    const policy = persistedConfig?.clipboard_policy ?? "manual";
    await executeClipboardAction(
      clipboardActionAfterCompletion(
        policy,
        persistedConfig?.clipboard_replace_confirmed === true
      )
    );
  }

  async function executeClipboardAction(action: ClipboardAction) {
    if (action === "none") return;
    if (action === "confirm") {
      clipboardNotice = null;
      state = { ...state, overlay: "clipboard_confirm" };
      return;
    }
    await writeClipboardValue(state.output, "✓ 已替换剪贴板");
  }

  async function writeClipboardValue(text: string, successMessage: string): Promise<boolean> {
    const result = await writeClipboardText(clipboardWriter, text);
    if (!result.ok) {
      clipboardNotice = result.message;
      showToast(result.message);
      return false;
    }
    clipboardNotice = null;
    showToast(successMessage);
    return true;
  }

  async function rememberClipboardConfirmation() {
    if (!persistedConfig) return;
    const confirmedConfig = {
      ...persistedConfig,
      clipboard_replace_confirmed: true
    };
    persistedConfig = confirmedConfig;
    if (!settingsApi) return;
    try {
      persistedConfig = await saveConfigSerial(settingsApi, (latest) => ({
        ...latest,
        clipboard_replace_confirmed: true
      }));
      settingsDraft = settingsDraftFromConfig(persistedConfig);
    } catch {
      clipboardNotice = "本次已替换，下次使用时仍会再次确认。";
    }
  }

  function retryRun() {
    state = retryAfterError(state);
    void runOptimization();
  }

  function openSettingsView() {
    beginSettings();
  }

  async function persistActivationState(next: ActivationState): Promise<boolean> {
    const previous = activationState;
    activationState = next;
    const api = settingsApi;
    const config = persistedConfig;
    if (!api || !config) {
      activationState = previous;
      activationNotice = "首次使用状态暂未保存，本次仍可继续使用。";
      return false;
    }
    try {
      const saved = await saveConfigSerial(api, (latest) => ({
        ...latest,
        first_run_activation: next
      }));
      persistedConfig = saved;
      activationState = normalizeActivationState(saved.first_run_activation);
      return true;
    } catch {
      activationState = previous;
      activationNotice = "首次使用状态暂未保存，本次仍可继续使用。";
      return false;
    }
  }

  async function chooseActivationRoute(route: ActivationRoute) {
    if (!availableActivationRoutes(cloudAvailability).includes(route)) return;
    const next = selectActivationRoute(activationState, route);
    const persisted = await persistActivationState(next);
    if (!persisted) return;
    activationNotice = "";
    if (route === "cloud") {
      const model = providerDefaultModel("reflex-cloud", providerOptions);
      if (model) switchWorkbenchModel("reflex-cloud", model);
      return;
    }
    openByokSettings();
  }

  function openByokSettings() {
    const providerId = preferredByokProvider(
      persistedConfig?.provider ?? activeProviderId,
      providerOptions.map((provider) => provider.id)
    );
    beginSettings(providerId);
  }

  function continueFirstRun() {
    activationOpen = false;
    activationNotice = "";
  }

  function postponeFirstRun() {
    activationOpen = false;
    activationNotice = "";
  }

  async function completeFirstRunActivation() {
    if (activationState.completed) return;
    const route = activationState.route ?? activationRouteForProvider(activeProviderId);
    const completed = completeActivation(selectActivationRoute(activationState, route));
    const persisted = await persistActivationState(completed);
    if (persisted) {
      activationOpen = false;
      activationNotice = "";
    }
  }

  function providerReadyForActivation(providerId: string | null): boolean {
    if (providerId === "reflex-cloud") return cloudAvailability === "ready";
    return (
      providerId !== null &&
      secretStatus.providerId === providerId &&
      secretStatus.configured &&
      !providerStatusError
    );
  }

  async function finishFirstRunFromSettings(providerId: string | null) {
    if (!activationOpen || !providerReadyForActivation(providerId)) return;
    await completeFirstRunActivation();
    if (activationState.completed) cancelSettingsView();
  }

  function managePluginSettings() {
    beginSettings();
    settingsSection = "plugins";
    void refreshSemanticModelStatus();
  }

  function setPluginEnabled(pluginId: SettingsPluginId, enabled: boolean) {
    settingsDraft = updatePluginSettingsDraft(settingsDraft, pluginId, enabled);
    if (pluginId === "semantic-detector" && !enabled) {
      semanticModelRun?.abort();
      semanticModel = createSemanticModelState();
    }
  }

  function selectSettingsSection(section: SettingsSection) {
    settingsSection = section;
    if (section === "plugins") void refreshSemanticModelStatus();
  }

  async function refreshSemanticModelStatus() {
    if (!persistedConfig?.enabled_plugins.includes("semantic-detector")) return;
    await runSemanticModelOperation("status");
  }

  async function downloadSemanticModel() {
    await runSemanticModelOperation("download");
  }

  async function deleteSemanticModel() {
    confirmation = {
      title: tr("删除本地语义模型？"),
      description: tr("删除后场景识别会自动回退，之后仍可重新下载。"),
      confirmLabel: tr("删除模型"),
      run: () => runSemanticModelOperation("delete")
    };
  }

  async function confirmCurrentAction() {
    const current = confirmation;
    confirmation = null;
    await current?.run();
  }

  function cancelSemanticModelDownload() {
    semanticModelRun?.abort();
  }

  async function runSemanticModelOperation(operation: "status" | "download" | "delete") {
    const bridge = capabilityBridge;
    if (!bridge || !persistedConfig?.enabled_plugins.includes("semantic-detector")) return;
    semanticModelRun?.abort();
    const controller = new AbortController();
    semanticModelRun = controller;
    semanticModel = beginSemanticModelOperation(semanticModel, operation);
    try {
      for await (const event of bridge.invoke("semantic-detector", operation, {}, {
        signal: controller.signal,
        timeoutMs: operation === "download" ? 1_800_000 : 30_000
      })) {
        if (semanticModelRun !== controller || controller.signal.aborted) return;
        semanticModel = applySemanticModelEvent(semanticModel, event);
      }
    } catch {
      if (semanticModelRun !== controller) return;
      semanticModel = controller.signal.aborted
        ? {
            ...semanticModel,
            phase: semanticModel.sizeBytes > 0 ? "ready" : "missing",
            percent: 0,
            errorCode: null
          }
        : failSemanticModelOperation(semanticModel);
    } finally {
      if (semanticModelRun === controller) semanticModelRun = null;
    }
  }

  function semanticModelStatusText(): string {
    if (!semanticDetectorActive && semanticDetectorEnabled) return "保存设置后即可管理本地模型。";
    if (semanticModel.phase === "loading") return "正在检查本地模型…";
    if (semanticModel.phase === "downloading") return tr("正在下载 {percent}%", { percent: semanticModel.percent });
    if (semanticModel.phase === "deleting") return "正在删除本地模型…";
    if (semanticModel.phase === "ready") return tr("模型已就绪 · {size}", { size: semanticModelSizeLabel(semanticModel.sizeBytes) });
    if (semanticModel.phase === "missing") {
      return semanticModel.runtimeReady
        ? "尚未下载本地语义模型。"
        : "本地语义运行组件尚未安装。";
    }
    if (semanticModel.phase === "error") {
      if (semanticModel.errorCode === "model_runtime_missing") return "缺少本地模型下载组件。";
      if (semanticModel.errorCode === "model_download_failed") return "模型下载失败，请检查网络后重试。";
      if (semanticModel.errorCode === "model_download_incomplete") return "模型文件不完整，请重新下载。";
      if (semanticModel.errorCode === "model_delete_failed") return "本地模型删除失败。";
      return "本地模型状态暂时不可用。";
    }
    return "检查本地模型后可启用更准确的场景识别。";
  }

  function closeOverlay() {
    if (state.overlay === "settings") {
      cancelSettingsView();
      return;
    }
    clipboardNotice = null;
    state = { ...state, overlay: null };
  }

  function handleKeydown(event: KeyboardEvent) {
    if (feedbackPromptOpen && event.key === "Escape") {
      event.preventDefault();
      postponeFeedbackPrompt();
      return;
    }
    if (scenePromptOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelScenePrompt();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      commandPaletteOpen = !commandPaletteOpen;
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key === ",") {
      event.preventDefault();
      beginSettings();
      return;
    }
    if (commandPaletteOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPalette();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        viewScale.step("in");
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        viewScale.step("out");
        return;
      }
      if (event.key === "0") {
        event.preventDefault();
        viewScale.reset();
        return;
      }
    }
    if (state.overlay === "template_manager") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeTemplateManager(true);
      }
      return;
    }
    if ($batch.phase !== "closed") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeBatchView();
      }
      return;
    }
    if ($markdownPreview.phase !== "closed") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMarkdownPreviewView(true);
      }
      return;
    }
    if ($translation.phase !== "closed") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeTranslationView(true);
      }
      return;
    }
    const action = resolveHostShortcut(state, {
      key: event.key,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey
    });
    if (action === "none") return;

    event.preventDefault();
    if (action === "generate") {
      void runOptimization();
      return;
    }
    if (action === "cancel_generation") {
      cancelRun();
      return;
    }
    if (action === "close_overlay") {
      closeOverlay();
      return;
    }
    if (action === "leave_adjust") {
      cancelAdjustView();
      return;
    }
    void hostApi?.invoke("hide_main_window").catch(() => undefined);
  }

  async function minimizeWindow() {
    try {
      await desktopBridge?.minimizeWindow();
    } catch {
      showToast("窗口操作暂不可用。");
    }
  }

  async function toggleMaximizeWindow() {
    try {
      await desktopBridge?.toggleMaximizeWindow();
    } catch {
      showToast("窗口操作暂不可用。");
    }
  }

  async function setWindowSize(preset: WindowSizePreset) {
    try {
      await desktopBridge?.setWindowSize(preset);
      windowSizePreset = preset;
    } catch {
      showToast("窗口尺寸暂不可用。");
    }
  }

  function isGenerating(phase: HostState["phase"]): boolean {
    return phase === "analyzing_scene" || phase === "connecting_provider" || phase === "streaming";
  }

  function providerAvailabilityLabel(value: ProviderAvailability): string {
    if (value === "ready") return tr("已配置");
    if (value === "missing") return tr("未配置");
    if (value === "unavailable") return tr("暂不可用");
    return tr("检查中");
  }

  function modeLabel(value: OptimizeMode): string {
    return tr(modes.find((item) => item.id === value)?.label ?? "内容优化");
  }

  function styleLabel(value: ResultStyle): string {
    if (value === "precise") return tr("精准");
    return tr(styles.find((item) => item.id === value)?.label ?? "平衡");
  }

  function sceneLabel(value: string | null): string {
    return tr(scenes.find((item) => item.id === value)?.label ?? "自动识别");
  }

  function translationLanguageLabel(value: TranslationLanguage | null): string {
    if (value === "zh") return tr("中文");
    if (value === "en") return "English";
    return tr("自动识别");
  }

</script>

<svelte:window on:keydown={handleKeydown} />

<main
  class="app-shell outer-contour"
  data-phase={state.phase}
  data-theme={settingsDraft.theme}
  data-dialog-focus-fallback
    tabindex="-1"
    style={`--view-scale: ${$viewScale}`}
  >
  <section
    class="window"
    aria-label="Reflex quick window"
    inert={state.overlay === "settings" || activationOpen}
  >
    <ReflexTitleBar
      providerName={tr(providerName(state.requestDraft.provider, providerOptions))}
      modelName={state.requestDraft.model ?? ""}
      availability={providerStatus}
      availabilityLabel={providerStatusText}
      scale={$viewScale}
      windowSize={windowSizePreset}
      onOpenProvider={beginSettings}
      onOpenCommand={openCommandPalette}
      onZoomOut={() => viewScale.step("out")}
      onResetZoom={() => viewScale.reset()}
      onZoomIn={() => viewScale.step("in")}
      onWindowSizeChange={desktopBridge ? setWindowSize : undefined}
      onMinimize={desktopBridge ? minimizeWindow : undefined}
      onMaximize={desktopBridge ? toggleMaximizeWindow : undefined}
      onClose={hostApi ? hideMainWindow : undefined}
    />

    <div class="shell-main">
      <NavRail items={navItems} {activeNavId} onSelect={handleNavigation} />
      <section class="workbench-surface" aria-label={tr("工作台")} bind:this={workbenchSurfaceEl}>
        <div class="workbench-grid">
          <div class="input-column">
            <InputPane
              value={state.inputText}
              phase={workbenchPhase}
              label={t(uiLanguage, "input")}
              placeholder={t(uiLanguage, "paste")}
              notice={state.inputNotice ? tr(state.inputNotice) : ""}
              maxLength={100_000}
              disabled={state.phase === "adjusting"}
              clipboardBusy={clipboardReading}
              quickActions={quickActions}
              onInput={setInput}
              onQuickAction={applyQuickActionToDraft}
              onRun={runOptimization}
              onReadClipboard={readClipboard}
              onClear={clearInput}

            />
            <ConfigSummary
              items={configSummaryItems}
              models={selectableModels}
              selectedProvider={state.requestDraft.provider}
              selectedModel={state.requestDraft.model}
              phase={workbenchPhase}
              canRun={canGenerate}
              statusMessage={workbenchStatusMessage}
              trustSummary={generationTrust}
              onRun={runOptimization}
              onCancel={cancelRun}
              onAdjust={beginAdjust}
              onModelChange={switchWorkbenchModel}

            />
          </div>
          <ResultPane
            phase={workbenchPhase}
            output={state.output}
            statusMessage={workbenchStatusMessage}
            errorMessage={state.errorMessage ? tr(state.errorMessage) : t(uiLanguage, "noProvider")}
            errorRecoverable={state.errorRecoverable}
            errorAction={state.errorAction}
            diagnosticId={state.diagnosticId}
            sceneLabel={state.detectedScene ? sceneLabel(state.detectedScene) : state.currentResult?.scene ? sceneLabel(state.currentResult.scene) : null}
            elapsedMs={state.currentResult?.elapsedMs ?? null}
            sourceAvailable={Boolean(state.currentResult?.sourceText?.trim())}
            historyStatus={state.currentResult ? saveStatusLabel() : ""}
            meta={resultMetaItems}
            copied={state.copied || ($toast.message.includes("已复制") && $toast.visible)}
            rating={state.currentResult?.rating ?? null}
            ratingEnabled={state.currentResult?.saveStatus === "saved" && !resultRatingBusy}
            onCopy={copyResult}
            onReplace={askReplaceClipboard}
            onAdjust={beginAdjust}
            onRegenerate={runOptimization}
            onExport={exportResultMarkdown}
            onOpenHistory={openHistoryWindow}
            onRate={rateCurrentResult}
            onTranslate={translatorEnabled && state.currentResult?.output ? openTranslationView : undefined}
            onPreview={markdownPreviewEnabled && state.currentResult?.output ? openMarkdownPreviewView : undefined}
            onCompare={state.currentResult?.sourceText?.trim() ? openResultCompare : undefined}
            onRetry={state.errorRecoverable && state.errorAction !== "settings" && state.errorAction !== "edit" && state.errorAction !== "restart" ? retryRun : undefined}
            onOpenSettings={state.errorAction === "settings" ? openSettingsView : undefined}
            onCopyDiagnosticId={state.diagnosticId ? copyDiagnosticId : undefined}
            onPositiveFeedback={() => beginFeedback("positive")}
            onNegativeFeedback={() => beginFeedback("negative")}

          />
        </div>
      </section>
    </div>

    <StatusBar
      message={workbenchStatusMessage}
      tone={statusTone}
      inputCount={state.inputText.length}
      languageLabel={uiLanguage === "zh-CN" ? "中文" : "English"}
      themeLabel={settingsDraft.theme === "system" ? tr("系统") : settingsDraft.theme === "dark" ? tr("深色") : tr("浅色")}
      versionLabel={`v${appVersion}`}
    />

    <Toast visible={$toast.visible} message={$toast.message} tone={$toast.tone} />

    {#if confirmation}
      <ConfirmDialog
        title={confirmation.title}
        description={confirmation.description}
        confirmLabel={confirmation.confirmLabel}
        cancelLabel={tr("取消")}
        danger={confirmation.danger ?? true}
        onCancel={() => (confirmation = null)}
        onConfirm={confirmCurrentAction}
      />
    {/if}

    {#if feedbackOpen}
      <FeedbackDialog
        sentiment={feedbackSentiment}
        screenshot={feedbackScreenshot}
        captureNotice={feedbackCaptureNotice}
        improvementConsent={cloudConsent.improvement_data}
        busy={feedbackSubmitBusy}
        notice={feedbackSubmitNotice}

        onClose={closeFeedback}
        onRemoveScreenshot={removeFeedbackScreenshot}
        onSubmit={submitFeedback}
      />
    {/if}

    {#if feedbackPromptOpen}
      <FeedbackPromptDialog
        busy={feedbackPromptBusy}
        notice={feedbackPromptNotice}

        onPositive={() => answerFeedbackPrompt("positive")}
        onNegative={() => answerFeedbackPrompt("negative")}
        onLater={postponeFeedbackPrompt}
        onDisable={turnOffFeedbackPrompt}
      />
    {/if}

    {#if scenePromptOpen}
      <ScenePromptDialog
        {scenes}
        selectedScene={scenePromptSelection}

        onSceneChange={(sceneId) => (scenePromptSelection = sceneId)}
        onCancel={cancelScenePrompt}
        onConfirm={confirmScenePrompt}
      />
    {/if}

    {#if state.phase === "adjusting"}
      <AdjustPanel
        {draft}
        inputText={state.inputText}
        {modes}
        {styles}
        {scenes}
        models={selectableModels}

        onDraftChange={(value) => (draft = value)}
        onCancel={cancelAdjustView}
        onApply={applyAdjust}
      />
    {/if}

    {#if commandPaletteOpen}
      <CommandPalette items={commandItems} onClose={closeCommandPalette} />
    {/if}

    {#if state.overlay === "template_manager"}
      <TemplateManagerDialog
        query={templateQuery}
        category={templateCategory}
        categories={templateCategories}
        templates={visibleTemplates}
        selectedId={selectedTemplateId}
        draft={templateDraft}
        values={templateValues}
        notice={templateNotice}
        busy={templateBusy}

        onQueryChange={(value) => (templateQuery = value)}
        onCategoryChange={(value) => (templateCategory = value)}
        onNew={() => { selectedTemplateId = null; templateDraft = createTemplateDraft(); templateValues = {}; templateNotice = null; }}
        onSelect={selectTemplate}
        onDraftChange={(value) => (templateDraft = value)}
        onValuesChange={(value) => (templateValues = value)}
        onDelete={deleteTemplate}
        onSave={saveTemplate}
        onApply={applyTemplate}
        onClose={() => closeTemplateManager(true)}
      />
    {/if}

    {#if $batch.phase !== "closed"}
      <BatchDialog
        state={$batch}
        fileNotice={$batchFileNotice}
        {styles}
        {scenes}

        onStateChange={(value) => ($batch = value)}
        onFileSelected={importBatchFile}
        onDownloadTemplate={downloadBatchTemplate}
        onParse={parseBatchSource}
        onCancel={cancelBatchRun}
        onExport={exportBatch}
        onRun={runBatch}
        onClose={closeBatchView}
      />
    {/if}

    {#if $translation.phase !== "closed"}
      <TranslationDialog
        state={$translation}
        sourceLanguageLabel={translationLanguageLabel($translation.sourceLanguage)}
        targetLanguageLabel={translationLanguageLabel($translation.targetLanguage)}

        onTargetChange={chooseTranslationTarget}
        onCancel={cancelTranslationRun}
        onRetry={runTranslation}
        onCopy={copyTranslation}
        onUseResult={useTranslationAsCurrentResult}
        onClose={closeTranslationView}
      />
    {/if}

    {#if $markdownPreview.phase !== "closed"}
      <MarkdownPreviewDialog
        state={$markdownPreview}

        onModeChange={(mode) => markdownPreviewFlow.setMode(mode)}
        onCopySource={() => writeClipboardValue($markdownPreview.sourceText, "✓ 源码已复制")}
        onRetry={runMarkdownPreview}
        onClose={closeMarkdownPreviewView}
      />
    {/if}

    {#if state.overlay === "clipboard_confirm"}
      <ClipboardConfirmDialog notice={clipboardNotice} onCancel={closeOverlay} onConfirm={confirmReplaceClipboard} />
    {/if}

    {#if state.overlay === "result_compare"}
      <ResultCompareDialog
        sourceText={state.currentResult?.sourceText ?? ""}
        output={state.output}

        onCopySource={copyComparisonSource}
        onCopyOutput={copyComparisonResult}
        onClose={closeOverlay}
      />
    {/if}

    {#if state.overlay === "plugin_manager"}
      <PluginDialog onManage={managePluginSettings} onClose={closeOverlay} />
    {/if}

  </section>

    {#if state.overlay === "settings"}
      <SettingsDialog
        draft={settingsDraft}
        section={settingsSection}
        busy={settingsBusy}
        {secretBusy}
        {secretInput}
        {secretStatus}
        {secretNotice}
        {providerConnectionBusy}
        {providerConnectionNotice}
        notice={settingsNotice}
        {providerCatalogNotice}
        providers={providerOptions}
        models={settingsProviderModels}
        {modes}
        {styles}
        {desktopStatus}
        {semanticModel}
        semanticEnabled={semanticDetectorEnabled}
        semanticActive={semanticDetectorActive}
        semanticStatusText={semanticModelStatusText()}
        diagnosticBusy={diagnosticExportBusy}
        diagnosticNotice={diagnosticExportNotice}
        cloudUsageMetricsEnabled={cloudUsageMetricsDraft}
        cloudImprovementEnabled={cloudImprovementDraft}
        feedbackPromptEnabled={feedbackPromptEnabledDraft}
        {cloudQualityRelease}
        {cloudQuota}
        {cloudPrivacyBusy}
        {cloudPrivacyNotice}

        onClose={cancelSettingsView}
        onSave={saveSettings}
        onSectionChange={selectSettingsSection}
        onDraftChange={(value) => (settingsDraft = value)}
        onProviderChange={selectSettingsProvider}
        onSecretInput={(value) => (secretInput = value)}
        onSaveSecret={saveSecret}
        onDeleteSecret={deleteSecret}
        onBaseUrlChange={updateProviderBaseUrl}
        onDiscoverModels={discoverProviderModels}
        onTestConnection={testProviderConnection}
        onModelCandidatesChange={(models) => {
          const providerId = settingsDraft.default_provider ?? "minimax";
          settingsDraft = {
            ...settingsDraft,
            provider_models: { ...settingsDraft.provider_models, [providerId]: models }
          };
          providerOptions = withConfiguredModels(providerOptions, settingsDraft.provider_models);
        }}
        onPluginChange={setPluginEnabled}
        onSemanticRefresh={refreshSemanticModelStatus}
        onSemanticCancel={cancelSemanticModelDownload}
        onSemanticDelete={deleteSemanticModel}
        onSemanticDownload={downloadSemanticModel}
        onDiagnosticExport={exportDiagnosticBundle}
        onDiagnosticCancel={cancelDiagnosticBundleExport}
        onCloudUsageMetricsChange={(enabled) => (cloudUsageMetricsDraft = enabled)}
        onCloudImprovementChange={(enabled) => (cloudImprovementDraft = enabled)}
        onFeedbackPromptEnabledChange={(enabled) => (feedbackPromptEnabledDraft = enabled)}
        onCloudRefresh={hydrateCloudPrivacy}
        onCloudDeleteData={confirmDeleteCloudData}
      />
    {/if}

  {#if activationOpen && state.overlay !== "settings"}
    <FirstRunDialog
      routes={activationRoutes}
      selectedRoute={activationState.route}
      providerReady={activationProviderReady}
      providerLabel={activeProviderLabel}
      notice={activationNotice}

      onChoose={chooseActivationRoute}
      onOpenSettings={openByokSettings}
      onContinue={continueFirstRun}
      onLater={postponeFirstRun}
    />
  {/if}
</main>
