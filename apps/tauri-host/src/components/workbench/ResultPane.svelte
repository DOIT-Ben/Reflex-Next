<script lang="ts">
  import ThumbsDown from "@lucide/svelte/icons/thumbs-down";
  import ThumbsUp from "@lucide/svelte/icons/thumbs-up";

  import type {
    ResultMetaItem,
    WorkbenchActionHandler,
    WorkbenchPhase,
    WorkbenchRatingHandler
  } from "./types";

  export let phase: WorkbenchPhase = "empty";
  export let output = "";
  export let statusMessage = "正在连接模型服务…";
  export let errorMessage = "生成失败，请稍后重试。";
  export let errorRecoverable = true;
  export let errorAction: string | null = null;
  export let inputPreserved = true;
  export let diagnosticId: string | null = null;
  export let sceneLabel: string | null = null;
  export let sceneConfidence: number | null = null;
  export let elapsedMs: number | null = null;
  export let sourceAvailable = false;
  export let historyStatus = "";
  export let meta: ReadonlyArray<ResultMetaItem> = [];
  export let copied = false;
  export let rating: number | null = null;
  export let ratingEnabled = false;
  export let onCopy: WorkbenchActionHandler | undefined = undefined;
  export let onReplace: WorkbenchActionHandler | undefined = undefined;
  export let onAdjust: WorkbenchActionHandler | undefined = undefined;
  export let onRegenerate: WorkbenchActionHandler | undefined = undefined;
  export let onExport: WorkbenchActionHandler | undefined = undefined;
  export let onOpenHistory: WorkbenchActionHandler | undefined = undefined;
  export let onRate: WorkbenchRatingHandler | undefined = undefined;
  export let onTranslate: WorkbenchActionHandler | undefined = undefined;
  export let onPreview: WorkbenchActionHandler | undefined = undefined;
  export let onCompare: WorkbenchActionHandler | undefined = undefined;
  export let onRetry: WorkbenchActionHandler | undefined = undefined;
  export let onOpenSettings: WorkbenchActionHandler | undefined = undefined;
  export let onCopyDiagnosticId: WorkbenchActionHandler | undefined = undefined;
  export let onPositiveFeedback: WorkbenchActionHandler | undefined = undefined;
  export let onNegativeFeedback: WorkbenchActionHandler | undefined = undefined;
  export let translate: (source: string, values?: Record<string, string | number>) => string = (source) => source;

  $: hasOutput = output.length > 0;
  $: errorGuidance = !inputPreserved
      ? translate("请重新输入文本后再试。")
    : errorAction === "settings"
      ? translate("你的输入已保留，请调整设置后再试。")
      : errorAction === "edit"
        ? translate("你的输入已保留，请修改内容后再试。")
        : errorAction === "restart"
          ? translate("你的输入已保留，请重新打开应用后再试。")
          : translate("你的输入已保留，可稍后重试。");
  $: showOutput = hasOutput && (phase === "running" || phase === "completed" || phase === "cancelled" || phase === "error");
  $: elapsedLabel = elapsedMs === null ? "" : elapsedMs < 1000 ? `${Math.max(0, Math.round(elapsedMs))} ms` : `${(elapsedMs / 1000).toFixed(2)} s`;
  $: confidenceLabel = sceneConfidence === null ? "" : `${Math.round(Math.max(0, Math.min(1, sceneConfidence)) * 100)}%`;
</script>

