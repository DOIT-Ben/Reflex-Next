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
    type ActivationRoute
  } from "./domain/activationState";
  import { createCloudPrivacyFlow } from "./domain/cloudPrivacyFlow";
  import { createDiagnosticFlow } from "./domain/diagnosticFlow";
  import { createSettingsFlow } from "./domain/settingsFlow";
  import {
    createFeedbackBridge,
    type FeedbackBridge,
    type FeedbackContext,
    type FeedbackFormValue,
    type FeedbackSentiment
  } from "./domain/feedbackBridge";
  import { normalizeFeedbackPromptState } from "./domain/feedbackPrompt";
  import { createFeedbackFlow } from "./domain/feedbackFlow";
  import { createFirstRunFlow } from "./domain/firstRunFlow";
  import { createOptimizationFlow } from "./domain/optimizationFlow";
  import {
    createDefaultCoreBridge,
    createDemoCoreBridge,
    UnavailableCoreBridge
  } from "./domain/coreBridge";
  import {
    applyAdjustDraft,
    applyClipboardError,
    applyClipboardText,
    applyCurrentResultRating,
    applyHistoryReuseIntent,
    applyHostAction,
    applyPersistedConfig,
    applySettingsDraft,
    cancelAdjust,
    cancelSettings,
    configFromSettingsDraft,
    createDefaultSettingsDraft,
    createHostState,
    openAdjust,
    openSettings,
    resolveHostShortcut,
    retryAfterError,
    selectRequestModel,
    settingsDraftFromConfig,
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
    createClipboardReader,
    createClipboardWriter,
    readClipboardText,
    shouldReadClipboardOnStartup,
    type ClipboardReader,
    type ClipboardWriter
  } from "./domain/clipboardBridge";
  import { createClipboardFlow } from "./domain/clipboardFlow";
  import {
    createDesktopBridge,
    safeDesktopSettingsError,
    type DesktopBridge,
    type HostAction
  } from "./domain/desktopBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import { createTranslationFlow } from "./domain/translationFlow";
  import { createMarkdownPreviewFlow } from "./domain/markdownPreviewFlow";
  import { createBatchFlow } from "./domain/batchFlow";
  import type { TranslationLanguage, TranslationTarget } from "./domain/translationState";
  import type { ProviderCatalogBridge } from "./domain/providerCatalogBridge";
  import { createProviderCatalogBridge } from "./domain/providerCatalogBridge";
  import type { ProviderConnectionBridge } from "./domain/providerConnectionBridge";
  import { createProviderConnectionBridge } from "./domain/providerConnectionBridge";
  import type { DiagnosticBundleBridge } from "./domain/diagnosticBundleBridge";
  import { createDiagnosticBundleBridge } from "./domain/diagnosticBundleBridge";
  import {
    type WindowSizePreset
  } from "./domain/viewControls";
  import type { SettingsApi } from "./domain/settingsApi";
  import { createSettingsApi } from "./domain/settingsApi";
  import type { CoreBridge, TauriHostApi } from "./domain/coreBridge";
  import { createTemplateFlow } from "./domain/templateFlow";
  import { readCustomTemplates, type PromptTemplate } from "./domain/templateLibrary";
  import {
    providerDefaultModel,
    providerName,
    providerModels,
    workbenchModelOptions,
    resolveProviderAvailability,
    type ProviderAvailability
  } from "./domain/providerCatalog";
  import {
    applyQuickAction,
    generationTrustSummary,
    preferredByokProvider,
    quickActions
  } from "./domain/productExperience";
  import {
    semanticModelSizeLabel
  } from "./domain/semanticModelState";
  import { createSemanticModelFlow } from "./domain/semanticModelFlow";
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
  let desktopBridge: DesktopBridge | null = null;
  let clipboardReader: ClipboardReader = createClipboardReader();
  let clipboardWriter: ClipboardWriter = createClipboardWriter();
  let state: HostState = createHostState();
  let draft: RequestSettings = { ...state.requestDraft };
  let settingsDraft: HostSettingsDraft = createDefaultSettingsDraft(state.requestDraft);
  let secretInput = "";
  let settingsSection: SettingsSection = "provider";
  let providerStatus: ProviderAvailability = "checking";
  let activeProviderId = "minimax";
  let providerStatusText = "";
  let clipboardReading = false;
  let startupClipboardRead = false;
  const toast = createToastController({ translate: (message) => tr(message) });
  const showToast = toast.show;
  let resultRatingBusy = false;
  let appVersion = __REFLEX_APP_VERSION__;
  let windowSizePreset: WindowSizePreset = "default";
  let commandPaletteOpen = false;
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
    language: () => ($persistedConfig?.language === "en-US" ? "en-US" : "zh-CN"),
    translate: (source, values) => tr(source, values),
    showToast
  });
  const batch = batchFlow.state;
  const batchFileNotice = batchFlow.fileNotice;

  const semanticModelFlow = createSemanticModelFlow({
    capabilityBridge: () => capabilityBridge,
    isEnabled: () => Boolean($persistedConfig?.enabled_plugins.includes("semantic-detector"))
  });
  const semanticModel = semanticModelFlow.state;

  const settingsFlow = createSettingsFlow({
    settingsApi: () => settingsApi,
    providerCatalogBridge: () => providerCatalogBridge,
    providerConnectionBridge: () => providerConnectionBridge,
    desktopBridge: () => desktopBridge,
    currentProviderModels: () => settingsDraft.provider_models
  });
  const persistedConfig = settingsFlow.persistedConfig;
  const providerOptions = settingsFlow.providerOptions;
  const secretStatus = settingsFlow.secretStatus;
  const secretBusy = settingsFlow.secretBusy;
  const secretNotice = settingsFlow.secretNotice;
  const providerStatusError = settingsFlow.providerStatusError;
  const providerCatalogNotice = settingsFlow.providerCatalogNotice;
  const providerConnectionBusy = settingsFlow.providerConnectionBusy;
  const providerConnectionNotice = settingsFlow.providerConnectionNotice;
  const settingsBusy = settingsFlow.settingsBusy;
  const settingsNotice = settingsFlow.settingsNotice;
  const desktopStatus = settingsFlow.desktopStatus;
  const cloudPrivacy = createCloudPrivacyFlow({
    feedbackBridge: () => feedbackBridge,
    showToast
  });
  const cloudConsent = cloudPrivacy.consent;
  const cloudUsageMetricsDraft = cloudPrivacy.usageMetricsDraft;
  const cloudImprovementDraft = cloudPrivacy.improvementDraft;
  const cloudQualityRelease = cloudPrivacy.qualityRelease;
  const cloudQuota = cloudPrivacy.quota;
  const cloudPrivacyBusy = cloudPrivacy.busy;
  const cloudPrivacyNotice = cloudPrivacy.notice;
  const cloudFeedbackAvailable = cloudPrivacy.feedbackAvailable;
  const cloudAvailability = cloudPrivacy.availability;
  const diagnosticFlow = createDiagnosticFlow({
    diagnosticBundleBridge: () => diagnosticBundleBridge
  });
  const diagnosticExportBusy = diagnosticFlow.busy;
  const diagnosticExportNotice = diagnosticFlow.notice;

  const templateFlow = createTemplateFlow({
    persistConfigPatch: (build) => settingsFlow.persistConfigPatch(build),
    hasPersistedConfig: () => Boolean($persistedConfig),
    updateHostState: (updater) => {
      state = updater(state);
    },
    closeManager: () => closeTemplateManager(),
    showToast
  });
  const templateDraft = templateFlow.draft;
  const selectedTemplateId = templateFlow.selectedId;
  const templateQuery = templateFlow.query;
  const templateCategory = templateFlow.category;
  const templateValues = templateFlow.values;
  const templateNotice = templateFlow.notice;
  const templateBusy = templateFlow.busy;
  const templateCategories = templateFlow.categories;
  const visibleTemplates = templateFlow.visible;

  const clipboardFlow = createClipboardFlow({
    clipboardWriter: () => clipboardWriter,
    clipboardPolicy: () => $persistedConfig?.clipboard_policy ?? null,
    clipboardReplaceConfirmed: () => $persistedConfig?.clipboard_replace_confirmed === true,
    hasPersistedConfig: () => Boolean($persistedConfig),
    persistReplaceConfirmation: async () => {
      try {
        await settingsFlow.persistConfigPatch((latest) => ({
          ...latest,
          clipboard_replace_confirmed: true
        }));
        settingsDraft = settingsDraftFromConfig($persistedConfig);
      } catch {
        clipboardFlow.notice.set("本次已替换，下次使用时仍会再次确认。");
      }
    },
    updateHostState: (updater) => {
      state = updater(state);
    },
    showToast
  });
  const clipboardNotice = clipboardFlow.notice;

  const feedbackFlow = createFeedbackFlow({
    feedbackBridge: () => feedbackBridge,
    persistConfigPatch: (build) => settingsFlow.persistConfigPatch(build),
    hasPersistedConfig: () => Boolean(settingsApi && $persistedConfig),
    settle: () => tick(),
    appVersion: () => appVersion,
    buildContext: () => feedbackContextFor(state),
    promptText: () => state.currentResult?.sourceText ?? state.inputText,
    resultText: () => state.currentResult?.output ?? null,
    updateConsent: (latest) => cloudConsent.set(latest),
    showToast
  });
  const feedbackOpen = feedbackFlow.open;
  const feedbackPromptOpen = feedbackFlow.promptOpen;
  const feedbackPromptBusy = feedbackFlow.promptBusy;
  const feedbackPromptNotice = feedbackFlow.promptNotice;
  const feedbackPromptState = feedbackFlow.promptState;
  const feedbackPromptEnabledDraft = feedbackFlow.promptEnabledDraft;
  const feedbackSentiment = feedbackFlow.sentiment;
  const feedbackScreenshot = feedbackFlow.screenshot;
  const feedbackCaptureNotice = feedbackFlow.captureNotice;
  const feedbackSubmitBusy = feedbackFlow.submitBusy;
  const feedbackSubmitNotice = feedbackFlow.submitNotice;

  const firstRunFlow = createFirstRunFlow({
    persistConfigPatch: (build) => settingsFlow.persistConfigPatch(build),
    hasPersistedConfig: () => Boolean(settingsApi && $persistedConfig),
    routeForProvider: (providerId) => activationRouteForProvider(providerId),
    currentProviderId: () => activeProviderId
  });
  const activationState = firstRunFlow.state;
  const activationOpen = firstRunFlow.open;
  const activationNotice = firstRunFlow.notice;

  const optimizationFlow = createOptimizationFlow({
    coreBridge: () => coreBridge,
    updateHostState: (updater) => {
      state = updater(state);
    },
    hostState: () => state,
    canGenerate: () => canGenerate,
    language: () => ($persistedConfig?.language === "en-US" ? "en-US" : "zh-CN"),
    onSuccessfulCompletion: async () => {
      await handleCompletionClipboard();
      await completeFirstRunActivation();
      await recordFeedbackPromptCompletion();
    }
  });
  const scenePromptOpen = optimizationFlow.scenePromptOpen;
  const scenePromptSelection = optimizationFlow.scenePromptSelection;

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
          desktopStatus.update((current) => ({
            ...current,
            message: "桌面入口暂不可用。"
          }));
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
      optimizationFlow.dispose();
      translationFlow.close();
      markdownPreviewFlow.close();
      batchFlow.close();
      semanticModelFlow.cancel();
    };
  });

  $: bridgeReady = coreBridgeState === "ready" || (
    coreBridgeState === "unavailable" &&
    hostApi !== null &&
    activeProviderId === "reflex-cloud"
  );
  $: bridgeUnavailable = coreBridgeState === "unavailable" && !bridgeReady;
  $: canGenerate = state.canGenerate && !optimizationFlow.isRunning() && !isGenerating(state.phase) && bridgeReady;
  $: translatorEnabled = $persistedConfig?.enabled_plugins.includes("translator") ?? true;
  $: markdownPreviewEnabled = $persistedConfig?.enabled_plugins.includes("markdown-preview") ?? true;
  $: batchRunnerEnabled = $persistedConfig?.enabled_plugins.includes("batch-runner") ?? true;
  $: semanticDetectorEnabled = settingsDraft.enabled_plugins.includes("semantic-detector");
  $: semanticDetectorActive = $persistedConfig?.enabled_plugins.includes("semantic-detector") ?? false;
  $: uiLanguage = settingsDraft.language === "en-US" || $persistedConfig?.language === "en-US"
    ? "en-US"
    : "zh-CN";
  $: tr = (source, values = {}) => translate(uiLanguage, source, values);
  $: setTranslator(tr);
  $: settingsProviderModels = providerModels(settingsDraft.default_provider, $providerOptions);
  $: selectableModels = workbenchModelOptions($persistedConfig, $providerOptions);
  $: activeProviderId = (state.requestDraft.provider ?? "minimax").trim().toLowerCase();
  $: providerStatus = resolveProviderAvailability(
    activeProviderId,
    $secretStatus,
    $persistedConfig !== null,
    $providerStatusError,
    $cloudAvailability
  );
  $: providerStatusText = providerAvailabilityLabel(providerStatus);
  $: activationRoutes = availableActivationRoutes($cloudAvailability);
  $: activationProviderReady = providerStatus === "ready";
  $: activeProviderLabel = tr(providerName(activeProviderId, $providerOptions));
  $: generationTrust = generationTrustSummary(
    {
      route: activationRouteForProvider(activeProviderId),
      providerLabel: activeProviderLabel,
      historyEnabled: $persistedConfig?.history_enabled ?? false,
      privacyMode: $persistedConfig?.privacy_mode ?? false,
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
      value: tr(providerName(state.currentResult?.provider ?? state.requestDraft.provider, $providerOptions))
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
    const policy = $persistedConfig?.clipboard_policy;
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
    feedbackPromptEnabledDraft.set($feedbackPromptState.enabled);
    settingsSection = "provider";
    secretInput = "";
    settingsNotice.set(null);
    secretNotice.set(null);
    void hydrateSettings(preferredProviderId);
    void settingsFlow.refreshCatalog();
    void hydrateCloudPrivacy();
  }

  function hydrateCloudPrivacy() {
    return cloudPrivacy.hydrate();
  }

  function saveCloudPrivacyDraft(): Promise<boolean> {
    return cloudPrivacy.saveDraft();
  }

  function confirmDeleteCloudData() {
    confirmation = {
      title: "删除全部云端数据？",
      description: "将删除当前安装身份、反馈附件和改进计划数据。此操作无法撤销。",
      confirmLabel: "删除云端数据",
      danger: true,
      run: () => cloudPrivacy.deleteAllData()
    };
  }

  async function saveSettings() {
    if ($settingsBusy) return;
    if (!settingsApi || !$persistedConfig) {
      settingsNotice.set("当前环境无法保存设置。");
      return;
    }
    settingsBusy.set(true);
    settingsNotice.set(null);
    try {
      const nextFeedbackPromptState = {
        ...feedbackPromptState,
        enabled: feedbackPromptEnabledDraft
      };
      const draftToSave = settingsDraft;
      const saved = await settingsFlow.persistConfigPatch((latest) => ({
        ...configFromSettingsDraft(latest, draftToSave),
        feedback_prompt: nextFeedbackPromptState
      }));
      feedbackFlow.hydratePromptState(normalizeFeedbackPromptState(saved.feedback_prompt));
      settingsDraft = settingsDraftFromConfig(saved);
      state = applySettingsDraft(applyPersistedConfig(state, saved), settingsDraft);
      draft = { ...state.requestDraft };
      await settingsFlow.refreshDesktopStatus();
      await settingsFlow.refreshSecretStatus(saved.provider);
      if (saved.enabled_plugins.includes("semantic-detector")) {
        await runSemanticModelOperation("status");
      } else {
        semanticModelFlow.reset();
      }
      const cloudSaved = await saveCloudPrivacyDraft();
      showToast(cloudSaved ? "✓ 设置已保存" : "本地设置已保存，云端授权未更新。", cloudSaved ? "success" : "error");
      if (providerReadyForActivation(saved.provider)) {
        await finishFirstRunFromSettings(saved.provider);
      }
    } catch (error) {
      settingsNotice.set(safeDesktopSettingsError(error));
    } finally {
      settingsBusy.set(false);
    }
  }

  async function exportDiagnosticBundle() {
    return diagnosticFlow.exportBundle();
  }

  async function cancelDiagnosticBundleExport() {
    return diagnosticFlow.cancelExport();
  }

  function cancelSettingsView() {
    state = cancelSettings(state);
    settingsDraft = $persistedConfig
      ? settingsDraftFromConfig($persistedConfig)
      : createDefaultSettingsDraft(state.requestDraft);
    secretInput = "";
    settingsNotice.set(null);
    secretNotice.set(null);
    feedbackPromptEnabledDraft.set($feedbackPromptState.enabled);
    void settingsFlow.refreshSecretStatus(state.requestDraft.provider ?? "minimax");
  }

  async function hydrateSettings(preferredProviderId: string | null = null) {
    const config = await settingsFlow.loadConfig();
    if (!config) return;
    firstRunFlow.hydrate(config);
    feedbackFlow.hydratePromptState(normalizeFeedbackPromptState(config.feedback_prompt));
    templateFlow.hydrate(readCustomTemplates(config.custom_templates));
    state = applyPersistedConfig(state, config);
    settingsDraft = settingsDraftFromConfig(config);
    settingsFlow.applyConfiguredModels(config.provider_models);
    const preferredProvider = preferredProviderId?.trim().toLowerCase();
    if (preferredProvider && $providerOptions.some((provider) => provider.id === preferredProvider)) {
      const models = providerModels(preferredProvider, $providerOptions);
      settingsDraft = {
        ...settingsDraft,
        default_provider: preferredProvider,
        default_model: providerDefaultModel(preferredProvider, $providerOptions) ?? models[0]?.id ?? null
      };
    }
    await settingsFlow.refreshSecretStatus(settingsDraft.default_provider ?? config.provider);
    settingsBusy.set(false);
  }

  function refreshProviderCatalog() {
    return settingsFlow.refreshCatalog();
  }

  function refreshDesktopStatus() {
    return settingsFlow.refreshDesktopStatus();
  }

  function refreshProviderSecretStatus(providerId: string) {
    return settingsFlow.refreshSecretStatus(providerId);
  }

  async function saveSecret() {
    const savedProvider = settingsDraft.default_provider ?? "minimax";
    const byokActivation = activationOpen && activationState.route === "byok";
    await settingsFlow.saveSecret(
      savedProvider,
      secretInput.trim(),
      byokActivation ? handleByokSecretSaved : undefined
    );
    secretInput = "";
  }

  async function handleByokSecretSaved(savedProvider: string) {
    const savedModel = settingsDraft.default_model ?? providerDefaultModel(savedProvider, $providerOptions);
    if (savedModel) state = selectRequestModel(state, savedProvider, savedModel);
    let defaultProviderSaved = true;
    if ($persistedConfig) {
      try {
        await settingsFlow.persistConfigPatch((latest) =>
          configFromSettingsDraft(latest, settingsDraft)
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

  function deleteSecret() {
    if (!settingsFlow.beginSecretDelete()) return;
    confirmation = {
      title: tr("删除已保存的 API Key？"),
      description: tr("删除后当前 Provider 将无法调用，之后仍可重新保存。"),
      confirmLabel: tr("删除密钥"),
      run: () => settingsFlow.performSecretDelete(settingsDraft.default_provider ?? "minimax")
    };
  }

  async function selectSettingsProvider(provider: string) {
    const models = providerModels(provider, $providerOptions);
    settingsDraft = {
      ...settingsDraft,
      default_provider: provider,
      default_model: providerDefaultModel(provider, $providerOptions) ?? models[0]?.id ?? null
    };
    secretInput = "";
    secretNotice.set(null);
    providerConnectionNotice.set(null);
    await settingsFlow.refreshSecretStatus(provider);
  }

  function updateProviderBaseUrl(value: string) {
    const providerId = settingsDraft.default_provider ?? "minimax";
    settingsDraft = {
      ...settingsDraft,
      provider_endpoints: { ...settingsDraft.provider_endpoints, [providerId]: value }
    };
    providerConnectionNotice.set(null);
  }

  async function discoverProviderModels() {
    const providerId = settingsDraft.default_provider ?? "minimax";
    const models = await settingsFlow.discoverModels(
      providerId,
      settingsDraft.provider_endpoints[providerId] ?? ""
    );
    if (!models) return;
    settingsDraft = {
      ...settingsDraft,
      default_model: models.includes(settingsDraft.default_model ?? "")
        ? settingsDraft.default_model
        : models[0],
      provider_models: { ...settingsDraft.provider_models, [providerId]: models }
    };
  }

  function testProviderConnection() {
    const providerId = settingsDraft.default_provider ?? "minimax";
    return settingsFlow.testConnection(
      providerId,
      settingsDraft.provider_endpoints[providerId] ?? "",
      settingsDraft.default_model
    );
  }

  async function recordFeedbackPromptCompletion() {
    if (!$cloudFeedbackAvailable || !state.currentResult?.output.trim()) return;
    const promptAvailable =
      !$feedbackOpen &&
      !$feedbackPromptOpen &&
      !$feedbackPromptBusy &&
      !confirmation &&
      !commandPaletteOpen &&
      !scenePromptOpen &&
      state.overlay === null &&
      $batch.phase === "closed" &&
      $translation.phase === "closed" &&
      $markdownPreview.phase === "closed" &&
      state.phase === "completed";
    await feedbackFlow.recordCompletion(promptAvailable);
  }

  function runOptimization() {
    return optimizationFlow.request();
  }

  function cancelScenePrompt() {
    optimizationFlow.cancelScene();
  }

  function confirmScenePrompt() {
    return optimizationFlow.confirmScene();
  }

  function cancelRun() {
    optimizationFlow.cancel();
  }

  async function copyResult() {
    await clipboardFlow.copyResult(state.output);
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
    templateFlow.newDraft();
    state = { ...state, overlay: "template_manager" };
  }

  function closeTemplateManager() {
    state = { ...state, overlay: null };
    templateNotice.set(null);
  }

  function selectTemplate(template: PromptTemplate) {
    templateFlow.select(template);
  }

  function saveTemplate() {
    return templateFlow.save();
  }

  function deleteTemplate() {
    if (!templateFlow.beginDelete()) return;
    confirmation = {
      title: tr("删除当前模板？"),
      description: tr("删除后无法恢复，但不会影响已经生成的内容。"),
      confirmLabel: tr("删除模板"),
      run: () => templateFlow.performDelete()
    };
  }

  function applyTemplate() {
    templateFlow.apply();
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
    return clipboardFlow.requestManualReplace(state.output);
  }

  async function confirmReplaceClipboard() {
    await clipboardFlow.confirmReplace(state.output);
  }

  async function copyDiagnosticId() {
    if (!state.diagnosticId) return;
    await writeClipboardValue(state.diagnosticId, "✓ 诊断 ID 已复制");
  }

  function beginFeedback(sentiment: FeedbackSentiment) {
    if (!state.currentResult?.output) return;
    feedbackPromptOpen.set(false);
    confirmation = {
      title: sentiment === "negative" ? "反馈这次不满意的结果？" : "反馈这次满意的结果？",
      description: "继续后只截取 Reflex 当前窗口，并在发送前显示预览。输入、结果和截图都可以单独移除。",
      confirmLabel: "继续反馈",
      danger: false,
      run: () => openFeedback(sentiment, "manual", true)
    };
  }

  function openFeedback(
    sentiment: FeedbackSentiment,
    source: "manual" | "prompt",
    captureScreenshot: boolean
  ) {
    return feedbackFlow.startDialog(sentiment, source, captureScreenshot);
  }

  function answerFeedbackPrompt(sentiment: FeedbackSentiment) {
    return feedbackFlow.answerPrompt(sentiment);
  }

  function postponeFeedbackPrompt() {
    feedbackFlow.postponePrompt();
  }

  function turnOffFeedbackPrompt() {
    feedbackFlow.disablePrompt();
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
    feedbackFlow.closeDialog();
  }

  function removeFeedbackScreenshot() {
    feedbackFlow.removeScreenshot();
  }

  function submitFeedback(form: FeedbackFormValue) {
    return feedbackFlow.submit(form);
  }

  async function handleCompletionClipboard() {
    await clipboardFlow.afterCompletion(state.output);
  }

  async function writeClipboardValue(text: string, successMessage: string): Promise<boolean> {
    return clipboardFlow.writeValue(text, successMessage);
  }

  function retryRun() {
    state = retryAfterError(state);
    void runOptimization();
  }

  function openSettingsView() {
    beginSettings();
  }

  async function chooseActivationRoute(route: ActivationRoute) {
    const persisted = await firstRunFlow.chooseRoute(
      route,
      availableActivationRoutes($cloudAvailability)
    );
    if (!persisted) return;
    activationNotice.set("");
    if (route === "cloud") {
      const model = providerDefaultModel("reflex-cloud", $providerOptions);
      if (model) switchWorkbenchModel("reflex-cloud", model);
      return;
    }
    openByokSettings();
  }

  function openByokSettings() {
    const providerId = preferredByokProvider(
      $persistedConfig?.provider ?? activeProviderId,
      $providerOptions.map((provider) => provider.id)
    );
    beginSettings(providerId);
  }

  function continueFirstRun() {
    firstRunFlow.postpone();
  }

  function postponeFirstRun() {
    firstRunFlow.postpone();
  }

  async function completeFirstRunActivation() {
    await firstRunFlow.complete();
  }

  function providerReadyForActivation(providerId: string | null): boolean {
    if (providerId === "reflex-cloud") return $cloudAvailability === "ready";
    return (
      providerId !== null &&
      $secretStatus.providerId === providerId &&
      $secretStatus.configured &&
      !$providerStatusError
    );
  }

  async function finishFirstRunFromSettings(providerId: string | null) {
    if (!$activationOpen || !providerReadyForActivation(providerId)) return;
    await completeFirstRunActivation();
    if ($activationState.completed) cancelSettingsView();
  }

  function managePluginSettings() {
    beginSettings();
    settingsSection = "plugins";
    void refreshSemanticModelStatus();
  }

  function setPluginEnabled(pluginId: SettingsPluginId, enabled: boolean) {
    settingsDraft = updatePluginSettingsDraft(settingsDraft, pluginId, enabled);
    if (pluginId === "semantic-detector" && !enabled) {
      semanticModelFlow.reset();
    }
  }

  function selectSettingsSection(section: SettingsSection) {
    settingsSection = section;
    if (section === "plugins") void refreshSemanticModelStatus();
  }

  async function refreshSemanticModelStatus() {
    if (!$persistedConfig?.enabled_plugins.includes("semantic-detector")) return;
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
    semanticModelFlow.cancel();
  }

  function runSemanticModelOperation(operation: "status" | "download" | "delete") {
    return semanticModelFlow.run(operation);
  }

  function semanticModelStatusText(): string {
    if (!semanticDetectorActive && semanticDetectorEnabled) return "保存设置后即可管理本地模型。";
    if ($semanticModel.phase === "loading") return "正在检查本地模型…";
    if ($semanticModel.phase === "downloading") return tr("正在下载 {percent}%", { percent: $semanticModel.percent });
    if ($semanticModel.phase === "deleting") return "正在删除本地模型…";
    if ($semanticModel.phase === "ready") return tr("模型已就绪 · {size}", { size: semanticModelSizeLabel($semanticModel.sizeBytes) });
    if ($semanticModel.phase === "missing") {
      return $semanticModel.runtimeReady
        ? "尚未下载本地语义模型。"
        : "本地语义运行组件尚未安装。";
    }
    if ($semanticModel.phase === "error") {
      if ($semanticModel.errorCode === "model_runtime_missing") return "缺少本地模型下载组件。";
      if ($semanticModel.errorCode === "model_download_failed") return "模型下载失败，请检查网络后重试。";
      if ($semanticModel.errorCode === "model_download_incomplete") return "模型文件不完整，请重新下载。";
      if ($semanticModel.errorCode === "model_delete_failed") return "本地模型删除失败。";
      return "本地模型状态暂时不可用。";
    }
    return "检查本地模型后可启用更准确的场景识别。";
  }

  function closeOverlay() {
    if (state.overlay === "settings") {
      cancelSettingsView();
      return;
    }
    clipboardNotice.set(null);
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
    inert={state.overlay === "settings" || $activationOpen}
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
        selectedScene={$scenePromptSelection}

        onSceneChange={(sceneId) => scenePromptSelection.set(sceneId)}
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
        query={$templateQuery}
        category={$templateCategory}
        categories={$templateCategories}
        templates={$visibleTemplates}
        selectedId={$selectedTemplateId}
        draft={$templateDraft}
        values={$templateValues}
        notice={$templateNotice}
        busy={$templateBusy}

        onQueryChange={(value) => templateQuery.set(value)}
        onCategoryChange={(value) => templateCategory.set(value)}
        onNew={() => templateFlow.newDraft()}
        onSelect={selectTemplate}
        onDraftChange={(value) => templateDraft.set(value)}
        onValuesChange={(value) => templateValues.set(value)}
        onDelete={deleteTemplate}
        onSave={saveTemplate}
        onApply={applyTemplate}
        onClose={closeTemplateManager}
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
      <ClipboardConfirmDialog notice={$clipboardNotice} onCancel={closeOverlay} onConfirm={confirmReplaceClipboard} />
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
        busy={$settingsBusy}
        secretBusy={$secretBusy}
        {secretInput}
        secretStatus={$secretStatus}
        secretNotice={$secretNotice}
        providerConnectionBusy={$providerConnectionBusy}
        providerConnectionNotice={$providerConnectionNotice}
        notice={$settingsNotice}
        providerCatalogNotice={$providerCatalogNotice}
        providers={$providerOptions}
        models={settingsProviderModels}
        {modes}
        {styles}
        desktopStatus={$desktopStatus}
        semanticModel={$semanticModel}
        semanticEnabled={semanticDetectorEnabled}
        semanticActive={semanticDetectorActive}
        semanticStatusText={semanticModelStatusText()}
        diagnosticBusy={$diagnosticExportBusy}
        diagnosticNotice={$diagnosticExportNotice}
        cloudUsageMetricsEnabled={$cloudUsageMetricsDraft}
        cloudImprovementEnabled={$cloudImprovementDraft}
        feedbackPromptEnabled={feedbackPromptEnabledDraft}
        cloudQualityRelease={$cloudQualityRelease}
        cloudQuota={$cloudQuota}
        cloudPrivacyBusy={$cloudPrivacyBusy}
        cloudPrivacyNotice={$cloudPrivacyNotice}

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
          settingsFlow.applyConfiguredModels(settingsDraft.provider_models);
        }}
        onPluginChange={setPluginEnabled}
        onSemanticRefresh={refreshSemanticModelStatus}
        onSemanticCancel={cancelSemanticModelDownload}
        onSemanticDelete={deleteSemanticModel}
        onSemanticDownload={downloadSemanticModel}
        onDiagnosticExport={exportDiagnosticBundle}
        onDiagnosticCancel={cancelDiagnosticBundleExport}
        onCloudUsageMetricsChange={(enabled) => cloudUsageMetricsDraft.set(enabled)}
        onCloudImprovementChange={(enabled) => cloudImprovementDraft.set(enabled)}
        onFeedbackPromptEnabledChange={(enabled) => feedbackPromptEnabledDraft.set(enabled)}
        onCloudRefresh={hydrateCloudPrivacy}
        onCloudDeleteData={confirmDeleteCloudData}
      />
    {/if}

  {#if $activationOpen && state.overlay !== "settings"}
    <FirstRunDialog
      routes={activationRoutes}
      selectedRoute={$activationState.route}
      providerReady={activationProviderReady}
      providerLabel={activeProviderLabel}
      notice={$activationNotice}

      onChoose={chooseActivationRoute}
      onOpenSettings={openByokSettings}
      onContinue={continueFirstRun}
      onLater={postponeFirstRun}
    />
  {/if}
</main>
