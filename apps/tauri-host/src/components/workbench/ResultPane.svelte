<script lang="ts">
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import ThumbsDown from "@lucide/svelte/icons/thumbs-down";
  import { Button } from "@/components/ui/button";
  import ThumbsUp from "@lucide/svelte/icons/thumbs-up";
  import Spinner from "../ui/Spinner.svelte";
  import { translator } from "../../domain/i18nStore";

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

  $: translate = $translator;

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
        <Spinner size={25} thickness={3} />
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
            <Button size="sm" onclick={() => void onRetry?.()}>{translate("重试")}</Button>
          {/if}
          {#if onOpenSettings}
            <Button variant="outline" size="sm" onclick={() => void onOpenSettings?.()}>{translate("打开设置")}</Button>
          {/if}
        </div>
        {#if diagnosticId}
          <Button variant="ghost" size="sm" disabled={!onCopyDiagnosticId}
            title="复制诊断 ID" onclick={() => void onCopyDiagnosticId?.()}>诊断 ID：{diagnosticId}</Button>
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
          <Button size="sm" onclick={() => void onRetry?.()}>{translate("重新生成")}</Button>
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
              <Button variant="link" size="sm" onclick={() => void onRetry?.()}>重试</Button>
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
        <Button
          size="sm"
          disabled={!onCopy}
          onclick={() => void onCopy?.()}
        >{copied ? translate("已复制") : translate("复制结果")}</Button>
        {#if onReplace}
          <Button variant="outline" size="sm" onclick={() => void onReplace?.()}>{translate("替换剪贴板")}</Button>
        {/if}
        {#if onCompare && sourceAvailable}
          <Button variant="outline" size="sm" onclick={() => void onCompare?.()}>{translate("对比原文")}</Button>
        {/if}
        {#if onAdjust}
          <Button variant="outline" size="sm" onclick={() => void onAdjust?.()}>{translate("再调整")}</Button>
        {/if}
      </div>
      <details class="secondary-tools">
        <summary>
          <ChevronRight class="disclosure-caret" size={14} strokeWidth={2} aria-hidden="true" />
          {translate("更多结果工具")}
        </summary>
        <div class="secondary-tools-content">
          {#if onRegenerate}
            <Button variant="outline" size="sm" onclick={() => void onRegenerate?.()}>{translate("重新生成")}</Button>
          {/if}
          {#if onExport}
            <Button variant="outline" size="sm" onclick={() => void onExport?.()}>{translate("导出")}</Button>
          {/if}
          {#if onOpenHistory}
            <Button variant="outline" size="sm" onclick={() => void onOpenHistory?.()}>{translate("历史")}</Button>
          {/if}
          {#if onTranslate}
            <Button variant="outline" size="sm" onclick={() => void onTranslate?.()}>{translate("翻译")}</Button>
          {/if}
          {#if onPreview}
            <Button variant="outline" size="sm" onclick={() => void onPreview?.()}>{translate("预览")}</Button>
          {/if}
          {#if onPositiveFeedback || onNegativeFeedback}
            <span class="feedback-actions" aria-label={translate("结果反馈")}>
              <Button variant="ghost" size="icon-sm" aria-label={translate("结果满意")} title={translate("满意")} disabled={!onPositiveFeedback} onclick={() => void onPositiveFeedback?.()}>
                <ThumbsUp size={15} strokeWidth={2} />
              </Button>
              <Button variant="ghost" size="icon-sm" aria-label={translate("结果不满意")} title={translate("不满意")} disabled={!onNegativeFeedback} onclick={() => void onNegativeFeedback?.()}>
                <ThumbsDown size={15} strokeWidth={2} />
              </Button>
            </span>
          {/if}
          {#if onRate}
            <span class="rating-actions" aria-label={translate("结果评分")}>
              {#each [1, 2, 3, 4, 5] as score}
                <Button variant="ghost" size="icon-sm" aria-label={translate("评分 {score}", { score })} aria-pressed={rating === score} disabled={!ratingEnabled} onclick={() => void onRate?.(score)}>{score}</Button>
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
    padding: 8px 12px;
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
    gap: 8px;
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
    font-weight: 600;
    line-height: var(--leading-body);
  }

  .scene-badge {
    max-width: 190px;
    padding: 2px 6px;
    overflow: hidden;
    color: var(--accent-strong, #0a84ff);
    background: var(--accent-soft, #eef1ff);
    border-radius: var(--radius-sm);
    font-size: var(--font-badge);
    font-weight: 600;
    line-height: var(--leading-badge);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .elapsed {
    flex: 0 0 auto;
    color: var(--muted, #697386);
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
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
    overflow: auto;
    text-align: center;
  }

  .center-state h3 {
    color: var(--text);
  }

  .center-state p {
    margin-top: 4px;
    overflow-wrap: anywhere;
  }

  .center-state .message {
    color: var(--text, #202535);
  }

  .state-mark,
  .error-mark,
  .cancelled-mark {
    display: grid;
    width: 40px;
    height: 40px;
    flex: 0 0 40px;
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
    border-radius: 4px;
  }

  .state-mark::after {
    transform: rotate(90deg);
  }

  .error-mark {
    color: var(--danger, #dc2626);
    background: var(--danger-soft, #fff8f8);
    border: 1px solid var(--danger-line, #f4caca);
    font-size: var(--font-title);
    font-weight: 700;
    line-height: var(--leading-none);
  }

  .cancelled-mark {
    background: color-mix(in srgb, var(--muted, #697386) 9%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
  }

  .cancelled-mark::before {
    width: 12px;
    height: 12px;
    content: "";
    background: var(--muted, #697386);
    border-radius: 4px;
  }

  .state-actions {
    justify-content: center;
    flex-wrap: wrap;
    gap: 8px;
  }

  .secondary-tools-content {
    display: none;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    padding-top: 8px;
  }

  .secondary-tools[open] .secondary-tools-content {
    display: flex;
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
    padding: 12px 16px;
    overflow: auto;
    color: var(--text, #202535);
    font: inherit;
    font-size: var(--font-body);
    line-height: var(--leading-prose);
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
    gap: 8px;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
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

  .result-footer {
    display: flex;
    min-width: 0;
    flex: 0 0 auto;
    flex-direction: column;
    border-top: 1px solid var(--line, #e1e6ee);
  }


  .rating-actions {
    display: inline-flex;
    gap: 2px;
  }

  .feedback-actions {
    display: inline-flex;
    gap: 4px;
  }


  .result-meta {
    min-height: 28px;
    justify-content: space-between;
    gap: 10px;
    padding: 4px 12px;
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--surface, #fff) 76%, var(--page, #edf1f6));
    border-top: 1px solid color-mix(in srgb, var(--line, #e1e6ee) 72%, transparent);
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
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
      min-height: 72px;
      align-items: stretch;
      flex-direction: column;
      gap: 4px;
    }

    .result-meta {
      align-items: flex-start;
      flex-direction: column;
      gap: 4px;
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
      min-height: 88px;
    }

    .center-state {
      gap: 6px;
      padding: 12px;
    }

    .result-meta {
      min-height: 24px;
      padding-block: 4px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }

    .stream-caret {
      animation: none;
    }
  }
</style>
