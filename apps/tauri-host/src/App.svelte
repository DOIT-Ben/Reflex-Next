<script lang="ts">
  import { onMount } from "svelte";
  import { createDefaultCoreBridge, DemoCoreBridge } from "./domain/coreBridge";
  import {
    applyAdjustDraft,
    applyClipboardError,
    applyClipboardText,
    applyCoreEnvelope,
    applyPersistedConfig,
    applySceneSelection,
    applySettingsDraft,
    cancelGeneration,
    cancelAdjust,
    cancelSettings,
    createHostState,
    createRequestDraft,
    openAdjust,
    openSettings,
    providerDisplayName,
    resolveHostShortcut,
    retryAfterError,
    startGeneration,
    updateInput,
    type HostState,
    type HostSettingsDraft,
    type RequestSettings
  } from "./domain/hostState";
  import {
    createClipboardReader,
    readClipboardText,
    type ClipboardReader
  } from "./domain/clipboardBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import {
    createSettingsApi,
    type AppConfig,
    type SecretStatus,
    type SettingsApi
  } from "./domain/settingsApi";
  import type { CoreBridge, TauriHostApi } from "./domain/coreBridge";
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
  const settingsSections = [
    { id: "provider", label: "模型与 Provider" },
    { id: "defaults", label: "默认行为" },
    { id: "clipboard", label: "剪贴板" },
    { id: "privacy", label: "安全与隐私" }
  ] as const;
  type SettingsSection = (typeof settingsSections)[number]["id"];

  let coreBridge: CoreBridge = new DemoCoreBridge();
  let hostApi: TauriHostApi | null = null;
  let settingsApi: SettingsApi | null = null;
  let clipboardReader: ClipboardReader = createClipboardReader();
  let state: HostState = updateInput(
    createHostState(),
    "帮我把这段产品说明改得更清晰，并保留专业语气。"
  );
  let draft: RequestSettings = { ...state.requestDraft };
  let settingsDraft: HostSettingsDraft = {
    default_provider: state.requestDraft.provider,
    default_model: state.requestDraft.model,
    default_mode: state.requestDraft.mode,
    default_style: state.requestDraft.style,
    scene_policy: state.requestDraft.scene_policy,
    clipboard_policy: "manual"
  };
  let activeRun: AbortController | null = null;
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
  let toastVisible = false;
  let toastText = "✓ 已复制到剪贴板";

  onMount(() => {
    void createTauriHostApi().then((host) => {
      if (host) {
        hostApi = host;
        settingsApi = createSettingsApi(host);
        clipboardReader = createClipboardReader(host);
        void hydrateSettings();
        void createDefaultCoreBridge(host).then((bridge) => {
          coreBridge = bridge;
        });
      }
    });
  });

  $: summary = [
    modeLabel(state.requestDraft.mode),
    styleLabel(state.requestDraft.style),
    sceneLabel(state.requestDraft.scene),
    providerDisplayName(state.requestDraft.provider)
  ].join(" · ");
  $: inputCount = `${state.inputText.trim().length} 字`;
  $: canGenerate = state.canGenerate && !isGenerating(state.phase);

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

  function beginAdjust() {
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
      const saved = await settingsApi.saveConfig({
        ...persistedConfig,
        provider: settingsDraft.default_provider ?? "minimax",
        model: settingsDraft.default_model ?? "MiniMax-M2.7-highspeed",
        mode: settingsDraft.default_mode,
        style: settingsDraft.default_style,
        scene_policy: settingsDraft.scene_policy,
        clipboard_policy: settingsDraft.clipboard_policy
      });
      persistedConfig = saved;
      settingsDraft = settingsDraftFromConfig(saved);
      state = applySettingsDraft(applyPersistedConfig(state, saved), settingsDraft);
      draft = { ...state.requestDraft };
      showToast("✓ 设置已保存");
    } catch {
      settingsNotice = "设置保存失败，请重试。";
    } finally {
      settingsBusy = false;
    }
  }

  function cancelSettingsView() {
    state = cancelSettings(state);
    settingsDraft = {
      default_provider: state.requestDraft.provider,
      default_model: state.requestDraft.model,
      default_mode: state.requestDraft.mode,
      default_style: state.requestDraft.style,
      scene_policy: state.requestDraft.scene_policy,
      clipboard_policy: settingsDraft.clipboard_policy
    };
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

  function settingsDraftFromConfig(config: AppConfig): HostSettingsDraft {
    return {
      default_provider: config.provider,
      default_model: config.model,
      default_mode: config.mode,
      default_style: config.style,
      scene_policy: config.scene_policy,
      clipboard_policy: config.clipboard_policy
    };
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
    await navigator.clipboard?.writeText(state.output);
    state = { ...state, copied: true };
    toastText = "✓ 已复制到剪贴板";
    toastVisible = true;
    window.setTimeout(() => {
      toastVisible = false;
      state = { ...state, copied: false };
    }, 1400);
  }

  function askReplaceClipboard() {
    if (!state.output) return;
    state = { ...state, overlay: "clipboard_confirm" };
  }

  async function confirmReplaceClipboard() {
    await copyResult();
    state = { ...state, overlay: null };
  }

  async function copyDiagnosticId() {
    if (!state.diagnosticId) return;
    await navigator.clipboard?.writeText(state.diagnosticId);
    toastText = "✓ 诊断 ID 已复制";
    toastVisible = true;
    window.setTimeout(() => {
      toastVisible = false;
    }, 1400);
  }

  function retryRun() {
    state = retryAfterError(state);
    void runOptimization();
  }

  function openSettingsView() {
    beginSettings();
  }

  function closeOverlay() {
    if (state.overlay === "settings") {
      cancelSettingsView();
      return;
    }
    state = { ...state, overlay: null };
  }

  function handleKeydown(event: KeyboardEvent) {
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

  function styleLabel(value: OptimizeStyle): string {
    return styles.find((item) => item.id === value)?.label ?? "平衡";
  }

  function sceneLabel(value: string | null): string {
    return scenes.find((item) => item.id === value)?.label ?? "自动识别";
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
        <p class="subline">{sceneLabel(state.detectedScene ?? state.requestDraft.scene)} · {styleLabel(state.requestDraft.style)} · 约 {state.output.length} 字</p>
        <article class="result-card">
          <pre>{state.output}</pre>
        </article>
        <div class="result-actions">
          <button class="primary small" on:click={copyResult}>复制结果</button>
          <button class="outline" on:click={askReplaceClipboard}>替换剪贴板</button>
          <button class="outline" on:click={runOptimization}>重新生成</button>
          <button class="outline" on:click={beginAdjust}>调整</button>
        </div>
        <p class="recent">最近一次结果</p>
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
          <button on:click={beginAdjust}>调整</button>
        </div>

        <button class="generate-button" disabled={!canGenerate} on:click={runOptimization}>
          优化文本 <span>→</span>
        </button>

        <div class="shortcut-row">
          <span>Esc 关闭</span>
          <span>Ctrl + Enter</span>
        </div>
      </section>
    {/if}

    {#if state.overlay === "clipboard_confirm"}
      <div class="modal-layer" role="presentation">
        <section class="clipboard-modal" aria-label="替换剪贴板确认">
          <h2>替换当前剪贴板内容？</h2>
          <p>原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。</p>
          <div>
            <button class="outline" on:click={closeOverlay}>取消</button>
            <button class="primary small" on:click={confirmReplaceClipboard}>确认替换</button>
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
              {:else}
                <h3>安全与隐私</h3>
                <div class="privacy-row">
                  <span>密钥保存在系统安全存储</span>
                  <span>日志不记录完整输入</span>
                  <span>服务错误会隐藏敏感内容</span>
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
