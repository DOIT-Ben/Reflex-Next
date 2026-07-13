<script lang="ts">
  import type {
    ResultMetaItem,
    WorkbenchActionHandler,
    WorkbenchPhase
  } from "./types";

  export let phase: WorkbenchPhase = "empty";
  export let output = "";
  export let statusMessage = "正在连接模型服务…";
  export let errorMessage = "生成失败，请稍后重试。";
  export let errorRecoverable = true;
  export let inputPreserved = true;
  export let diagnosticId: string | null = null;
  export let sceneLabel: string | null = null;
  export let sceneConfidence: number | null = null;
  export let elapsedMs: number | null = null;
  export let sourceAvailable = false;
  export let historyStatus = "";
  export let meta: ReadonlyArray<ResultMetaItem> = [];
  export let copied = false;
  export let onCopy: WorkbenchActionHandler | undefined = undefined;
  export let onTranslate: WorkbenchActionHandler | undefined = undefined;
  export let onPreview: WorkbenchActionHandler | undefined = undefined;
  export let onCompare: WorkbenchActionHandler | undefined = undefined;
  export let onRetry: WorkbenchActionHandler | undefined = undefined;
  export let onOpenSettings: WorkbenchActionHandler | undefined = undefined;
  export let onCopyDiagnosticId: WorkbenchActionHandler | undefined = undefined;

  $: hasOutput = output.length > 0;
  $: showOutput = hasOutput && (phase === "running" || phase === "completed" || phase === "cancelled" || phase === "error");
  $: elapsedLabel = elapsedMs === null ? "" : elapsedMs < 1000 ? `${Math.max(0, Math.round(elapsedMs))} ms` : `${(elapsedMs / 1000).toFixed(2)} s`;
  $: confidenceLabel = sceneConfidence === null ? "" : `${Math.round(Math.max(0, Math.min(1, sceneConfidence)) * 100)}%`;
</script>

