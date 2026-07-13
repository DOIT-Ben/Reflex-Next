<script lang="ts">
  import type {
    ConfigSummaryItem,
    WorkbenchActionHandler,
    WorkbenchPhase
  } from "./types";

  export let items: ReadonlyArray<ConfigSummaryItem> = [];
  export let phase: WorkbenchPhase = "empty";
  export let canRun = false;
  export let statusMessage = "正在生成…";
  export let runLabel = "优化文本";
  export let cancelLabel = "取消生成";
  export let adjustLabel = "调整方案";
  export let onRun: WorkbenchActionHandler | undefined = undefined;
  export let onCancel: WorkbenchActionHandler | undefined = undefined;
  export let onAdjust: WorkbenchActionHandler | undefined = undefined;

  $: running = phase === "running";
</script>

<section class="config-summary" aria-label="本次生成配置">
  <div class="summary-row">
    <div class="summary-items" aria-label="配置摘要">
      {#each items as item (item.id)}
        <span class="summary-chip" title={item.title ?? `${item.label}：${item.value}`}>
          <span class="chip-label">{item.label}</span>
          <strong>{item.value}</strong>
        </span>
      {/each}
    </div>
    {#if onAdjust}
      <button class="adjust-button" type="button" disabled={running} on:click={() => void onAdjust?.()}>
        {adjustLabel}
      </button>
    {/if}
  </div>

  <div class="action-row">
    {#if running}
      <button
        class="cancel-button"
        type="button"
        disabled={!onCancel}
        on:click={() => void onCancel?.()}
      >
        <span class="stop-mark" aria-hidden="true"></span>
        {cancelLabel}
      </button>
      <p class="run-status" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <span>{statusMessage}</span>
      </p>
    {:else}
      <button
        class="run-button"
        type="button"
        disabled={!canRun || !onRun}
        on:click={() => void onRun?.()}
      >
        <span>{runLabel}</span>
        <kbd>Ctrl+Enter</kbd>
      </button>
    {/if}
  </div>
</section>

<style>
  .config-summary {
    container-type: inline-size;
    display: flex;
    min-width: 0;
    flex: 0 0 auto;
    flex-direction: column;
    gap: 8px;
    padding: 9px 12px 11px;
    color: var(--text, #202535);
    background: var(--surface, #fff);
    border-top: 1px solid var(--line, #e1e6ee);
  }

  .summary-row,
  .action-row {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 8px;
  }

  .summary-items {
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    flex-wrap: wrap;
    gap: 5px;
  }

  .summary-chip {
    display: inline-flex;
    max-width: min(100%, 220px);
    min-height: 25px;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    overflow: hidden;
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 38%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 7px;
    font-size: 11px;
    line-height: 1.35;
    white-space: nowrap;
  }

  .chip-label {
    flex: 0 0 auto;
    color: var(--weak, #98a2b3);
  }

  .summary-chip strong {
    min-width: 0;
    overflow: hidden;
    color: var(--text, #202535);
    font-weight: 620;
    text-overflow: ellipsis;
  }

  button {
    border-radius: 7px;
    font: inherit;
    font-size: 12px;
    font-weight: 620;
    line-height: 1;
    white-space: nowrap;
    transition: color 140ms ease, background 140ms ease, border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
  }

  button:focus-visible {
    outline: 2px solid var(--accent, #5065c7);
    outline-offset: 2px;
  }

  button:active:not(:disabled) {
    transform: translateY(1px);
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.44;
  }

  .adjust-button {
    height: 29px;
    flex: 0 0 auto;
    padding: 0 10px;
    color: var(--muted, #697386);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
  }

  .adjust-button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: var(--accent-soft, #eef1ff);
    border-color: var(--line-strong, #cbd4e2);
  }

  .run-button,
  .cancel-button {
    display: inline-flex;
    min-width: 0;
    height: 39px;
    flex: 1 1 auto;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: 0 14px;
  }

  .run-button {
    color: #fff;
    background: var(--accent, #5065c7);
    border: 1px solid var(--accent, #5065c7);
    box-shadow: 0 5px 14px color-mix(in srgb, var(--accent, #5065c7) 20%, transparent);
  }

  .run-button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #5065c7) 88%, #000);
    box-shadow: 0 7px 18px color-mix(in srgb, var(--accent, #5065c7) 26%, transparent);
    transform: translateY(-1px);
  }

  .run-button kbd {
    padding: 3px 5px;
    color: inherit;
    background: rgb(255 255 255 / 15%);
    border: 1px solid rgb(255 255 255 / 22%);
    border-radius: 5px;
    font: inherit;
    font-size: 10px;
    font-weight: 500;
  }

  .cancel-button {
    color: var(--danger, #dc2626);
    background: var(--danger-soft, #fff8f8);
    border: 1px solid var(--danger-line, #f4caca);
  }

  .cancel-button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--danger-soft, #fff8f8) 76%, var(--danger, #dc2626));
    border-color: color-mix(in srgb, var(--danger, #dc2626) 46%, var(--danger-line, #f4caca));
    transform: translateY(-1px);
  }

  .stop-mark {
    width: 9px;
    height: 9px;
    flex: 0 0 9px;
    background: currentColor;
    border-radius: 2px;
  }

  .run-status {
    display: flex;
    min-width: 96px;
    max-width: 42%;
    margin: 0;
    align-items: center;
    gap: 6px;
    overflow: hidden;
    color: var(--muted, #697386);
    font-size: 11px;
    line-height: 1.4;
  }

  .run-status span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .spinner {
    width: 13px;
    height: 13px;
    flex: 0 0 13px;
    border: 2px solid color-mix(in srgb, var(--accent, #5065c7) 20%, transparent);
    border-top-color: var(--accent, #5065c7);
    border-radius: 50%;
    animation: spin 850ms linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  @container (max-width: 420px) {
    .summary-row {
      align-items: stretch;
      flex-direction: column;
    }

    .adjust-button {
      align-self: flex-start;
    }

    .run-button kbd {
      display: none;
    }

    .run-status {
      min-width: 0;
      max-width: 38%;
    }
  }

  @container (max-width: 300px) {
    .action-row {
      align-items: stretch;
      flex-direction: column;
    }

    .run-status {
      width: 100%;
      max-width: none;
    }
  }

  @media (max-height: 520px) {
    .config-summary {
      gap: 6px;
      padding-block: 6px 7px;
    }

    .run-button,
    .cancel-button {
      height: 35px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }

    .spinner {
      animation-duration: 1.8s;
    }
  }
</style>
