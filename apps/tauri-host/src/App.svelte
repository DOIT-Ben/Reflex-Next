<script lang="ts">
  import { onMount } from "svelte";
  import SettingsDialog from "./components/settings/SettingsDialog.svelte";
  import type { SettingsSection } from "./components/settings/types";
  import MarkdownPreviewDialog from "./components/tools/MarkdownPreviewDialog.svelte";
  import TranslationDialog from "./components/tools/TranslationDialog.svelte";
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
    providerDisplayName,
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
    batchCompletedCount,
    batchProcessedCount,
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
    setBatchConcurrency,
    setBatchFormat,
    setBatchScene,
    setBatchSourceText,
    setBatchStyle,
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
    providerModels,
    resolveProviderAvailability,
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
  const batchFormats: Array<{ id: BatchFormat; label: string }> = [
    { id: "txt", label: "TXT 每行一条" },
    { id: "csv", label: "CSV prompt 列" }
  ];

  let coreBridge: CoreBridge = new DemoCoreBridge();
  let capabilityBridge: CapabilityBridge | null = null;
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
  let batchCloseButton: HTMLButtonElement | null = null;
  let batchFileInput: HTMLInputElement | null = null;
  let batchFileNotice: string | null = null;
  let customTemplates: PromptTemplate[] = [];
  let templateDraft: TemplateDraft = createTemplateDraft();
  let selectedTemplateId: string | null = null;
  let templateQuery = "";
  let templateCategory: string | null = null;
  let templateValues: Record<string, string> = {};
  let templateNotice: string | null = null;
  let templateBusy = false;
  let templateCloseButton: HTMLButtonElement | null = null;
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
  let providerStatus: ProviderAvailability = "checking";
  let activeProviderId = "minimax";
  let providerStatusText = "";
  let settingsNotice: string | null = null;
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
  let resultRatingBusy = false;
  let viewScale = 1;
  let windowSizePreset: WindowSizePreset = "default";
  let commandPaletteOpen = false;
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
      settingsApi = createSettingsApi(host);
      clipboardReader = createClipboardReader(host);
      clipboardWriter = createClipboardWriter(host);
      const desktop = createDesktopBridge(host);
      desktopBridge = desktop;

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

      await Promise.all([hydrateSettings(), refreshDesktopStatus()]);
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
  $: settingsProviderModels = providerModels(settingsDraft.default_provider);
  $: draftProviderModels = providerModels(draft.provider);
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
  $: configSummaryItems = [
    { id: "mode", label: tr("模式"), value: modeLabel(state.requestDraft.mode) },
    { id: "style", label: tr("风格"), value: styleLabel(state.requestDraft.style) },
    { id: "scene", label: tr("场景"), value: sceneLabel(state.requestDraft.scene) },
    {
      id: "model",
      label: tr("模型"),
      value: state.requestDraft.model ?? tr(providerDisplayName(state.requestDraft.provider))
    }
  ];
  $: resultMetaItems = [
    { id: "mode", label: tr("模式"), value: modeLabel(state.currentResult?.mode ?? state.requestDraft.mode) },
    { id: "style", label: tr("风格"), value: styleLabel(state.currentResult?.style ?? state.requestDraft.style) },
    {
      id: "provider",
      label: "Provider",
      value: tr(providerDisplayName(state.currentResult?.provider ?? state.requestDraft.provider))
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
      showToast("✓ 设置已保存");
    } catch (error) {
      settingsNotice = safeDesktopSettingsError(error);
    } finally {
      settingsBusy = false;
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
    if (!window.confirm("删除已保存的 API Key？")) return;
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
    const models = providerModels(provider);
    settingsDraft = { ...settingsDraft, default_provider: provider, default_model: models[0].id };
    secretInput = "";
    secretNotice = null;
    await refreshProviderSecretStatus(provider);
  }

  function showToast(message: string) {
    toastText = tr(message);
    toastVisible = true;
    window.setTimeout(() => {
      toastVisible = false;
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
    window.setTimeout(() => batchCloseButton?.focus());
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
    window.setTimeout(() => templateCloseButton?.focus());
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
    if (!window.confirm("删除当前模板？")) return;
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

  function requestBatchFileImport() {
    if (batch.phase === "parsing" || batch.phase === "running") return;
    batchFileInput?.click();
  }

  async function importBatchFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
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
    if (!window.confirm(tr("删除本地语义模型？之后仍可重新下载。"))) return;
    await runSemanticModelOperation("delete");
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
      provider: tr(providerDisplayName(state.requestDraft.provider)),
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
      providerName={tr(providerDisplayName(state.requestDraft.provider))}
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
            onRetry={state.errorRecoverable ? retryRun : undefined}
            onOpenSettings={openSettingsView}
            onCopyDiagnosticId={state.diagnosticId ? copyDiagnosticId : undefined}
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
      versionLabel="v0.6 beta"
    />

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
      <div class="command-layer" role="presentation">
        <div class="command-dialog" role="dialog" aria-modal="true" aria-label={tr("命令面板")}>
          <header>
            <strong>{tr("命令")}</strong>
            <button type="button" aria-label={tr("关闭命令面板")} on:click={closeCommandPalette}>×</button>
          </header>
          <div class="command-list">
            <button type="button" on:click={() => { closeCommandPalette(); beginAdjust(); }}>{tr("调整生成方案")}</button>
            <button type="button" on:click={() => { closeCommandPalette(); openTemplateManager(); }}>{tr("模板管理")}</button>
            <button type="button" disabled={!batchRunnerEnabled} on:click={() => { closeCommandPalette(); openBatchView(); }}>{tr("批量处理")}</button>
            <button type="button" disabled={!translatorEnabled || !state.currentResult?.output} on:click={() => { closeCommandPalette(); openTranslationView(); }}>{tr("翻译当前结果")}</button>
            <button type="button" disabled={!markdownPreviewEnabled || !state.currentResult?.output} on:click={() => { closeCommandPalette(); openMarkdownPreviewView(); }}>{tr("预览 Markdown")}</button>
            <button type="button" on:click={() => { closeCommandPalette(); openHistoryWindow(); }}>{tr("打开历史记录")}</button>
            <button type="button" on:click={() => { closeCommandPalette(); beginSettings(); }}>{tr("打开设置")}</button>
          </div>
        </div>
      </div>
    {/if}

    {#if state.overlay === "template_manager"}
      <div class="template-layer" role="presentation">
        <div class="template-dialog" role="dialog" aria-modal="true" aria-label={tr("模板管理")}>
          <div class="template-head">
            <div><h2>{tr("模板管理")}</h2><p>{tr("自定义模板仅保存在本机配置中。")}</p></div>
            <button class="icon-button" aria-label={tr("关闭模板管理")} bind:this={templateCloseButton} on:click={() => closeTemplateManager(true)}>×</button>
          </div>
          <div class="template-layout">
            <aside class="template-list">
              <input aria-label={tr("搜索模板")} bind:value={templateQuery} placeholder={tr("搜索名称、分类或标签")} />
              <select aria-label={tr("模板分类")} bind:value={templateCategory}>
                <option value={null}>{tr("全部分类")}</option>
                {#each templateCategories as category}<option value={category}>{category}</option>{/each}
              </select>
              <button class="outline" type="button" on:click={() => { selectedTemplateId = null; templateDraft = createTemplateDraft(); templateValues = {}; templateNotice = null; }}>{tr("新建模板")}</button>
              <div class="template-list-items">
                {#each visibleTemplates as template}
                  <button class:active={selectedTemplateId === template.id} type="button" on:click={() => selectTemplate(template)}>
                    <strong>{template.name}</strong><span>{template.category}{template.tags.length ? ` · ${template.tags.join("、")}` : ""}</span>
                  </button>
                {:else}<p>{tr("还没有符合条件的模板。")}</p>{/each}
              </div>
            </aside>
            <section class="template-editor">
              <div class="template-fields">
                <label><span>{tr("名称")}</span><input bind:value={templateDraft.name} disabled={templateBusy} /></label>
                <label><span>{tr("分类")}</span><input bind:value={templateDraft.category} disabled={templateBusy} /></label>
                <label class="wide"><span>{tr("标签（用逗号分隔）")}</span><input value={templateDraft.tags.join(", ")} disabled={templateBusy} on:input={(event) => templateDraft = { ...templateDraft, tags: event.currentTarget.value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) }} /></label>
                <label class="wide"><span>{tr("说明")}</span><input bind:value={templateDraft.description} disabled={templateBusy} /></label>
                <label class="wide"><span>{tr("模板内容")}</span><textarea bind:value={templateDraft.content} disabled={templateBusy} placeholder={tr("使用 {变量名} 插入需要填写的内容")}></textarea></label>
              </div>
              {#if templateVariables(templateDraft.content).length}
                <div class="template-variables">
                  <h3>{tr("填写变量")}</h3>
                  {#each templateVariables(templateDraft.content) as variable}
                    <label><span>{variable}</span><input value={templateValues[variable] ?? ""} on:input={(event) => templateValues = { ...templateValues, [variable]: event.currentTarget.value }} /></label>
                  {/each}
                </div>
              {/if}
              <p class="template-notice" aria-live="polite">{templateNotice ? tr(templateNotice) : ""}</p>
              <div class="template-footer">
                <button class="outline danger" type="button" disabled={!selectedTemplateId || templateBusy} on:click={deleteTemplate}>{tr("删除")}</button>
                <span></span><button class="outline" type="button" disabled={templateBusy} on:click={saveTemplate}>{tr("保存模板")}</button><button class="primary small" type="button" on:click={applyTemplate}>{tr("应用到输入区")}</button>
              </div>
            </section>
          </div>
        </div>
      </div>
    {/if}

    {#if batch.phase !== "closed"}
      <div class="batch-layer" role="presentation">
        <div class="batch-dialog" role="dialog" aria-modal="true" aria-label={tr("批量处理")}>
          <div class="batch-head">
            <div>
              <h2>{tr("批量处理")}</h2>
              <p>{tr("最多导入 200 条提示词，结果在本机导出。")}</p>
            </div>
            <button class="icon-button" aria-label={tr("关闭批量处理")} bind:this={batchCloseButton} on:click={() => closeBatchView(true)}>×</button>
          </div>

          <div class="batch-controls">
            <div class="batch-format" role="group" aria-label={tr("导入格式")}>
              {#each batchFormats as item}
                <button
                  type="button"
                  class:active={batch.format === item.id}
                  aria-pressed={batch.format === item.id}
                  disabled={batch.phase === "parsing" || batch.phase === "running"}
                  on:click={() => batch = setBatchFormat(batch, item.id)}
                >{tr(item.label)}</button>
              {/each}
            </div>
            <label>
              <span>{tr("处理风格")}</span>
              <select
                value={batch.style}
                disabled={batch.phase === "running"}
                on:change={(event) => batch = setBatchStyle(batch, event.currentTarget.value as OptimizeStyle)}
              >
                {#each styles as item}
                  <option value={item.id}>{tr(item.label)}</option>
                {/each}
              </select>
            </label>
            <label>
              <span>{tr("场景")}</span>
              <select
                value={batch.scene ?? ""}
                disabled={batch.phase === "running"}
                on:change={(event) => batch = setBatchScene(batch, event.currentTarget.value)}
              >
                <option value="">{tr("自动识别")}</option>
                {#each scenes as scene}
                  <option value={scene.id}>{tr(scene.label)}</option>
                {/each}
              </select>
            </label>
            <label>
              <span>{tr("并发数")}</span>
              <select
                value={batch.concurrency}
                disabled={batch.phase === "running"}
                on:change={(event) => batch = setBatchConcurrency(batch, Number(event.currentTarget.value))}
              >
                {#each [1, 2, 3, 4] as value}
                  <option value={value}>{value}</option>
                {/each}
              </select>
            </label>
          </div>

          <label class="batch-source">
            <span>{tr(batch.format === "csv" ? "粘贴 CSV，需包含 prompt 或 提示词 列" : "粘贴文本，每行一条提示词")}</span>
            <textarea
              aria-label={tr("批量输入内容")}
              value={batch.sourceText}
              disabled={batch.phase === "parsing" || batch.phase === "running"}
              on:input={(event) => batch = setBatchSourceText(batch, event.currentTarget.value)}
              placeholder={batch.format === "csv" ? "prompt\nWrite a business email" : tr("写一封商务邮件\n解释什么是机器学习")}
            ></textarea>
          </label>
          <input
            type="file"
            accept=".csv,text/csv,.txt,text/plain"
            hidden
            bind:this={batchFileInput}
            on:change={importBatchFile}
          />

          <div class="batch-action-row">
            <div class="batch-import-actions">
              <button class="outline" type="button" disabled={batch.phase === "parsing" || batch.phase === "running"} on:click={requestBatchFileImport}>{tr("导入文件")}</button>
              <button class="outline" type="button" disabled={batch.phase === "parsing" || batch.phase === "running"} on:click={downloadBatchTemplate}>{tr("下载模板")}</button>
              <button class="outline" type="button" disabled={batch.phase === "parsing" || batch.phase === "running" || !batch.sourceText.trim()} on:click={parseBatchSource}>
                {tr(batch.phase === "parsing" ? "正在解析" : "解析内容")}
              </button>
            </div>
            <p aria-live="polite">
              {#if batchFileNotice}
                <span class="error">{tr(batchFileNotice)}</span>
              {:else if batch.phase === "running"}
                {tr("正在处理 {processed}/{total}，已完成 {completed} 条", { processed: batchProcessedCount(batch), total: batch.items.length, completed: batchCompletedCount(batch) })}
              {:else if batch.phase === "completed"}
                {tr("已完成 {completed}/{total} 条", { completed: batchCompletedCount(batch), total: batch.items.length })}
              {:else if batch.phase === "cancelled"}
                {tr("已停止，已完成 {completed} 条", { completed: batchCompletedCount(batch) })}
              {:else if batch.error}
                <span class="error">{tr(batch.error)}</span>
              {:else if batch.items.length}
                {tr("已解析 {count} 条提示词", { count: batch.items.length })}
              {:else}
                {tr("等待导入内容")}
              {/if}
            </p>
          </div>

          <div class="batch-list" aria-label={tr("批处理列表")}>
            {#if batch.items.length}
              {#each batch.items as item}
                <article class:completed={item.status === "completed"} class:failed={item.status === "failed"} class:running={item.status === "running"} class="batch-item">
                  <span class="batch-item-id">{item.id}</span>
                  <div>
                    <strong>{item.prompt}</strong>
                    {#if item.result}<p>{item.result}</p>{/if}
                    {#if item.error}<p class="error">{tr(item.error)}</p>{/if}
                  </div>
                  <span class="batch-status">{tr(item.status === "pending" ? "等待" : item.status === "running" ? "处理中" : item.status === "completed" ? "已完成" : item.status === "cancelled" ? "已停止" : "失败")}</span>
                </article>
              {/each}
            {:else}
              <p class="batch-empty">{tr("解析后将在这里显示待处理的提示词。")}</p>
            {/if}
          </div>

          <div class="batch-footer">
            {#if batch.phase === "running"}
              <button class="outline" type="button" on:click={cancelBatchRun}>{tr("停止")}</button>
            {:else}
              <button class="outline" type="button" disabled={!batchCanExport(batch)} on:click={exportBatch}>{tr("导出结果")}</button>
              <button class="primary small" type="button" disabled={!batch.items.length} on:click={runBatch}>{tr("开始处理")}</button>
            {/if}
          </div>
        </div>
      </div>
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
      <div class="modal-layer" role="presentation">
        <section class="clipboard-modal" aria-label={tr("替换剪贴板确认")}>
          <h2>{tr("替换当前剪贴板内容？")}</h2>
          <p>{tr("原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。")}</p>
          {#if clipboardNotice}
            <p class="clipboard-feedback" aria-live="polite">{tr(clipboardNotice)}</p>
          {/if}
          <div>
            <button class="outline" on:click={closeOverlay}>{t(uiLanguage, "cancel")}</button>
            <button class="primary small" on:click={confirmReplaceClipboard}>{tr("确认替换")}</button>
          </div>
        </section>
      </div>
    {/if}

    {#if state.overlay === "result_compare"}
      <div class="translation-layer" role="presentation">
        <div class="translation-dialog" role="dialog" aria-modal="true" aria-label={tr("结果对比")}>
          <div class="translation-head">
            <div><h2>{tr("结果对比")}</h2></div>
            <button class="icon-button" aria-label={tr("关闭结果对比")} on:click={closeOverlay}>×</button>
          </div>
          <div class="translation-content">
            <section class="translation-pane" aria-label={tr("原文")}>
              <div class="translation-pane-head">
                <h3>{tr("原文")}</h3>
                <button class="outline small" type="button" on:click={copyComparisonSource}>{tr("复制")}</button>
              </div>
              {#if state.currentResult?.sourceText}
                <pre>{state.currentResult.sourceText}</pre>
              {/if}
            </section>
            <section class="translation-pane translated" aria-label={tr("优化结果")}>
              <div class="translation-pane-head">
                <h3>{tr("优化结果")}</h3>
                <button class="outline small" type="button" on:click={copyComparisonResult}>{tr("复制")}</button>
              </div>
              <pre>{state.output}</pre>
            </section>
          </div>
          <div class="translation-footer">
            <button class="primary small" type="button" on:click={closeOverlay}>{tr("关闭")}</button>
          </div>
        </div>
      </div>
    {/if}

    {#if state.overlay === "plugin_manager"}
      <div class="settings-layer" role="presentation">
        <section class="plugin-dialog" aria-label={tr("插件")}>
          <div class="settings-head">
            <div>
              <h2>{tr("插件")}</h2>
              <p>{tr("查看当前可用能力及其访问范围。")}</p>
            </div>
            <button class="icon-button" aria-label={tr("关闭插件")} on:click={closeOverlay}>×</button>
          </div>
          <div class="plugin-list">
            <article class="plugin-row">
              <div>
                <strong>{tr("MiniMax 模型服务")}</strong>
                <span>{tr("生成与优化文本")}</span>
              </div>
              <span class="permission-badge">{tr("网络访问")}</span>
            </article>
            <article class="plugin-row">
              <div>
                <strong>{tr("内置模板")}</strong>
                <span>{tr("提供场景、风格与语言模板")}</span>
              </div>
              <span class="permission-badge">{tr("本地内容")}</span>
            </article>
            <article class="plugin-row">
              <div>
                <strong>{tr("场景识别")}</strong>
                <span>{tr("根据当前文本选择适合的处理方式")}</span>
              </div>
              <span class="permission-badge">{tr("本地文本")}</span>
            </article>
          </div>
          <div class="plugin-footer">
            <span>{tr("3 项内置能力")}</span>
            <button class="primary small" type="button" on:click={managePluginSettings}>{tr("管理设置")}</button>
          </div>
        </section>
      </div>
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
        models={settingsProviderModels}
        {modes}
        {styles}
        {desktopStatus}
        {semanticModel}
        semanticEnabled={semanticDetectorEnabled}
        semanticActive={semanticDetectorActive}
        semanticStatusText={semanticModelStatusText()}
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
      />
    {/if}
  </section>
</main>
