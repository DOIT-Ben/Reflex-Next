<script lang="ts">
  import { onMount, tick } from "svelte";
  import FeedbackDialog from "./components/feedback/FeedbackDialog.svelte";
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
  import type {
    ConfigSummaryItem,
    ResultMetaItem,
    WorkbenchPhase
  } from "./components/workbench/types";
  import { CapabilityBridge } from "./domain/capabilityBridge";
  import { createDiagnosticBundleBridge, type DiagnosticBundleBridge } from "./domain/diagnosticBundleBridge";
  import {
    createFeedbackBridge,
    type CloudConsent,
    type CloudQuota,
    type FeedbackBridge,
    type FeedbackFormValue,
    type FeedbackScreenshot,
    type FeedbackSentiment
  } from "./domain/feedbackBridge";
  import { createDefaultCoreBridge, DemoCoreBridge } from "./domain/coreBridge";
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
    applyTranslationAsCurrentResult,
    cancelGeneration,
    cancelAdjust,
    cancelSettings,
    configFromSettingsDraft,
    createDefaultSettingsDraft,
    createHostState,
    createRequestDraft,
    openAdjust,
    openSettings,
    resolveHostShortcut,
    retryAfterError,
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
  import {
    createProviderCatalogBridge,
    PROVIDER_CATALOG_UNAVAILABLE_MESSAGE,
    type ProviderCatalogBridge
  } from "./domain/providerCatalogBridge";
  import {
    normalizeViewScale,
    stepViewScale,
    viewScaleLabel,
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
    appendTranslationChunk,
    buildTranslationInput,
    cancelTranslation,
    closeTranslation,
    completeTranslation,
    createTranslationState,
    failTranslation,
    openTranslation,
    selectTranslationTarget,
    startTranslation,
    translationErrorMessage,
    type TranslationLanguage,
    type TranslationTarget
  } from "./domain/translationState";
  import {
    closeMarkdownPreview,
    completeMarkdownPreview,
    createMarkdownPreviewState,
    failMarkdownPreview,
    openMarkdownPreview,
    selectMarkdownPreviewMode
  } from "./domain/markdownPreviewState";
  import {
    batchCanExport,
    beginBatchParse,
    beginBatchRun,
    cancelBatch,
    closeBatch,
    completeBatchItem,
    completeBatchParse,
    createBatchState,
    failBatchItem,
    failBatchParse,
    finalizeBatchRun,
    openBatch,
    runBatchWorkerPool,
    setBatchFormat,
    setBatchSourceText,
    startBatchItem,
    type BatchFormat
  } from "./domain/batchState";
  import {
    batchTemplateContent,
    readBatchImportFile,
    type BatchImportFailure
  } from "./domain/batchFileImport";
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
    resolveProviderAvailability,
    type ProviderOption,
    type ProviderAvailability
  } from "./domain/providerCatalog";
  import {
    applySemanticModelEvent,
    beginSemanticModelOperation,
    createSemanticModelState,
    failSemanticModelOperation,
    semanticModelSizeLabel
  } from "./domain/semanticModelState";
  import { t, translate } from "./domain/i18n";
  import { resultMarkdownContent, resultMarkdownFilename } from "./domain/resultExport";
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
  let coreBridge: CoreBridge = new DemoCoreBridge();
  let capabilityBridge: CapabilityBridge | null = null;
  let diagnosticBundleBridge: DiagnosticBundleBridge | null = null;
  let feedbackBridge: FeedbackBridge | null = null;
  let providerCatalogBridge: ProviderCatalogBridge | null = null;
  let hostApi: TauriHostApi | null = null;
  let settingsApi: SettingsApi | null = null;
  let desktopBridge: DesktopBridge | null = null;
  let clipboardReader: ClipboardReader = createClipboardReader();
  let clipboardWriter: ClipboardWriter = createClipboardWriter();
  let state: HostState = createHostState();
  let draft: RequestSettings = { ...state.requestDraft };
  let settingsDraft: HostSettingsDraft = createDefaultSettingsDraft(state.requestDraft);
  let activeRun: AbortController | null = null;
  let translationRun: AbortController | null = null;
  let translation = createTranslationState();
  let translationSourceResult: CurrentResult | null = null;
  let markdownPreview = createMarkdownPreviewState();
  let markdownPreviewRun: AbortController | null = null;
  let batch = createBatchState();
  let batchRun: AbortController | null = null;
  let semanticModel = createSemanticModelState();
  let semanticModelRun: AbortController | null = null;
  let batchFileNotice: string | null = null;
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
  let secretInput = "";
  let secretStatus: SecretStatus = {
    providerId: "minimax",
    configured: false,
    maskedTail: null
  };
  let settingsSection: SettingsSection = "provider";
  let settingsBusy = false;
  let secretBusy = false;
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
  let toastVisible = false;
  let toastText = "✓ 已复制到剪贴板";
  let toastTone: "success" | "error" = "success";
  let toastTimeout: number | null = null;
  let resultRatingBusy = false;
  let feedbackOpen = false;
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
  let cloudImprovementDraft = false;
  let cloudQuota: CloudQuota | null = null;
  let cloudPrivacyBusy = false;
  let cloudPrivacyNotice: string | null = null;
  let appVersion = __REFLEX_APP_VERSION__;
  let viewScale = 1;
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
  let workbenchStatusMessage = "准备就绪";
  let statusTone: StatusTone = "idle";
  let navItems: NavRailItem[] = [];
  let configSummaryItems: ConfigSummaryItem[] = [];
  let resultMetaItems: ResultMetaItem[] = [];
  let tr: (source: string, values?: Record<string, string | number>) => string = (source) => source;

  onMount(() => {
    let disposed = false;
    let stopListening: (() => void) | null = null;
    let stopHistoryReuseListening: (() => void) | null = null;

    viewScale = readViewScale();

    void createTauriHostApi().then(async (host) => {
      if (!host || disposed) return;

      hostApi = host;
      capabilityBridge = new CapabilityBridge(host);
      providerCatalogBridge = createProviderCatalogBridge(host);
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

      void createDefaultCoreBridge(host).then((bridge) => {
        if (!disposed) coreBridge = bridge;
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
      translationRun?.abort();
      markdownPreviewRun?.abort();
      batchRun?.abort();
      semanticModelRun?.abort();
    };
  });

  $: canGenerate = state.canGenerate && !isGenerating(state.phase);
  $: translatorEnabled = persistedConfig?.enabled_plugins.includes("translator") ?? true;
  $: markdownPreviewEnabled = persistedConfig?.enabled_plugins.includes("markdown-preview") ?? true;
  $: batchRunnerEnabled = persistedConfig?.enabled_plugins.includes("batch-runner") ?? true;
  $: semanticDetectorEnabled = settingsDraft.enabled_plugins.includes("semantic-detector");
  $: semanticDetectorActive = persistedConfig?.enabled_plugins.includes("semantic-detector") ?? false;
  $: uiLanguage = settingsDraft.language === "en-US" || persistedConfig?.language === "en-US"
    ? "en-US"
    : "zh-CN";
  $: tr = (source, values = {}) => translate(uiLanguage, source, values);
  $: templateCategories = [...new Set(customTemplates.map((template) => template.category))].sort((left, right) => left.localeCompare(right, "zh-CN"));
  $: visibleTemplates = filterTemplates(customTemplates, templateQuery, templateCategory);
  $: settingsProviderModels = providerModels(settingsDraft.default_provider, providerOptions);
  $: draftProviderModels = providerModels(draft.provider, providerOptions);
  $: activeProviderId = (state.requestDraft.provider ?? "minimax").trim().toLowerCase();
  $: providerStatus = resolveProviderAvailability(
    activeProviderId,
    secretStatus,
    persistedConfig !== null,
    providerStatusError
  );
  $: providerStatusText = providerAvailabilityLabel(providerStatus);
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
  $: workbenchStatusMessage = state.phase === "analyzing_scene"
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
  $: statusTone = isGenerating(state.phase)
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
        : batch.phase !== "closed"
          ? "batch"
          : translation.phase !== "closed"
            ? "translation"
            : markdownPreview.phase !== "closed"
              ? "markdown"
              : "workbench";
  $: navItems = [
    { id: "workbench", label: tr("工作台"), symbol: "" },
    { id: "templates", label: tr("模板管理"), symbol: "" },
    { id: "batch", label: tr("批量处理"), symbol: "", disabled: !batchRunnerEnabled },
    {
      id: "translation",
      label: tr("翻译"),
      symbol: "",
      disabled: !translatorEnabled || !state.currentResult?.output
    },
    {
      id: "markdown",
      label: tr("Markdown 预览"),
      symbol: "",
      disabled: !markdownPreviewEnabled || !state.currentResult?.output
    },
    { id: "plugins", label: tr("插件"), symbol: "" },
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
    {
      id: "model",
      label: tr("模型"),
      value: state.requestDraft.model ?? tr(providerName(state.requestDraft.provider, providerOptions))
    }
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
    if (batch.phase !== "closed") closeBatchView();
    if (translation.phase !== "closed") closeTranslationView();
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
  }

  function handleNavigation(id: string) {
    commandPaletteOpen = false;
    if (id === "workbench") returnToWorkbench();
    else if (id === "templates") openTemplateManager();
    else if (id === "batch" && batchRunnerEnabled) openBatchView();
    else if (id === "translation" && translatorEnabled && state.currentResult?.output) openTranslationView();
    else if (id === "markdown" && markdownPreviewEnabled && state.currentResult?.output) openMarkdownPreviewView();
    else if (id === "plugins") state = applyHostAction(state, "plugins");
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
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if (translation.phase !== "closed") closeTranslationView();
    if (action === "settings") {
      beginSettings();
      return;
    }
    state = applyHostAction(state, action);
  }

  function beginAdjust() {
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if (translation.phase !== "closed") closeTranslationView();
    state = openAdjust(state);
    draft = { ...(state.adjustDraft ?? state.requestDraft) };
  }

  function applyAdjust() {
    state = applyAdjustDraft(state, draft);
  }

  function cancelAdjustView() {
    state = cancelAdjust(state);
    draft = { ...state.requestDraft };
  }

  function beginSettings() {
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if (translation.phase !== "closed") closeTranslationView();
    state = openSettings(state);
    settingsDraft = { ...(state.settingsDraft ?? settingsDraft) };
    settingsSection = "provider";
    secretInput = "";
    settingsNotice = null;
    secretNotice = null;
    void hydrateSettings();
    void refreshProviderCatalog();
    void hydrateCloudPrivacy();
  }

  async function hydrateCloudPrivacy() {
    const bridge = feedbackBridge;
    if (!bridge || cloudPrivacyBusy) return;
    cloudPrivacyBusy = true;
    cloudPrivacyNotice = null;
    try {
      const [consent, quota] = await Promise.all([bridge.getConsent(), bridge.getQuota()]);
      cloudConsent = consent;
      cloudImprovementDraft = consent.improvement_data;
      cloudQuota = quota;
    } catch {
      cloudPrivacyNotice = "云端隐私设置暂不可用。";
    } finally {
      cloudPrivacyBusy = false;
    }
  }

  async function saveCloudPrivacyDraft(): Promise<boolean> {
    if (cloudImprovementDraft === cloudConsent.improvement_data) return true;
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
        improvement_data: cloudImprovementDraft,
        policy_version: cloudConsent.policy_version
      });
      cloudImprovementDraft = cloudConsent.improvement_data;
      cloudPrivacyNotice = cloudConsent.improvement_data
        ? "改进计划已开启。"
        : "改进计划已关闭。";
      return true;
    } catch {
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

  async function saveSettings() {
    if (settingsBusy) return;
    if (!settingsApi || !persistedConfig) {
      settingsNotice = "当前环境无法保存设置。";
      return;
    }
    settingsBusy = true;
    settingsNotice = null;
    try {
      const saved = await settingsApi.saveConfig(
        configFromSettingsDraft(persistedConfig, settingsDraft)
      );
      persistedConfig = saved;
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
    void refreshProviderSecretStatus(state.requestDraft.provider ?? "minimax");
  }

  async function hydrateSettings() {
    if (!settingsApi) return;
    settingsBusy = true;
    providerStatusError = false;
    settingsNotice = null;
    secretNotice = null;
    let config: AppConfig;
    try {
      config = await settingsApi.loadConfig();
      persistedConfig = config;
      customTemplates = readCustomTemplates(config.custom_templates);
      state = applyPersistedConfig(state, config);
      settingsDraft = settingsDraftFromConfig(config);
    } catch {
      providerStatusError = true;
      settingsNotice = "设置加载失败，请重试。";
      settingsBusy = false;
      return;
    }
    await refreshProviderSecretStatus(config.provider);
    settingsBusy = false;
  }

  async function refreshProviderCatalog() {
    const bridge = providerCatalogBridge;
    if (!bridge) return;
    try {
      const descriptors = await bridge.listProviders();
      providerOptions = providerOptionsFromRuntime(descriptors);
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
    await refreshProviderSecretStatus(provider);
  }

  function showToast(message: string, tone?: "success" | "error") {
    if (toastTimeout !== null) window.clearTimeout(toastTimeout);
    toastText = tr(message);
    toastTone = tone ?? (/失败|不可用|未保存|错误/.test(message) ? "error" : "success");
    toastVisible = true;
    toastTimeout = window.setTimeout(() => {
      toastVisible = false;
      toastTimeout = null;
    }, 1400);
  }

  async function runOptimization() {
    if (!canGenerate) return;
    const requestId = `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = new AbortController();
    activeRun = controller;
    state = startGeneration(state, requestId);

    for await (const event of coreBridge.optimize(createRequestDraft(state, persistedConfig?.language ?? "zh-CN"), {
      signal: controller.signal
    })) {
      if (controller.signal.aborted) break;
      state = applyCoreEnvelope(state, {
        version: 1,
        request_id: requestId,
        event
      });
      if (event.type === "done" && state.phase === "completed") {
        await handleCompletionClipboard();
      }
    }

    if (activeRun === controller) {
      activeRun = null;
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
    const content = resultMarkdownContent(state.output);
    const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = resultMarkdownFilename();
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
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
    const source = state.currentResult;
    if (!source?.output.trim() || !translatorEnabled) return;
    translationSourceResult = { ...source };
    translation = openTranslation(translation, source.output);
    if (translation.phase !== "closed") {
      void runTranslation();
    }
  }

  async function runTranslation() {
    if (translation.phase === "closed") return;
    translationRun?.abort();
    const started = startTranslation(translation);
    translation = started.state;
    const request = started.request;
    const controller = new AbortController();
    translationRun = controller;
    const input = buildTranslationInput(
      translation,
      translationSourceResult ?? {},
      { provider: state.requestDraft.provider, model: state.requestDraft.model }
    );
    const bridge = capabilityBridge;
    if (!bridge || !input) {
      if (translationRun === controller) {
        translation = failTranslation(
          translation,
          request,
          "翻译暂时不可用，请重试。"
        );
        translationRun = null;
      }
      return;
    }

    try {
      for await (const event of bridge.invoke("translator", "translate", input, {
        signal: controller.signal,
        timeoutMs: 60_000
      })) {
        if (controller.signal.aborted || translationRun !== controller) return;
        if (event.status === "chunk") {
          translation = appendTranslationChunk(translation, request, event.data.text);
        } else if (event.status === "result") {
          translation = completeTranslation(translation, request, event.data);
        } else if (event.status === "cancelled") {
          translation = cancelTranslation(translation, request);
        } else if (event.status === "error") {
          translation = failTranslation(
            translation,
            request,
            translationErrorMessage(event.code)
          );
        }
      }
    } catch {
      if (translationRun === controller) {
        translation = controller.signal.aborted
          ? cancelTranslation(translation, request)
          : failTranslation(translation, request, "翻译暂时不可用，请重试。");
      }
    } finally {
      if (translationRun === controller) translationRun = null;
    }
  }

  function chooseTranslationTarget(target: TranslationTarget) {
    const next = selectTranslationTarget(translation, target);
    if (next === translation) return;
    translation = next;
    void runTranslation();
  }

  function cancelTranslationRun() {
    const request = translation.request;
    translationRun?.abort();
    translationRun = null;
    translation = cancelTranslation(translation, request);
  }

  function closeTranslationView(restoreFocus = false) {
    translationRun?.abort();
    translationRun = null;
    translation = closeTranslation(translation);
    translationSourceResult = null;
  }

  async function copyTranslation() {
    if (!translation.translatedText) return;
    await writeClipboardValue(translation.translatedText, "✓ 译文已复制");
  }

  function useTranslationAsCurrentResult() {
    if (!translation.translatedText || !translationSourceResult) return;
    const next = applyTranslationAsCurrentResult(
      state,
      translation.translatedText,
      translation.request,
      translationSourceResult
    );
    if (next === state) return;
    state = next;
    closeTranslationView();
    showToast("已设为当前结果");
  }

  function openMarkdownPreviewView() {
    const source = state.currentResult?.output;
    if (!source?.trim() || !markdownPreviewEnabled) return;
    markdownPreview = openMarkdownPreview(markdownPreview, source);
    if (markdownPreview.phase !== "closed") {
      void runMarkdownPreview();
    }
  }

  async function runMarkdownPreview() {
    if (markdownPreview.phase === "closed") return;
    markdownPreviewRun?.abort();
    const request = markdownPreview.request;
    const controller = new AbortController();
    markdownPreviewRun = controller;
    const bridge = capabilityBridge;
    if (!bridge) {
      markdownPreview = failMarkdownPreview(markdownPreview, request);
      markdownPreviewRun = null;
      return;
    }
    try {
      for await (const event of bridge.invoke(
        "markdown-preview",
        "preview",
        { text: markdownPreview.sourceText },
        { signal: controller.signal, timeoutMs: 20_000 }
      )) {
        if (controller.signal.aborted || markdownPreviewRun !== controller) return;
        if (event.status === "result") {
          markdownPreview = completeMarkdownPreview(markdownPreview, request, event.data);
        } else if (event.status === "error" || event.status === "cancelled") {
          markdownPreview = failMarkdownPreview(markdownPreview, request);
        }
      }
    } catch {
      if (markdownPreviewRun === controller && !controller.signal.aborted) {
        markdownPreview = failMarkdownPreview(markdownPreview, request);
      }
    } finally {
      if (markdownPreviewRun === controller) markdownPreviewRun = null;
    }
  }

  function closeMarkdownPreviewView(restoreFocus = false) {
    markdownPreviewRun?.abort();
    markdownPreviewRun = null;
    markdownPreview = closeMarkdownPreview(markdownPreview);
  }

  function openBatchView() {
    if (!batchRunnerEnabled) return;
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if (translation.phase !== "closed") closeTranslationView();
    batch = openBatch(batch);
    batchFileNotice = null;
  }

  function closeBatchView(restoreFocus = false) {
    batchRun?.abort();
    batchRun = null;
    batch = closeBatch(batch);
    batchFileNotice = null;
  }

  function openTemplateManager() {
    if (batch.phase !== "closed") closeBatchView();
    selectedTemplateId = null;
    templateDraft = createTemplateDraft();
    templateValues = {};
    templateNotice = null;
    state = { ...state, overlay: "template_manager" };
  }

  function closeTemplateManager(restoreFocus = false) {
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
      const saved = await settingsApi.saveConfig({ ...persistedConfig, custom_templates: next });
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
      const saved = await settingsApi.saveConfig({ ...persistedConfig, custom_templates: next });
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

  async function parseBatchSource() {
    const started = beginBatchParse(batch);
    if (!started) return;
    const bridge = capabilityBridge;
    batch = started.state;
    if (!bridge) {
      batch = failBatchParse(batch, started.request, "批处理暂时不可用，请重试。");
      return;
    }
    try {
      for await (const event of bridge.invoke(
        "batch-runner",
        "parse",
        { format: batch.format, content: batch.sourceText },
        { timeoutMs: 20_000 }
      )) {
        if (batch.request !== started.request) return;
        if (event.status === "result") {
          batch = completeBatchParse(batch, started.request, event.data);
        } else if (event.status === "error" || event.status === "cancelled") {
          batch = failBatchParse(batch, started.request, "导入内容格式不正确，请检查后重试。");
        }
      }
    } catch {
      batch = failBatchParse(batch, started.request, "批处理暂时不可用，请重试。");
    }
  }

  async function importBatchFile(file: File) {
    if (!file || batch.phase === "parsing" || batch.phase === "running") return;

    const imported = await readBatchImportFile(file);
    if (!imported.ok) {
      batchFileNotice = batchImportFailureMessage(imported.reason);
      return;
    }

    batch = setBatchFormat(batch, imported.format);
    batch = setBatchSourceText(batch, imported.content);
    batchFileNotice = null;
    await parseBatchSource();
    if (batch.phase === "ready") {
      showToast(tr("已从 {name} 导入 {count} 条提示词", { name: file.name, count: batch.items.length }));
    }
  }

  function downloadBatchTemplate() {
    const content = batchTemplateContent(batch.format);
    const type = batch.format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8";
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `reflex-batch-template.${batch.format}`;
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function batchImportFailureMessage(reason: BatchImportFailure): string {
    const messages: Record<BatchImportFailure, string> = {
      unsupported_file: "请选择 CSV 或 TXT 文件。",
      file_too_large: "文件超过 200 万字符限制。",
      empty_file: "文件中没有可导入的内容。",
      read_failed: "无法读取该文件，请重试。"
    };
    return messages[reason];
  }

  async function runBatch() {
    const started = beginBatchRun(batch);
    if (!started) return;
    const controller = new AbortController();
    batchRun = controller;
    batch = started.state;
    const run = started.request;
    const items = batch.items;
    const language = persistedConfig?.language === "en-US" ? "en-US" : "zh-CN";

    await runBatchWorkerPool(items, batch.concurrency, controller.signal, async (item) => {
      if (controller.signal.aborted || batch.request !== run) return;
      batch = startBatchItem(batch, run, item.id);
      let output = "";
      try {
        const request = {
          text: item.prompt,
          mode: state.requestDraft.mode,
          style: batch.style,
          scene: batch.scene,
          scene_policy: batch.scene ? "manual" as const : "auto" as const,
          provider: state.requestDraft.provider,
          model: state.requestDraft.model,
          stream: true,
          metadata: { host: "tauri" as const, surface: "quick-panel" as const, language }
        };
        for await (const event of coreBridge.optimize(request, { signal: controller.signal })) {
          if (controller.signal.aborted || batch.request !== run) return;
          if (event.type === "chunk") output += batchEventText(event.data);
          if (event.type === "done") {
            const completed = batchEventText(event.data);
            if (completed) output = completed;
          }
          if (event.type === "error") {
            batch = failBatchItem(batch, run, item.id, "此条处理失败，请稍后重试。");
            return;
          }
        }
        if (!controller.signal.aborted && batch.request === run) {
          batch = completeBatchItem(batch, run, item.id, output);
        }
      } catch {
        if (!controller.signal.aborted && batch.request === run) {
          batch = failBatchItem(batch, run, item.id, "此条处理失败，请稍后重试。");
        }
      }
    });

    if (batchRun === controller) batchRun = null;
    if (!controller.signal.aborted) batch = finalizeBatchRun(batch, run);
  }

  function cancelBatchRun() {
    batchRun?.abort();
    batchRun = null;
    batch = cancelBatch(batch);
  }

  async function exportBatch() {
    if (!batchCanExport(batch)) return;
    const bridge = capabilityBridge;
    if (!bridge) {
      showToast("导出暂时不可用，请重试。");
      return;
    }
    let content = "";
    try {
      for await (const event of bridge.invoke(
        "batch-runner",
        "export",
        {
          format: batch.format,
          items: batch.items.map(({ id, prompt, result, status }) => ({ id, prompt, result, status }))
        },
        { timeoutMs: 20_000 }
      )) {
        if (event.status === "result" && typeof event.data.content === "string") content = event.data.content;
        if (event.status === "error" || event.status === "cancelled") break;
      }
    } catch {
      content = "";
    }
    if (!content) {
      showToast("导出暂时不可用，请重试。");
      return;
    }
    downloadBatchContent(content, batch.format);
    showToast("批处理结果已导出");
  }

  function batchEventText(data: Record<string, unknown>): string {
    for (const key of ["text", "output", "result"]) {
      if (typeof data[key] === "string") return data[key].replace(/\u0000/g, "").replace(/\r\n?/g, "\n");
    }
    return "";
  }

  function downloadBatchContent(content: string, format: BatchFormat) {
    const type = format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8";
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `reflex-batch-results.${format}`;
    anchor.style.display = "none";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
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
    confirmation = {
      title: sentiment === "negative" ? "反馈这次不满意的结果？" : "反馈这次满意的结果？",
      description: "继续后只截取 Reflex 当前窗口，并在发送前显示预览。输入、结果和截图都可以单独移除。",
      confirmLabel: "继续反馈",
      danger: false,
      run: () => openFeedback(sentiment)
    };
  }

  async function openFeedback(sentiment: FeedbackSentiment) {
    feedbackSentiment = sentiment;
    feedbackScreenshot = null;
    feedbackCaptureNotice = null;
    feedbackSubmitNotice = null;
    await tick();
    if (feedbackBridge) {
      try {
        feedbackScreenshot = await feedbackBridge.captureWindow();
      } catch {
        feedbackCaptureNotice = "窗口截图失败，可以不附加截图继续反馈。";
      }
    } else {
      feedbackCaptureNotice = "当前环境无法截取应用窗口。";
    }
    feedbackOpen = true;
  }

  function closeFeedback() {
    if (feedbackSubmitBusy) return;
    feedbackOpen = false;
    feedbackScreenshot = null;
    feedbackCaptureNotice = null;
    feedbackSubmitNotice = null;
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
        sentiment: feedbackSentiment,
        category: form.category,
        message: form.message,
        expected_output: form.expectedOutput,
        contact: form.contact,
        context: {
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
        },
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
      showToast("反馈已发送，谢谢。", "success");
    } catch (error) {
      feedbackSubmitNotice = error instanceof Error ? error.message : "反馈发送失败，请稍后重试。";
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
      persistedConfig = await settingsApi.saveConfig(confirmedConfig);
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
        changeViewScale("in");
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        changeViewScale("out");
        return;
      }
      if (event.key === "0") {
        event.preventDefault();
        setViewScale(1);
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
    if (batch.phase !== "closed") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeBatchView(true);
      }
      return;
    }
    if (markdownPreview.phase !== "closed") {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMarkdownPreviewView(true);
      }
      return;
    }
    if (translation.phase !== "closed") {
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

  function readViewScale(): number {
    try {
      return normalizeViewScale(Number(window.localStorage.getItem("reflex-view-scale") ?? 1));
    } catch {
      return 1;
    }
  }

  function setViewScale(next: number) {
    viewScale = normalizeViewScale(next);
    try {
      window.localStorage.setItem("reflex-view-scale", String(viewScale));
    } catch {
      // The view remains usable when browser storage is unavailable.
    }
  }

  function changeViewScale(direction: "in" | "out") {
    setViewScale(stepViewScale(viewScale, direction));
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

  function providerStatusAriaLabel(): string {
    return tr("Provider：{provider}，{status}", {
      provider: tr(providerName(state.requestDraft.provider, providerOptions)),
      status: providerStatusText
    });
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

<main class="app-shell" data-phase={state.phase} data-theme={settingsDraft.theme} style={`--view-scale: ${viewScale}`}>
  <section class="window" aria-label="Reflex quick window">
    <ReflexTitleBar
      providerName={tr(providerName(state.requestDraft.provider, providerOptions))}
      modelName={state.requestDraft.model ?? ""}
      availability={providerStatus}
      availabilityLabel={providerStatusText}
      scale={viewScale}
      windowSize={windowSizePreset}
      onOpenProvider={beginSettings}
      onOpenCommand={openCommandPalette}
      onZoomOut={() => changeViewScale("out")}
      onResetZoom={() => setViewScale(1)}
      onZoomIn={() => changeViewScale("in")}
      onWindowSizeChange={desktopBridge ? setWindowSize : undefined}
      onMinimize={desktopBridge ? minimizeWindow : undefined}
      onMaximize={desktopBridge ? toggleMaximizeWindow : undefined}
      onClose={hostApi ? hideMainWindow : undefined}
    />

    <div class="shell-main">
      <NavRail items={navItems} {activeNavId} onSelect={handleNavigation} />
      <section class="workbench-surface" aria-label={tr("工作台")}>
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
              onInput={setInput}
              onRun={runOptimization}
              onReadClipboard={readClipboard}
              onClear={clearInput}
            />
            <ConfigSummary
              items={configSummaryItems}
              phase={workbenchPhase}
              canRun={canGenerate}
              statusMessage={workbenchStatusMessage}
              onRun={runOptimization}
              onCancel={cancelRun}
              onAdjust={beginAdjust}
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
            copied={state.copied || toastText.includes("已复制") && toastVisible}
            rating={state.currentResult?.rating ?? null}
            ratingEnabled={state.currentResult?.saveStatus === "saved" && !resultRatingBusy}
            onCopy={copyResult}
            onReplace={askReplaceClipboard}
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

    <Toast visible={toastVisible} message={toastText} tone={toastTone} />

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
        onSubmit={submitFeedback}
      />
    {/if}

    {#if state.phase === "adjusting"}
      <AdjustPanel
        {draft}
        inputText={state.inputText}
        {modes}
        {styles}
        {scenes}
        models={draftProviderModels}
        translate={tr}
        onDraftChange={(value) => (draft = value)}
        onCancel={cancelAdjustView}
        onApply={applyAdjust}
      />
    {/if}

    {#if commandPaletteOpen}
      <CommandPalette items={commandItems} translate={tr} onClose={closeCommandPalette} />
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
        translate={tr}
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

    {#if batch.phase !== "closed"}
      <BatchDialog
        state={batch}
        fileNotice={batchFileNotice}
        {styles}
        {scenes}
        translate={tr}
        onStateChange={(value) => (batch = value)}
        onFileSelected={importBatchFile}
        onDownloadTemplate={downloadBatchTemplate}
        onParse={parseBatchSource}
        onCancel={cancelBatchRun}
        onExport={exportBatch}
        onRun={runBatch}
        onClose={() => closeBatchView(true)}
      />
    {/if}

    {#if translation.phase !== "closed"}
      <TranslationDialog
        state={translation}
        sourceLanguageLabel={translationLanguageLabel(translation.sourceLanguage)}
        targetLanguageLabel={translationLanguageLabel(translation.targetLanguage)}
        translate={tr}
        onTargetChange={chooseTranslationTarget}
        onCancel={cancelTranslationRun}
        onRetry={runTranslation}
        onCopy={copyTranslation}
        onUseResult={useTranslationAsCurrentResult}
        onClose={() => closeTranslationView(true)}
      />
    {/if}

    {#if markdownPreview.phase !== "closed"}
      <MarkdownPreviewDialog
        state={markdownPreview}
        translate={tr}
        onModeChange={(mode) => (markdownPreview = selectMarkdownPreviewMode(markdownPreview, mode))}
        onCopySource={() => writeClipboardValue(markdownPreview.sourceText, "✓ 源码已复制")}
        onRetry={runMarkdownPreview}
        onClose={() => closeMarkdownPreviewView(true)}
      />
    {/if}

    {#if state.overlay === "clipboard_confirm"}
      <ClipboardConfirmDialog notice={clipboardNotice} translate={tr} onCancel={closeOverlay} onConfirm={confirmReplaceClipboard} />
    {/if}

    {#if state.overlay === "result_compare"}
      <ResultCompareDialog
        sourceText={state.currentResult?.sourceText ?? ""}
        output={state.output}
        translate={tr}
        onCopySource={copyComparisonSource}
        onCopyOutput={copyComparisonResult}
        onClose={closeOverlay}
      />
    {/if}

    {#if state.overlay === "plugin_manager"}
      <PluginDialog translate={tr} onManage={managePluginSettings} onClose={closeOverlay} />
    {/if}

    {#if state.overlay === "settings"}
      <SettingsDialog
        draft={settingsDraft}
        section={settingsSection}
        busy={settingsBusy}
        {secretBusy}
        {secretInput}
        {secretStatus}
        {secretNotice}
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
        cloudImprovementEnabled={cloudImprovementDraft}
        {cloudQuota}
        {cloudPrivacyBusy}
        {cloudPrivacyNotice}
        translate={tr}
        onClose={cancelSettingsView}
        onSave={saveSettings}
        onSectionChange={selectSettingsSection}
        onDraftChange={(value) => (settingsDraft = value)}
        onProviderChange={selectSettingsProvider}
        onSecretInput={(value) => (secretInput = value)}
        onSaveSecret={saveSecret}
        onDeleteSecret={deleteSecret}
        onPluginChange={setPluginEnabled}
        onSemanticRefresh={refreshSemanticModelStatus}
        onSemanticCancel={cancelSemanticModelDownload}
        onSemanticDelete={deleteSemanticModel}
        onSemanticDownload={downloadSemanticModel}
        onDiagnosticExport={exportDiagnosticBundle}
        onDiagnosticCancel={cancelDiagnosticBundleExport}
        onCloudImprovementChange={(enabled) => (cloudImprovementDraft = enabled)}
        onCloudRefresh={hydrateCloudPrivacy}
        onCloudDeleteData={confirmDeleteCloudData}
      />
    {/if}
  </section>
</main>
