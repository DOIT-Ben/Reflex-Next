<script lang="ts">
  import { onMount } from "svelte";
  import { createDefaultCoreBridge } from "./domain/coreBridge";
  import {
    applyAdjustDraft,
    applyCoreEnvelope,
    cancelGeneration,
    cancelAdjust,
    createHostState,
    createRequestDraft,
    openAdjust,
    resolveHostShortcut,
    retryAfterError,
    startGeneration,
    updateInput,
    type HostState,
    type RequestSettings
  } from "./domain/hostState";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import type { TauriHostApi } from "./domain/coreBridge";
  import type { OptimizeMode, OptimizeStyle, ScenePolicy } from "./domain/reflexSession";

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
  const scenes = [
    { id: "general", label: "通用" },
    { id: "email", label: "邮件" },
    { id: "report_writing", label: "报告写作" },
    { id: "code_review", label: "代码审查" },
    { id: "doc_translation", label: "文档翻译" }
  ];

  let coreBridge = createDefaultCoreBridge();
  let hostApi: TauriHostApi | null = null;
  let state: HostState = updateInput(
    createHostState(),
    "帮我把这段产品说明改得更清晰，并保留专业语气。"
  );
  let draft: RequestSettings = { ...state.requestDraft };
  let activeRun: AbortController | null = null;
  let toastVisible = false;
  let toastText = "✓ 已复制到剪贴板";

  onMount(() => {
    void createTauriHostApi().then((host) => {
      if (host) {
        hostApi = host;
        coreBridge = createDefaultCoreBridge(host);
      }
    });
  });

  $: summary = [
    modeLabel(state.requestDraft.mode),
    styleLabel(state.requestDraft.style),
    sceneLabel(state.requestDraft.scene),
    state.requestDraft.provider ?? "未配置"
  ].join(" · ");
  $: inputCount = `${state.inputText.trim().length} 字`;
  $: canGenerate = state.canGenerate && !isGenerating(state.phase);

  function setInput(value: string) {
    state = updateInput(state, value);
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

  async function runOptimization() {
    if (!canGenerate) return;
    const requestId = `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = new AbortController();
    activeRun = controller;
    state = startGeneration(state, requestId);

    for await (const event of coreBridge.optimize(createRequestDraft(state), {
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

  function openSettings() {
    void hostApi?.invoke("open_settings").catch(() => undefined);
  }

  function closeOverlay() {
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
</script>

<svelte:window on:keydown={handleKeydown} />

<main class="app-shell" data-phase={state.phase}>
  <section class="window" aria-label="Reflex quick window">
    <header class="top-bar">
      <div class="brand">
        <span class="brand-mark">R</span>
        <strong>Reflex</strong>
      </div>
      <div class="provider-pill"><span></span>{state.requestDraft.provider ?? "未配置"}</div>
      <button class="icon-button" aria-label="设置">⚙</button>
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
            <select bind:value={draft.scene}>
              {#each scenes as scene}
                <option value={scene.id}>{scene.label}</option>
              {/each}
            </select>
          </label>

          <label class="setting-row">
            <span>模型</span>
            <select bind:value={draft.model}>
              <option value="abab6.5">MiniMax / abab6.5</option>
              <option value="local-preview">本地预览 / 预览流</option>
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
          <button class="outline" on:click={openSettings}>打开设置</button>
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
            <button type="button">读取剪贴板</button>
            <span>{inputCount}</span>
          </div>
        </div>

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
  </section>
</main>