<section class="result-pane" aria-labelledby="workbench-result-title">
  <header class="pane-header">
    <div class="title-group">
      <h2 id="workbench-result-title">{translate("结果")}</h2>
      {#if sceneLabel}
        <span class="scene-badge" title={translate("识别场景")}>
          {sceneLabel}{confidenceLabel ? ` · ${confidenceLabel}` : ""}
        </span>
      {/if}
      {#if elapsedLabel && phase === "completed"}
        <span class="elapsed">{elapsedLabel}</span>
      {/if}
    </div>
  </header>

  <div class="result-body">
    {#if phase === "empty"}
      <div class="center-state empty-state">
        <span class="state-mark" aria-hidden="true"></span>
        <div>
          <h3>{translate("还没有结果")}</h3>
          <p>{translate("输入文本并开始优化，结果会在这里流式显示。")}</p>
        </div>
      </div>
    {:else if phase === "running" && !hasOutput}
      <div class="center-state" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <h3>{statusMessage}</h3>
          <p>{translate("正在与模型服务通信，请稍候。")}</p>
        </div>
      </div>
    {:else if phase === "error" && !hasOutput}
      <div class="center-state error-state" role="alert">
        <span class="error-mark" aria-hidden="true">!</span>
        <div>
          <h3>{translate("生成失败")}</h3>
          <p class="message">{errorMessage}</p>
          <p>{errorGuidance}</p>
        </div>
        <div class="state-actions">
          {#if errorRecoverable && onRetry}
            <button class="primary-action" type="button" on:click={() => void onRetry?.()}>{translate("重试")}</button>
          {/if}
          {#if onOpenSettings}
            <button class="secondary-action" type="button" on:click={() => void onOpenSettings?.()}>{translate("打开设置")}</button>
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
          <h3>{translate("已取消生成")}</h3>
          <p>{translate("本次没有生成内容，可以重新运行。")}</p>
        </div>
        {#if onRetry}
          <button class="primary-action" type="button" on:click={() => void onRetry?.()}>{translate("重新生成")}</button>
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
          <h3>{translate("没有可显示的结果")}</h3>
          <p>{translate("请重新运行，或调整生成方案后再试。")}</p>
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
        >{copied ? translate("已复制") : translate("复制结果")}</button>
        {#if onReplace}
          <button class="secondary-result-action" type="button" on:click={() => void onReplace?.()}>{translate("替换剪贴板")}</button>
        {/if}
        {#if onCompare && sourceAvailable}
          <button class="secondary-result-action" type="button" on:click={() => void onCompare?.()}>{translate("对比原文")}</button>
        {/if}
        {#if onAdjust}
          <button class="secondary-result-action" type="button" on:click={() => void onAdjust?.()}>{translate("再调整")}</button>
        {/if}
      </div>
      <details class="secondary-tools">
        <summary>{translate("更多结果工具")}</summary>
        <div class="secondary-tools-content">
          {#if onRegenerate}
            <button class="secondary-result-action" type="button" on:click={() => void onRegenerate?.()}>{translate("重新生成")}</button>
          {/if}
          {#if onExport}
            <button class="secondary-result-action" type="button" on:click={() => void onExport?.()}>{translate("导出")}</button>
          {/if}
          {#if onOpenHistory}
            <button class="secondary-result-action" type="button" on:click={() => void onOpenHistory?.()}>{translate("历史")}</button>
          {/if}
          {#if onTranslate}
            <button class="secondary-result-action" type="button" on:click={() => void onTranslate?.()}>{translate("翻译")}</button>
          {/if}
          {#if onPreview}
            <button class="secondary-result-action" type="button" on:click={() => void onPreview?.()}>{translate("预览")}</button>
          {/if}
          {#if onPositiveFeedback || onNegativeFeedback}
            <span class="feedback-actions" aria-label={translate("结果反馈")}>
              <button type="button" aria-label={translate("结果满意")} title={translate("满意")} disabled={!onPositiveFeedback} on:click={() => void onPositiveFeedback?.()}>
                <ThumbsUp size={15} strokeWidth={2} />
              </button>
              <button type="button" aria-label={translate("结果不满意")} title={translate("不满意")} disabled={!onNegativeFeedback} on:click={() => void onNegativeFeedback?.()}>
                <ThumbsDown size={15} strokeWidth={2} />
              </button>
            </span>
          {/if}
          {#if onRate}
            <span class="rating-actions" aria-label={translate("结果评分")}>
              {#each [1, 2, 3, 4, 5] as score}
                <button
                  type="button"
                  aria-label={translate("评分 {score}", { score })}
                  aria-pressed={rating === score}
                  disabled={!ratingEnabled}
                  on:click={() => void onRate?.(score)}
                >{score}</button>
              {/each}
            </span>
          {/if}
        </div>
      </details>
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
    font-size: var(--font-body);
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
    font-size: var(--font-meta);
    font-weight: 620;
    line-height: 1.4;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .elapsed {
    flex: 0 0 auto;
    color: var(--muted, #697386);
    font-size: var(--font-meta);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
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
    font-size: var(--font-body);
    font-weight: 650;
    line-height: 1.45;
  }

  .center-state p {
    max-width: 360px;
    margin-top: 4px;
    color: var(--muted, #697386);
    font-size: var(--font-meta);
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
    font-size: var(--font-title);
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
    font-size: var(--font-meta);
    font-weight: 620;
  }

  .primary-action,
  .copy-button {
    color: #fff;
    background: var(--accent, #5065c7);
    border: 1px solid var(--accent, #5065c7);
  }

  .secondary-tools {
    min-width: 0;
    padding: 0 11px 7px;
  }

  .secondary-tools summary {
    width: fit-content;
    color: var(--muted, #697386);
    font-size: var(--font-meta);
    cursor: pointer;
  }

  .secondary-tools-content {
    display: none;
    align-items: center;
    flex-wrap: wrap;
    gap: 5px;
    padding-top: 7px;
  }

  .secondary-tools[open] .secondary-tools-content {
    display: flex;
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
    font-size: var(--font-meta);
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
    font-size: var(--font-body);
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
    font-size: var(--font-meta);
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
    flex-wrap: wrap;
    gap: 5px;
    padding: 6px 11px;
  }

  .copy-button {
    min-width: 84px;
  }

  .secondary-result-action,
  .rating-actions button,
  .feedback-actions button {
    min-height: 31px;
    padding: 0 9px;
    color: var(--muted, #697386);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 7px;
    font-size: var(--font-meta);
    font-weight: 600;
  }

  .secondary-result-action:hover:not(:disabled),
  .rating-actions button:hover:not(:disabled),
  .feedback-actions button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: var(--accent-soft, #eef1ff);
    border-color: var(--line-strong, #cbd4e2);
  }

  .rating-actions {
    display: inline-flex;
    gap: 2px;
  }

  .feedback-actions {
    display: inline-flex;
    gap: 3px;
  }

  .feedback-actions button {
    display: grid;
    width: 31px;
    height: 31px;
    place-items: center;
    padding: 0;
  }

  .rating-actions button {
    min-width: 27px;
    padding: 0 5px;
  }

  .rating-actions button[aria-pressed="true"] {
    color: #fff;
    background: var(--accent, #5065c7);
    border-color: var(--accent, #5065c7);
  }

  .result-meta {
    min-height: 29px;
    justify-content: space-between;
    gap: 10px;
    padding: 5px 11px;
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--surface, #fff) 76%, var(--page, #edf1f6));
    border-top: 1px solid color-mix(in srgb, var(--line, #e1e6ee) 72%, transparent);
    font-size: var(--font-meta);
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
