<script lang="ts">
  import { onMount } from "svelte";
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
    applySceneSelection,
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
    SETTINGS_PLUGIN_IDS,
    settingsDraftFromConfig,
    startGeneration,
    updateHistorySettingsDraft,
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
    selectMarkdownPreviewMode,
    type MarkdownPreviewMode
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
    listSceneOptions,
    type OptimizeMode,
    type OptimizeStyle,
    type ScenePolicy
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
  const clipboardPolicies: Array<{ id: HostSettingsDraft["clipboard_policy"]; label: string }> = [
    { id: "startup", label: "启动时读取" },
    { id: "manual", label: "仅手动读取" },
    { id: "auto_replace", label: "生成后自动替换" }
  ];
  const scenePolicies: Array<{ id: ScenePolicy; label: string }> = [
    { id: "auto", label: "自动" },
    { id: "ask", label: "每次询问" },
    { id: "manual", label: "手动固定" }
  ];
  const historyRedactionOptions: Array<{
    id: HostSettingsDraft["history_redaction"];
    label: string;
  }> = [
    { id: "secrets", label: "隐藏敏感内容" },
    { id: "none", label: "保留原文" }
  ];
  const settingsPlugins: Array<{
    id: SettingsPluginId;
    label: string;
    description: string;
  }> = [
    { id: SETTINGS_PLUGIN_IDS[0], label: "翻译", description: "跨语言转换" },
    { id: SETTINGS_PLUGIN_IDS[1], label: "Markdown 预览", description: "渲染 Markdown 内容" },
    { id: SETTINGS_PLUGIN_IDS[2], label: "批处理", description: "导入与导出批量提示词" },
    { id: SETTINGS_PLUGIN_IDS[3], label: "语义识别", description: "使用已安装的本地模型增强场景识别" }
  ];
  const settingsSections = [
    { id: "provider", label: "模型与 Provider" },
    { id: "defaults", label: "默认行为" },
    { id: "clipboard", label: "剪贴板" },
    { id: "privacy", label: "安全与隐私" },
    { id: "plugins", label: "插件" }
  ] as const;
  type SettingsSection = (typeof settingsSections)[number]["id"];
  const translationTargets: Array<{ id: TranslationTarget; label: string }> = [
    { id: "auto", label: "自动" },
    { id: "zh", label: "中文" },
    { id: "en", label: "English" }
  ];
  const markdownPreviewModes: Array<{ id: MarkdownPreviewMode; label: string }> = [
    { id: "split", label: "分栏" },
    { id: "source", label: "源码" },
    { id: "preview", label: "预览" }
  ];
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
  let translationCloseButton: HTMLButtonElement | null = null;
  let markdownPreview = createMarkdownPreviewState();
  let markdownPreviewRun: AbortController | null = null;
  let markdownPreviewCloseButton: HTMLButtonElement | null = null;
  let batch = createBatchState();
  let batchRun: AbortController | null = null;
  let batchCloseButton: HTMLButtonElement | null = null;
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
  let moreActionsOpen = false;
  let moreActionsButton: HTMLButtonElement | null = null;
  let resultRatingBusy = false;

  onMount(() => {
    let disposed = false;
    let stopListening: (() => void) | null = null;
    let stopHistoryReuseListening: (() => void) | null = null;

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
    };
  });

  $: summary = [
    modeLabel(state.requestDraft.mode),
    styleLabel(state.requestDraft.style),
    sceneLabel(state.requestDraft.scene),
    providerDisplayName(state.requestDraft.provider)
  ].join(" · ");
  $: inputCount = `${state.inputText.trim().length} 字`;
  $: canGenerate = state.canGenerate && !isGenerating(state.phase);
  $: translatorEnabled = persistedConfig?.enabled_plugins.includes("translator") ?? true;
  $: markdownPreviewEnabled = persistedConfig?.enabled_plugins.includes("markdown-preview") ?? true;
  $: batchRunnerEnabled = persistedConfig?.enabled_plugins.includes("batch-runner") ?? true;

  function setInput(value: string) {
    state = updateInput(state, value);
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
  }

  async function hydrateSettings() {
    if (!settingsApi) return;
    settingsBusy = true;
    settingsNotice = null;
    secretNotice = null;
    let config: AppConfig;
    try {
      config = await settingsApi.loadConfig();
      persistedConfig = config;
      state = applyPersistedConfig(state, config);
      settingsDraft = settingsDraftFromConfig(config);
    } catch {
      settingsNotice = "设置加载失败，请重试。";
      settingsBusy = false;
      return;
    }
    try {
      secretStatus = await settingsApi.getProviderSecretStatus(config.provider);
    } catch {
      secretNotice = "密钥状态读取失败，请重试。";
    } finally {
      settingsBusy = false;
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
      secretNotice = "密钥已安全保存。";
    } catch {
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
      secretNotice = "密钥已删除。";
    } catch {
      secretNotice = "密钥删除失败，请重试。";
    } finally {
      secretInput = "";
      secretBusy = false;
    }
  }

  function showToast(message: string) {
    toastText = message;
    toastVisible = true;
    window.setTimeout(() => {
      toastVisible = false;
    }, 1400);
  }

  async function runOptimization() {
    if (!canGenerate) return;
    moreActionsOpen = false;
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

  function openTranslationView() {
    const source = state.currentResult;
    if (!source?.output.trim() || !translatorEnabled) return;
    closeMoreActions();
    translationSourceResult = { ...source };
    translation = openTranslation(translation, source.output);
    if (translation.phase !== "closed") {
      window.setTimeout(() => translationCloseButton?.focus());
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
    if (restoreFocus) window.setTimeout(() => moreActionsButton?.focus());
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
    closeMoreActions();
    markdownPreview = openMarkdownPreview(markdownPreview, source);
    if (markdownPreview.phase !== "closed") {
      window.setTimeout(() => markdownPreviewCloseButton?.focus());
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
    if (restoreFocus) window.setTimeout(() => moreActionsButton?.focus());
  }

  function openBatchView() {
    if (!batchRunnerEnabled) return;
    closeMoreActions();
    if (markdownPreview.phase !== "closed") closeMarkdownPreviewView();
    if (translation.phase !== "closed") closeTranslationView();
    batch = openBatch(batch);
    window.setTimeout(() => batchCloseButton?.focus());
  }

  function closeBatchView(restoreFocus = false) {
    batchRun?.abort();
    batchRun = null;
    batch = closeBatch(batch);
    if (restoreFocus) window.setTimeout(() => moreActionsButton?.focus());
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

  function toggleMoreActions() {
    moreActionsOpen = !moreActionsOpen;
  }

  function closeMoreActions(restoreFocus = false) {
    moreActionsOpen = false;
    if (restoreFocus) moreActionsButton?.focus();
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
    closeMoreActions();
    void hostApi?.invoke("show_history_window").catch(() => showToast("历史记录暂时不可用。"));
  }

  function runFromMoreActions(action: "replace" | "regenerate" | "adjust") {
    closeMoreActions();
    if (action === "replace") askReplaceClipboard();
    else if (action === "regenerate") void runOptimization();
    else beginAdjust();
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
  }

  function setHistoryEnabled(enabled: boolean) {
    settingsDraft = updateHistorySettingsDraft(settingsDraft, {
      history_enabled: enabled
    });
  }

  function setPrivacyMode(enabled: boolean) {
    settingsDraft = updateHistorySettingsDraft(settingsDraft, {
      privacy_mode: enabled
    });
  }

  function setHistoryRedaction(value: HostSettingsDraft["history_redaction"]) {
    settingsDraft = updateHistorySettingsDraft(settingsDraft, {
      history_redaction: value
    });
  }

  function setPluginEnabled(pluginId: SettingsPluginId, enabled: boolean) {
    settingsDraft = updatePluginSettingsDraft(settingsDraft, pluginId, enabled);
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
    if (moreActionsOpen && event.key === "Escape") {
      event.preventDefault();
      closeMoreActions(true);
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

  function isGenerating(phase: HostState["phase"]): boolean {
    return phase === "analyzing_scene" || phase === "connecting_provider" || phase === "streaming";
  }

  function modeLabel(value: OptimizeMode): string {
    return modes.find((item) => item.id === value)?.label ?? "内容优化";
  }

  function styleLabel(value: ResultStyle): string {
    if (value === "precise") return "精准";
    return styles.find((item) => item.id === value)?.label ?? "平衡";
  }

  function sceneLabel(value: string | null): string {
    return scenes.find((item) => item.id === value)?.label ?? "自动识别";
  }

  function translationLanguageLabel(value: TranslationLanguage | null): string {
    if (value === "zh") return "中文";
    if (value === "en") return "English";
    return "自动识别";
  }

  function chooseDraftScene(value: string) {
    draft = applySceneSelection(draft, value);
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<main class="app-shell" data-phase={state.phase}>
  <section class="window" aria-label="Reflex quick window">
    <header class="top-bar">
      <div class="brand">
        <span class="brand-mark">R</span>
        <strong>Reflex</strong>
      </div>
      <div class="provider-pill"><span></span>{providerDisplayName(state.requestDraft.provider)}</div>
      <button class="icon-button" aria-label="设置" on:click={beginSettings}>⚙</button>
    </header>

    {#if state.phase === "adjusting"}
      <section class="adjust-view" aria-label="生成设置">
        <div class="badge">当前方案</div>
        <h1>生成设置</h1>

        <div class="settings-panel">
          <div class="setting-row">
            <span>模式</span>
            <div class="segments">
              {#each modes as item}
                <button class:active={draft.mode === item.id} on:click={() => (draft = { ...draft, mode: item.id })}>
                  {item.label}
                </button>
              {/each}
            </div>
          </div>

          <div class="setting-row">
            <span>风格</span>
            <div class="segments compact">
              {#each styles as item}
                <button class:active={draft.style === item.id} on:click={() => (draft = { ...draft, style: item.id })}>
                  {item.label}
                </button>
              {/each}
            </div>
          </div>

          <label class="setting-row">
            <span>场景</span>
            <select
              value={draft.scene ?? ""}
              on:change={(event) => chooseDraftScene(event.currentTarget.value)}
            >
              <option value="">自动识别</option>
              {#each scenes as scene}
                <option value={scene.id}>{scene.label}</option>
              {/each}
            </select>
          </label>

          <label class="setting-row">
            <span>模型</span>
            <select bind:value={draft.model}>
              <option value="MiniMax-M2.7-highspeed">MiniMax / M2.7 高速版</option>
            </select>
          </label>

          <div class="setting-row current-input">
            <span>当前输入</span>
            <p>{state.inputText}</p>
          </div>
        </div>

        <div class="footer-actions">
          <button class="outline" on:click={cancelAdjustView}>取消</button>
          <button class="primary small" on:click={applyAdjust}>应用</button>
        </div>
      </section>
    {:else if isGenerating(state.phase)}
      <section class="generation-view" aria-label="正在生成">
        <div class="badge">当前方案</div>
        <h1>正在生成</h1>
        <p class="subline">{summary}</p>
        <div class="progress"><span style={`width: ${state.phase === "streaming" ? 76 : 48}%`}></span></div>
        <article class="result-card streaming">
          <pre>{state.output || "正在准备结果…"}</pre>
          <span class="cursor">▋</span>
        </article>
        <div class="footer-meta">
          <span>{state.phase === "analyzing_scene" ? "正在分析场景" : state.phase === "connecting_provider" ? "正在连接模型" : "正在生成内容"}</span>
          <button class="outline" on:click={cancelRun}>取消生成</button>
        </div>
      </section>
    {:else if state.phase === "completed"}
      <section class="complete-view" aria-label="优化完成">
        <div class="badge">当前方案</div>
        <h1>优化完成</h1>
        <p class="subline">{sceneLabel(state.currentResult?.scene ?? null)} · {styleLabel(state.currentResult?.style ?? state.requestDraft.style)} · 约 {state.output.length} 字</p>
        <article class="result-card">
          <pre>{state.output}</pre>
        </article>
        <div class="result-actions">
          <button class="primary small" on:click={copyResult}>复制结果</button>
          <div class="more-actions">
            <button
              class="icon-button more-button"
              aria-label="更多操作"
              aria-expanded={moreActionsOpen}
              bind:this={moreActionsButton}
              on:click={toggleMoreActions}
            >⋯</button>
            {#if moreActionsOpen}
              <div class="result-menu" role="menu" aria-label="结果操作">
                <button role="menuitem" on:click={() => runFromMoreActions("replace")}>替换剪贴板</button>
                <button role="menuitem" on:click={() => runFromMoreActions("regenerate")}>重新生成</button>
                <button role="menuitem" on:click={() => runFromMoreActions("adjust")}>调整</button>
                <button
                  role="menuitem"
                  disabled={!translatorEnabled || !state.currentResult?.output}
                  on:click={openTranslationView}
                >翻译</button>
                <button
                  role="menuitem"
                  disabled={!markdownPreviewEnabled || !state.currentResult?.output}
                  on:click={openMarkdownPreviewView}
                >Markdown 预览</button>
                <button role="menuitem" disabled={!batchRunnerEnabled} on:click={openBatchView}>批量处理</button>
                <div class="rating-menu" aria-label="评分">
                  <span>评分</span>
                  <div>
                    {#each [1, 2, 3, 4, 5] as score}
                      <button
                        aria-label={`评分 ${score}`}
                        aria-pressed={state.currentResult?.rating === score}
                        disabled={state.currentResult?.saveStatus !== "saved" || resultRatingBusy}
                        on:click={() => rateCurrentResult(score)}
                      >{score}</button>
                    {/each}
                  </div>
                </div>
                <button role="menuitem" on:click={openHistoryWindow}>查看历史</button>
              </div>
            {/if}
          </div>
        </div>
        <p class="recent result-save-status" role="status" aria-live="polite">{saveStatusLabel()}</p>
        {#if toastVisible}
          <div class="toast">{toastText}</div>
        {/if}
      </section>
    {:else if state.phase === "error"}
      <section class="error-view" aria-label="生成失败">
        <div class="badge">当前方案</div>
        <h1>生成失败</h1>
        <p class="subline">{summary}</p>
        <article class="error-panel">
          <strong>{state.errorMessage ?? "模型服务暂时不可用"}</strong>
          <span>
            {state.errorRecoverable ? "可以稍后重试，或检查当前 Provider 设置。" : "请检查文本或设置后再试。"}
          </span>
        </article>
        <div class="error-actions">
          {#if state.errorRecoverable}
            <button class="primary small" on:click={retryRun}>重试</button>
          {/if}
          <button class="outline" on:click={openSettingsView}>打开设置</button>
          <button class="outline" disabled={!state.diagnosticId} on:click={copyDiagnosticId}>复制诊断 ID</button>
        </div>
        <p class="recent">
          {state.errorCode ? `错误代码：${state.errorCode}` : "错误信息已脱敏"}
        </p>
        {#if toastVisible}
          <div class="toast">{toastText}</div>
        {/if}
      </section>
    {:else}
      <section class="default-view" aria-label="输入内容">
        <div class="badge">当前方案</div>
        <label class="input-label" for="source-text">输入内容</label>
        <div class="input-card">
          <textarea
            id="source-text"
            aria-label="输入内容"
            value={state.inputText}
            on:input={(event) => setInput(event.currentTarget.value)}
            placeholder="粘贴文本、需求或提示词…"
          ></textarea>
          <div class="input-tools">
            <button type="button" disabled={clipboardReading} on:click={readClipboard}>
              {clipboardReading ? "正在读取" : "读取剪贴板"}
            </button>
            <span>{inputCount}</span>
          </div>
        </div>
        {#if state.inputNotice}
          <p class="input-notice">{state.inputNotice}</p>
        {/if}

        <div class="summary-row">
          <span>{summary}</span>
          <div>
            <button disabled={!batchRunnerEnabled} on:click={openBatchView}>批量处理</button>
            <button on:click={beginAdjust}>调整</button>
          </div>
        </div>

        <button class="generate-button" disabled={!canGenerate} on:click={runOptimization}>
          优化文本 <span>→</span>
        </button>

      </section>
    {/if}

    {#if batch.phase !== "closed"}
      <div class="batch-layer" role="presentation">
        <div class="batch-dialog" role="dialog" aria-modal="true" aria-label="批量处理">
          <div class="batch-head">
            <div>
              <h2>批量处理</h2>
              <p>最多导入 200 条提示词，结果在本机导出。</p>
            </div>
            <button class="icon-button" aria-label="关闭批量处理" bind:this={batchCloseButton} on:click={() => closeBatchView(true)}>×</button>
          </div>

          <div class="batch-controls">
            <div class="batch-format" role="group" aria-label="导入格式">
              {#each batchFormats as item}
                <button
                  type="button"
                  class:active={batch.format === item.id}
                  aria-pressed={batch.format === item.id}
                  disabled={batch.phase === "parsing" || batch.phase === "running"}
                  on:click={() => batch = setBatchFormat(batch, item.id)}
                >{item.label}</button>
              {/each}
            </div>
            <label>
              <span>处理风格</span>
              <select
                value={batch.style}
                disabled={batch.phase === "running"}
                on:change={(event) => batch = setBatchStyle(batch, event.currentTarget.value as OptimizeStyle)}
              >
                {#each styles as item}
                  <option value={item.id}>{item.label}</option>
                {/each}
              </select>
            </label>
            <label>
              <span>场景</span>
              <select
                value={batch.scene ?? ""}
                disabled={batch.phase === "running"}
                on:change={(event) => batch = setBatchScene(batch, event.currentTarget.value)}
              >
                <option value="">自动识别</option>
                {#each scenes as scene}
                  <option value={scene.id}>{scene.label}</option>
                {/each}
              </select>
            </label>
            <label>
              <span>并发数</span>
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
            <span>{batch.format === "csv" ? "粘贴 CSV，需包含 prompt 或 提示词 列" : "粘贴文本，每行一条提示词"}</span>
            <textarea
              aria-label="批量输入内容"
              value={batch.sourceText}
              disabled={batch.phase === "parsing" || batch.phase === "running"}
              on:input={(event) => batch = setBatchSourceText(batch, event.currentTarget.value)}
              placeholder={batch.format === "csv" ? "prompt\n写一封商务邮件" : "写一封商务邮件\n解释什么是机器学习"}
            ></textarea>
          </label>

          <div class="batch-action-row">
            <button class="outline" type="button" disabled={batch.phase === "parsing" || batch.phase === "running" || !batch.sourceText.trim()} on:click={parseBatchSource}>
              {batch.phase === "parsing" ? "正在解析" : "解析内容"}
            </button>
            <p aria-live="polite">
              {#if batch.phase === "running"}
                正在处理 {batchProcessedCount(batch)}/{batch.items.length}，已完成 {batchCompletedCount(batch)} 条
              {:else if batch.phase === "completed"}
                已完成 {batchCompletedCount(batch)}/{batch.items.length} 条
              {:else if batch.phase === "cancelled"}
                已停止，已完成 {batchCompletedCount(batch)} 条
              {:else if batch.error}
                <span class="error">{batch.error}</span>
              {:else if batch.items.length}
                已解析 {batch.items.length} 条提示词
              {:else}
                等待导入内容
              {/if}
            </p>
          </div>

          <div class="batch-list" aria-label="批处理列表">
            {#if batch.items.length}
              {#each batch.items as item}
                <article class:completed={item.status === "completed"} class:failed={item.status === "failed"} class:running={item.status === "running"} class="batch-item">
                  <span class="batch-item-id">{item.id}</span>
                  <div>
                    <strong>{item.prompt}</strong>
                    {#if item.result}<p>{item.result}</p>{/if}
                    {#if item.error}<p class="error">{item.error}</p>{/if}
                  </div>
                  <span class="batch-status">{item.status === "pending" ? "等待" : item.status === "running" ? "处理中" : item.status === "completed" ? "已完成" : item.status === "cancelled" ? "已停止" : "失败"}</span>
                </article>
              {/each}
            {:else}
              <p class="batch-empty">解析后将在这里显示待处理的提示词。</p>
            {/if}
          </div>

          <div class="batch-footer">
            {#if batch.phase === "running"}
              <button class="outline" type="button" on:click={cancelBatchRun}>停止</button>
            {:else}
              <button class="outline" type="button" disabled={!batchCanExport(batch)} on:click={exportBatch}>导出结果</button>
              <button class="primary small" type="button" disabled={!batch.items.length} on:click={runBatch}>开始处理</button>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    {#if translation.phase !== "closed"}
      <div class="translation-layer" role="presentation">
        <div class="translation-dialog" role="dialog" aria-modal="true" aria-label="翻译结果">
          <div class="translation-head">
            <div>
              <h2>翻译结果</h2>
              {#if translation.sourceLanguage && translation.targetLanguage}
                <p>{translationLanguageLabel(translation.sourceLanguage)} → {translationLanguageLabel(translation.targetLanguage)}</p>
              {/if}
            </div>
            <button
              class="icon-button"
              aria-label="关闭翻译"
              bind:this={translationCloseButton}
              on:click={() => closeTranslationView(true)}
            >×</button>
          </div>

          <div class="translation-toolbar">
            <span>目标语言</span>
            <div class="translation-segments" role="group" aria-label="目标语言">
              {#each translationTargets as item}
                <button
                  type="button"
                  class:active={translation.target === item.id}
                  aria-pressed={translation.target === item.id}
                  disabled={translation.phase === "streaming"}
                  on:click={() => chooseTranslationTarget(item.id)}
                >{item.label}</button>
              {/each}
            </div>
          </div>

          <div class="translation-content">
            <section class="translation-pane" aria-label="原文">
              <h3>原文</h3>
              <pre>{translation.sourceText}</pre>
            </section>
            <section class="translation-pane translated" aria-label="译文" aria-live="polite">
              <h3>译文</h3>
              {#if translation.phase === "error"}
                <p class="translation-message error">{translation.error}</p>
              {:else if translation.phase === "cancelled" && !translation.translatedText}
                <p class="translation-message">翻译已取消。</p>
              {:else if translation.translatedText}
                <pre>{translation.translatedText}</pre>
              {:else if translation.phase === "streaming"}
                <p class="translation-message">正在翻译…</p>
              {:else}
                <p class="translation-message">准备翻译</p>
              {/if}
            </section>
          </div>

          <div class="translation-footer">
            {#if translation.phase === "streaming"}
              <button class="outline" type="button" on:click={cancelTranslationRun}>取消翻译</button>
            {:else}
              <button class="outline" type="button" on:click={runTranslation}>
                {translation.phase === "completed" ? "重新翻译" : "重试"}
              </button>
            {/if}
            {#if translation.phase === "completed"}
              <button class="outline" type="button" on:click={copyTranslation}>复制译文</button>
              <button class="primary small" type="button" on:click={useTranslationAsCurrentResult}>作为当前结果</button>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    {#if markdownPreview.phase !== "closed"}
      <div class="markdown-layer" role="presentation">
        <div class="markdown-dialog" role="dialog" aria-modal="true" aria-label="Markdown 预览">
          <div class="markdown-head">
            <h2>Markdown 预览</h2>
            <button
              class="icon-button"
              aria-label="关闭 Markdown 预览"
              bind:this={markdownPreviewCloseButton}
              on:click={() => closeMarkdownPreviewView(true)}
            >×</button>
          </div>
          <div class="markdown-toolbar">
            <div class="markdown-segments" role="group" aria-label="预览方式">
              {#each markdownPreviewModes as item}
                <button
                  type="button"
                  class:active={markdownPreview.mode === item.id}
                  aria-pressed={markdownPreview.mode === item.id}
                  on:click={() => markdownPreview = selectMarkdownPreviewMode(markdownPreview, item.id)}
                >{item.label}</button>
              {/each}
            </div>
            <button class="outline" type="button" on:click={() => writeClipboardValue(markdownPreview.sourceText, "✓ 源码已复制")}>复制源码</button>
          </div>
          <div class:source-only={markdownPreview.mode === "source"} class:preview-only={markdownPreview.mode === "preview"} class="markdown-content">
            <section class="markdown-source" aria-label="Markdown 源码">
              <h3>源码</h3>
              <pre>{markdownPreview.sourceText}</pre>
            </section>
            <section class="markdown-rendered" aria-label="渲染预览" aria-live="polite">
              <h3>预览</h3>
              {#if markdownPreview.phase === "loading"}
                <p class="markdown-message">正在渲染…</p>
              {:else if markdownPreview.phase === "error"}
                <p class="markdown-message error">{markdownPreview.error}</p>
              {:else}
                <article>{@html markdownPreview.html}</article>
              {/if}
            </section>
          </div>
          <div class="markdown-footer">
            {#if markdownPreview.phase === "error"}
              <button class="outline" type="button" on:click={runMarkdownPreview}>重试</button>
            {/if}
            <button class="primary small" type="button" on:click={() => closeMarkdownPreviewView(true)}>关闭</button>
          </div>
        </div>
      </div>
    {/if}

    {#if state.overlay === "clipboard_confirm"}
      <div class="modal-layer" role="presentation">
        <section class="clipboard-modal" aria-label="替换剪贴板确认">
          <h2>替换当前剪贴板内容？</h2>
          <p>原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。</p>
          {#if clipboardNotice}
            <p class="clipboard-feedback" aria-live="polite">{clipboardNotice}</p>
          {/if}
          <div>
            <button class="outline" on:click={closeOverlay}>取消</button>
            <button class="primary small" on:click={confirmReplaceClipboard}>确认替换</button>
          </div>
        </section>
      </div>
    {/if}

    {#if state.overlay === "plugin_manager"}
      <div class="settings-layer" role="presentation">
        <section class="plugin-dialog" aria-label="插件">
          <div class="settings-head">
            <div>
              <h2>插件</h2>
              <p>查看当前可用能力及其访问范围。</p>
            </div>
            <button class="icon-button" aria-label="关闭插件" on:click={closeOverlay}>×</button>
          </div>
          <div class="plugin-list">
            <article class="plugin-row">
              <div>
                <strong>MiniMax 模型服务</strong>
                <span>生成与优化文本</span>
              </div>
              <span class="permission-badge">网络访问</span>
            </article>
            <article class="plugin-row">
              <div>
                <strong>内置模板</strong>
                <span>提供场景、风格与语言模板</span>
              </div>
              <span class="permission-badge">本地内容</span>
            </article>
            <article class="plugin-row">
              <div>
                <strong>场景识别</strong>
                <span>根据当前文本选择适合的处理方式</span>
              </div>
              <span class="permission-badge">本地文本</span>
            </article>
          </div>
          <div class="plugin-footer">
            <span>3 项内置能力</span>
            <button class="primary small" type="button" on:click={managePluginSettings}>管理设置</button>
          </div>
        </section>
      </div>
    {/if}

    {#if state.overlay === "settings"}
      <div class="settings-layer" role="presentation">
        <section class="settings-dialog" aria-label="设置">
          <div class="settings-head">
            <div>
              <h2>设置</h2>
              <p>管理模型、默认行为和本地隐私。</p>
            </div>
            <button class="icon-button" aria-label="关闭设置" on:click={cancelSettingsView}>×</button>
          </div>

          <div class="settings-layout">
            <nav class="settings-nav" aria-label="设置分类">
              {#each settingsSections as section}
                <button
                  type="button"
                  class:active={settingsSection === section.id}
                  aria-pressed={settingsSection === section.id}
                  on:click={() => (settingsSection = section.id)}
                >
                  {section.label}
                </button>
              {/each}
            </nav>

            <div class="settings-content">
              {#if settingsSection === "provider"}
                <h3>模型与 Provider</h3>
                <div class="settings-grid">
                  <label>
                    <span>默认 Provider</span>
                    <select bind:value={settingsDraft.default_provider} disabled={settingsBusy}>
                      <option value="minimax">MiniMax</option>
                    </select>
                  </label>
                  <label>
                    <span>默认模型</span>
                    <select bind:value={settingsDraft.default_model} disabled={settingsBusy}>
                      <option value="MiniMax-M2.7-highspeed">M2.7 高速版</option>
                    </select>
                  </label>
                </div>

                <div class="api-key-row">
                  <label>
                    <span>API Key</span>
                    <input
                      type="password"
                      bind:value={secretInput}
                      autocomplete="off"
                      spellcheck="false"
                      disabled={secretBusy}
                      placeholder="输入新的 API Key"
                      aria-describedby="secret-feedback"
                    />
                  </label>
                  <button class="outline" type="button" disabled={secretBusy} on:click={saveSecret}>
                    {secretBusy ? "正在保存" : "保存密钥"}
                  </button>
                  <button
                    class="outline danger"
                    type="button"
                    disabled={secretBusy || !secretStatus.configured}
                    on:click={deleteSecret}
                  >
                    删除密钥
                  </button>
                </div>
                <p id="secret-feedback" class="settings-feedback" aria-live="polite">
                  {secretNotice ?? "密钥只保存在系统安全存储中，输入不会保留。"}
                </p>
                <div class="credential-status" class:configured={secretStatus.configured}>
                  <span class="status-dot" aria-hidden="true"></span>
                  <div>
                    <strong>{secretStatus.configured ? "密钥已保存" : "尚未配置密钥"}</strong>
                    <span>
                      {secretStatus.configured && secretStatus.maskedTail
                        ? `尾号 ${secretStatus.maskedTail}`
                        : "保存后即可使用当前 Provider"}
                    </span>
                  </div>
                </div>
              {:else if settingsSection === "defaults"}
                <h3>默认行为</h3>
                <div class="settings-grid">
                  <div>
                    <span class="field-label">默认模式</span>
                    <div class="segments compact">
                      {#each modes as item}
                        <button type="button" class:active={settingsDraft.default_mode === item.id} on:click={() => (settingsDraft = { ...settingsDraft, default_mode: item.id })}>
                          {item.label}
                        </button>
                      {/each}
                    </div>
                  </div>
                  <div>
                    <span class="field-label">默认风格</span>
                    <div class="segments compact">
                      {#each styles as item}
                        <button type="button" class:active={settingsDraft.default_style === item.id} on:click={() => (settingsDraft = { ...settingsDraft, default_style: item.id })}>
                          {item.label}
                        </button>
                      {/each}
                    </div>
                  </div>
                </div>
                <div class="settings-block">
                  <span class="field-label">场景识别策略</span>
                  <div class="segments compact">
                    {#each scenePolicies as item}
                      <button type="button" class:active={settingsDraft.scene_policy === item.id} on:click={() => (settingsDraft = { ...settingsDraft, scene_policy: item.id })}>
                        {item.label}
                      </button>
                    {/each}
                  </div>
                </div>
                <label class="desktop-hotkey">
                  <span>全局快捷键</span>
                  <input
                    bind:value={settingsDraft.hotkey}
                    disabled={settingsBusy}
                    autocomplete="off"
                    spellcheck="false"
                  />
                  <small class:available={desktopStatus.hotkeyActive}>
                    {desktopStatus.message ?? (desktopStatus.hotkeyActive ? "当前快捷键已启用" : "保存后启用快捷键")}
                  </small>
                </label>
              {:else if settingsSection === "clipboard"}
                <h3>剪贴板</h3>
                <div class="settings-block">
                  <span class="field-label">读取与替换策略</span>
                  <div class="segments compact">
                    {#each clipboardPolicies as item}
                      <button type="button" class:active={settingsDraft.clipboard_policy === item.id} on:click={() => (settingsDraft = { ...settingsDraft, clipboard_policy: item.id })}>
                        {item.label}
                      </button>
                    {/each}
                  </div>
                  <p class="warning-note">自动替换会覆盖当前剪贴板内容，首次使用仍需确认。</p>
                </div>
              {:else if settingsSection === "privacy"}
                <h3>安全与隐私</h3>
                <div class="settings-choice-list">
                  <label class="settings-toggle">
                    <span>
                      <strong>保存历史记录</strong>
                      <small>记录优化结果，便于稍后查看</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={settingsDraft.history_enabled}
                      disabled={settingsBusy}
                      on:change={(event) => setHistoryEnabled(event.currentTarget.checked)}
                    />
                  </label>
                  <label class="settings-toggle">
                    <span>
                      <strong>隐私模式</strong>
                      <small>减少本地内容保留</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={settingsDraft.privacy_mode}
                      disabled={settingsBusy}
                      on:change={(event) => setPrivacyMode(event.currentTarget.checked)}
                    />
                  </label>
                </div>
                <div class="settings-block">
                  <span class="field-label">历史内容处理</span>
                  <div class="segments compact">
                    {#each historyRedactionOptions as item}
                      <button
                        type="button"
                        class:active={settingsDraft.history_redaction === item.id}
                        disabled={settingsBusy}
                        on:click={() => setHistoryRedaction(item.id)}
                      >
                        {item.label}
                      </button>
                    {/each}
                  </div>
                </div>
              {:else}
                <h3>插件</h3>
                <div class="settings-choice-list">
                  {#each settingsPlugins as plugin}
                    <label class="settings-toggle">
                      <span>
                        <strong>{plugin.label}</strong>
                        <small>{plugin.description}</small>
                      </span>
                      <input
                        type="checkbox"
                        checked={settingsDraft.enabled_plugins.includes(plugin.id)}
                        disabled={settingsBusy}
                        on:change={(event) => setPluginEnabled(plugin.id, event.currentTarget.checked)}
                      />
                    </label>
                  {/each}
                </div>
              {/if}
            </div>
          </div>

          <div class="settings-footer">
            <p class="settings-save-notice" aria-live="polite">{settingsNotice ?? ""}</p>
            <button class="outline" type="button" disabled={settingsBusy} on:click={cancelSettingsView}>取消</button>
            <button class="primary small" type="button" disabled={settingsBusy} on:click={saveSettings}>
              {settingsBusy ? "正在保存" : "保存设置"}
            </button>
          </div>
        </section>
      </div>
    {/if}
  </section>
</main>