<section class="result-pane" aria-labelledby="workbench-result-title">
  <header class="pane-header">
    <div class="title-group">
      <h2 id="workbench-result-title">结果</h2>
      {#if sceneLabel}
        <span class="scene-badge" title="识别场景">
          {sceneLabel}{confidenceLabel ? ` · ${confidenceLabel}` : ""}
        </span>
      {/if}
      {#if elapsedLabel && phase === "completed"}
        <span class="elapsed">{elapsedLabel}</span>
      {/if}
    </div>
    <div class="header-actions" aria-label="结果操作">
      <button
        type="button"
        disabled={!hasOutput || !onTranslate}
        aria-label="翻译结果"
        title="翻译"
        on:click={() => void onTranslate?.()}
      >翻译</button>
      <button
        type="button"
        disabled={!hasOutput || !onPreview}
        aria-label="Markdown 预览"
        title="Markdown 预览"
        on:click={() => void onPreview?.()}
      >预览</button>
      <button
        type="button"
        disabled={!hasOutput || !sourceAvailable || !onCompare}
        aria-label="对比原文"
        title="对比原文"
        on:click={() => void onCompare?.()}
      >对比</button>
    </div>
  </header>

  <div class="result-body">
    {#if phase === "empty"}
      <div class="center-state empty-state">
        <span class="state-mark" aria-hidden="true"></span>
        <div>
          <h3>还没有结果</h3>
          <p>输入文本并开始优化，结果会在这里流式显示。</p>
        </div>
      </div>
    {:else if phase === "running" && !hasOutput}
      <div class="center-state" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <h3>{statusMessage}</h3>
          <p>正在与模型服务通信，请稍候。</p>
        </div>
      </div>
    {:else if phase === "error" && !hasOutput}
      <div class="center-state error-state" role="alert">
        <span class="error-mark" aria-hidden="true">!</span>
        <div>
          <h3>生成失败</h3>
          <p class="message">{errorMessage}</p>
          <p>{inputPreserved ? "你的输入已保留，可重试或调整方案。" : "请重新输入文本后再试。"}</p>
        </div>
        <div class="state-actions">
          {#if errorRecoverable && onRetry}
            <button class="primary-action" type="button" on:click={() => void onRetry?.()}>重试</button>
          {/if}
          {#if onOpenSettings}
            <button class="secondary-action" type="button" on:click={() => void onOpenSettings?.()}>打开设置</button>
          {/if}
        </div>
        {#if diagnosticId}
          <button
            class="diagnostic-action"
            type="button"
            disabled={!onCopyDiagnosticId}
            title="复制诊断 ID"
            on:click={() => void onCopyDiagnosticId?.()}
          >诊断 ID：{diagnosticId}</button>
        {/if}
      </div>
    {:else if phase === "cancelled" && !hasOutput}
      <div class="center-state cancelled-state" role="status">
        <span class="cancelled-mark" aria-hidden="true"></span>
        <div>
          <h3>已取消生成</h3>
          <p>本次没有生成内容，可以重新运行。</p>
        </div>
        {#if onRetry}
          <button class="primary-action" type="button" on:click={() => void onRetry?.()}>重新生成</button>
        {/if}
      </div>
    {:else if showOutput}
      <div class="output-layout">
        <pre aria-live={phase === "running" ? "polite" : "off"}>{output}{#if phase === "running"}<span class="stream-caret" aria-hidden="true"></span>{/if}</pre>
        {#if phase === "cancelled"}
          <p class="inline-notice cancelled-notice" role="status">已取消生成，已输出内容已保留。</p>
        {:else if phase === "error"}
          <div class="inline-notice error-notice" role="alert">
            <strong>生成中断</strong>
            <span>{errorMessage} 已输出内容已保留。</span>
            {#if errorRecoverable && onRetry}
              <button type="button" on:click={() => void onRetry?.()}>重试</button>
            {/if}
          </div>
        {/if}
      </div>
    {:else}
      <div class="center-state empty-state">
        <span class="state-mark" aria-hidden="true"></span>
        <div>
          <h3>没有可显示的结果</h3>
          <p>请重新运行，或调整生成方案后再试。</p>
        </div>
      </div>
    {/if}
  </div>

  {#if hasOutput}
    <footer class="result-footer">
      <div class="primary-actions">
        <button
          class="copy-button"
          type="button"
          disabled={!onCopy}
          on:click={() => void onCopy?.()}
        >{copied ? "已复制" : "复制结果"}</button>
      </div>
      {#if meta.length || historyStatus}
        <div class="result-meta">
          <span class="meta-list">
            {#each meta as item, index (item.id)}
              <span title={`${item.label}：${item.value}`}>{item.value}</span>{#if index < meta.length - 1}<span aria-hidden="true">·</span>{/if}
            {/each}
          </span>
          {#if historyStatus}<span class="history-status">{historyStatus}</span>{/if}
        </div>
      {/if}
    </footer>
  {/if}
</section>

<style>
  .result-pane {
    container-type: inline-size;
    display: flex;
    min-width: 0;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    overflow: hidden;
    color: var(--text, #202535);
    background: var(--surface, #fff);
  }

  .pane-header {
    display: flex;
    min-width: 0;
    min-height: 44px;
    flex: 0 0 auto;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 7px 10px 7px 12px;
    border-bottom: 1px solid var(--line, #e1e6ee);
  }

  .title-group,
  .header-actions,
  .state-actions,
  .result-meta,
  .meta-list {
    display: flex;
    min-width: 0;
    align-items: center;
  }

  .title-group {
    flex: 1 1 auto;
    gap: 7px;
    overflow: hidden;
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    flex: 0 0 auto;
    font-size: 13px;
    font-weight: 650;
    line-height: 1.4;
  }

  .scene-badge {
    max-width: 190px;
    padding: 3px 7px;
    overflow: hidden;
    color: var(--accent, #5065c7);
    background: var(--accent-soft, #eef1ff);
    border-radius: 999px;
    font-size: 10px;
    font-weight: 620;
    line-height: 1.4;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .elapsed {
    flex: 0 0 auto;
    color: var(--muted, #697386);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .header-actions {
    flex: 0 0 auto;
    gap: 2px;
  }

  button {
    font: inherit;
    transition: color 140ms ease, background 140ms ease, border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
  }

  button:focus-visible {
    outline: 2px solid var(--accent, #5065c7);
    outline-offset: 2px;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.4;
  }

  .header-actions button {
    min-width: 40px;
    height: 30px;
    padding: 0 8px;
    color: var(--muted, #697386);
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    font-size: 11px;
    font-weight: 560;
  }

  .header-actions button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: var(--accent-soft, #eef1ff);
    border-color: var(--line, #e1e6ee);
    transform: translateY(-1px);
  }

  .result-body {
    position: relative;
    display: flex;
    min-width: 0;
    min-height: 120px;
    flex: 1 1 auto;
    overflow: hidden;
  }

  .center-state {
    display: flex;
    width: 100%;
    min-width: 0;
    min-height: 120px;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 22px;
    overflow: auto;
    text-align: center;
  }

  .center-state h3 {
    font-size: 13px;
    font-weight: 650;
    line-height: 1.45;
  }

  .center-state p {
    max-width: 360px;
    margin-top: 4px;
    color: var(--muted, #697386);
    font-size: 11px;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }

  .center-state .message {
    color: var(--text, #202535);
  }

  .state-mark,
  .error-mark,
  .cancelled-mark {
    display: grid;
    width: 42px;
    height: 42px;
    flex: 0 0 42px;
    place-items: center;
    border-radius: 50%;
  }

  .state-mark {
    position: relative;
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 72%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
  }

  .state-mark::before,
  .state-mark::after {
    position: absolute;
    width: 14px;
    height: 2px;
    content: "";
    background: var(--accent, #5065c7);
    border-radius: 2px;
  }

  .state-mark::after {
    transform: rotate(90deg);
  }

  .error-mark {
    color: var(--danger, #dc2626);
    background: var(--danger-soft, #fff8f8);
    border: 1px solid var(--danger-line, #f4caca);
    font-size: 18px;
    font-weight: 760;
  }

  .cancelled-mark {
    background: color-mix(in srgb, var(--muted, #697386) 9%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
  }

  .cancelled-mark::before {
    width: 13px;
    height: 13px;
    content: "";
    background: var(--muted, #697386);
    border-radius: 3px;
  }

  .spinner {
    width: 25px;
    height: 25px;
    flex: 0 0 25px;
    border: 3px solid color-mix(in srgb, var(--accent, #5065c7) 18%, transparent);
    border-top-color: var(--accent, #5065c7);
    border-radius: 50%;
    animation: spin 850ms linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .state-actions {
    justify-content: center;
    flex-wrap: wrap;
    gap: 7px;
  }

  .primary-action,
  .secondary-action,
  .diagnostic-action,
  .copy-button,
  .inline-notice button {
    min-height: 31px;
    padding: 0 11px;
    border-radius: 7px;
    font-size: 11px;
    font-weight: 620;
  }

  .primary-action,
  .copy-button {
    color: #fff;
    background: var(--accent, #5065c7);
    border: 1px solid var(--accent, #5065c7);
  }

  .primary-action:hover:not(:disabled),
  .copy-button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #5065c7) 88%, #000);
    box-shadow: 0 4px 12px color-mix(in srgb, var(--accent, #5065c7) 18%, transparent);
    transform: translateY(-1px);
  }

  .secondary-action {
    color: var(--text, #202535);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
  }

  .secondary-action:hover:not(:disabled) {
    background: var(--accent-soft, #eef1ff);
    border-color: var(--line-strong, #cbd4e2);
  }

  .diagnostic-action {
    display: block;
    max-width: min(100%, 360px);
    min-height: 0;
    padding: 2px 4px;
    overflow: hidden;
    color: var(--muted, #697386);
    background: transparent;
    border: 0;
    font-size: 10px;
    font-weight: 500;
    overflow-wrap: anywhere;
    text-decoration: underline;
    text-decoration-color: transparent;
    text-underline-offset: 3px;
    white-space: normal;
  }

  .diagnostic-action:hover:not(:disabled) {
    color: var(--text, #202535);
    text-decoration-color: currentColor;
  }

  .output-layout {
    display: flex;
    width: 100%;
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    overflow: hidden;
  }

  pre {
    min-width: 0;
    min-height: 0;
    margin: 0;
    flex: 1 1 auto;
    padding: 13px 15px;
    overflow: auto;
    color: var(--text, #202535);
    font: inherit;
    font-size: 13px;
    line-height: 1.72;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .stream-caret {
    display: inline-block;
    width: 2px;
    height: 1em;
    margin-left: 2px;
    vertical-align: -0.12em;
    background: var(--accent, #5065c7);
    animation: blink 900ms steps(1) infinite;
  }

  @keyframes blink {
    50% {
      opacity: 0;
    }
  }

  .inline-notice {
    display: flex;
    min-width: 0;
    margin: 0 12px 10px;
    flex: 0 0 auto;
    align-items: center;
    gap: 7px;
    padding: 8px 10px;
    border-radius: 7px;
    font-size: 11px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }

  .cancelled-notice {
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--muted, #697386) 8%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
  }

  .error-notice {
    color: var(--danger, #dc2626);
    background: var(--danger-soft, #fff8f8);
    border: 1px solid var(--danger-line, #f4caca);
  }

  .error-notice span {
    min-width: 0;
    flex: 1 1 auto;
  }

  .error-notice button {
    flex: 0 0 auto;
    color: var(--danger, #dc2626);
    background: var(--surface, #fff);
    border: 1px solid var(--danger-line, #f4caca);
  }

  .result-footer {
    display: flex;
    min-width: 0;
    flex: 0 0 auto;
    flex-direction: column;
    border-top: 1px solid var(--line, #e1e6ee);
  }

  .primary-actions {
    display: flex;
    min-height: 44px;
    align-items: center;
    padding: 6px 11px;
  }

  .copy-button {
    min-width: 84px;
  }

  .result-meta {
    min-height: 29px;
    justify-content: space-between;
    gap: 10px;
    padding: 5px 11px;
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--surface, #fff) 76%, var(--page, #edf1f6));
    border-top: 1px solid color-mix(in srgb, var(--line, #e1e6ee) 72%, transparent);
    font-size: 10px;
    line-height: 1.4;
  }

  .meta-list {
    flex: 1 1 auto;
    gap: 4px;
    overflow: hidden;
  }

  .meta-list span:not([aria-hidden="true"]) {
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .history-status {
    flex: 0 0 auto;
    max-width: 46%;
    overflow: hidden;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @container (max-width: 420px) {
    .pane-header {
      min-height: 76px;
      align-items: stretch;
      flex-direction: column;
      gap: 4px;
    }

    .header-actions {
      justify-content: flex-start;
    }

    .result-meta {
      align-items: flex-start;
      flex-direction: column;
      gap: 3px;
    }

    .history-status {
      max-width: 100%;
      text-align: left;
    }

    .inline-notice {
      align-items: flex-start;
      flex-wrap: wrap;
    }
  }

  @media (max-height: 520px) {
    .result-body,
    .center-state {
      min-height: 90px;
    }

    .center-state {
      gap: 6px;
      padding: 12px;
    }

    .primary-actions {
      min-height: 36px;
      padding-block: 3px;
    }

    .result-meta {
      min-height: 25px;
      padding-block: 3px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }

    .spinner {
      animation-duration: 1.8s;
    }

    .stream-caret {
      animation: none;
    }
  }
</style>
