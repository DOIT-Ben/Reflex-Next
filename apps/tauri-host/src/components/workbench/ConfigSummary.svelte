<script lang="ts">
  import type {
    ConfigSummaryItem,
    WorkbenchActionHandler,
    WorkbenchModelHandler,
    WorkbenchPhase
  } from "./types";
  import type { WorkbenchModelOption } from "../../domain/providerCatalog";
  import SelectField from "../ui/SelectField.svelte";
  import Spinner from "../ui/Spinner.svelte";

  export let items: ReadonlyArray<ConfigSummaryItem> = [];
  export let phase: WorkbenchPhase = "empty";
  export let canRun = false;
  export let statusMessage = "正在生成…";
  export let runLabel = "优化文本";
  export let cancelLabel = "取消生成";
  export let adjustLabel = "调整方案";
  export let trustSummary = "";
  export let onRun: WorkbenchActionHandler | undefined = undefined;
  export let onCancel: WorkbenchActionHandler | undefined = undefined;
  export let onAdjust: WorkbenchActionHandler | undefined = undefined;
  export let models: ReadonlyArray<WorkbenchModelOption> = [];
  export let selectedProvider: string | null = null;
  export let selectedModel: string | null = null;
  export let onModelChange: WorkbenchModelHandler | undefined = undefined;
  export let translate: (source: string, values?: Record<string, string | number>) => string = (source) => source;

  $: running = phase === "running";
  $: modelOptions = models.map((model) => ({
    value: optionValue(model.providerId, model.id),
    label: `${model.providerLabel} · ${translate(model.label)}${model.isDefault ? ` · ${translate("默认")}` : ""}`
  }));

  function optionValue(providerId: string, modelId: string): string {
    return JSON.stringify([providerId, modelId]);
  }

  function changeModel(value: string) {
    try {
      const [providerId, modelId] = JSON.parse(value) as unknown[];
      if (typeof providerId === "string" && typeof modelId === "string") {
        onModelChange?.(providerId, modelId);
      }
    } catch {
      // Ignore malformed values that did not originate from the model list.
    }
  }
</script>

<section class="config-summary" aria-label={translate("本次生成配置")}>
  <div class="summary-row">
    <div class="summary-items" aria-label={translate("配置摘要")}>
      {#each items as item (item.id)}
        <span class="summary-chip" title={item.title ?? `${item.label}：${item.value}`}>
          <span class="chip-label">{item.label}</span>
          <strong>{item.value}</strong>
        </span>
      {/each}
    </div>
  </div>

  {#if (models.length > 0 && onModelChange) || onAdjust}
    <details class="advanced-config">
      <summary>{translate("更多设置")}</summary>
      <div class="advanced-config-content">
        {#if models.length > 0 && onModelChange}
          <label class="model-picker">
            <span>{translate("模型")}</span>
            <SelectField
              ariaLabel={translate("切换润色模型")}
              disabled={running}
              value={optionValue(selectedProvider ?? "", selectedModel ?? "")}
              options={modelOptions}
              className="model-select"
              size="compact"
              fullWidth={false}
              onValueChange={changeModel}
            />
          </label>
        {/if}
        {#if onAdjust}
          <button class="adjust-button" type="button" disabled={running} on:click={() => void onAdjust?.()}>
            {adjustLabel}
          </button>
        {/if}
      </div>
    </details>
  {/if}

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
        <Spinner size={13} thickness={2} />
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
  {#if trustSummary}
    <p class="trust-summary" aria-live="polite">{trustSummary}</p>
  {/if}
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

  .trust-summary {
    margin: 0;
    color: var(--muted, #697386);
    font-size: var(--font-meta);
    line-height: 1.48;
    overflow-wrap: anywhere;
  }

  .summary-items {
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    flex-wrap: wrap;
    gap: 5px;
  }

  .advanced-config {
    min-width: 0;
  }

  .advanced-config summary {
    width: fit-content;
    color: var(--muted, #697386);
    cursor: pointer;
    font-size: var(--font-meta);
    font-weight: 600;
  }

  .advanced-config-content {
    display: none;
    min-width: 0;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding-top: 8px;
  }

  .advanced-config[open] .advanced-config-content {
    display: flex;
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
    font-size: var(--font-meta);
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

  .model-picker {
    display: inline-flex;
    max-width: min(100%, 300px);
    min-height: 25px;
    align-items: center;
    gap: 5px;
    padding-left: 8px;
    color: var(--weak, #98a2b3);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 7px;
    font-size: var(--font-meta);
  }

  .model-picker :global(.model-select) {
    min-width: 0;
    max-width: 230px;
    flex: 1 1 auto;
  }

  button {
    border-radius: 7px;
    font: inherit;
    font-size: var(--font-meta);
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
    font-size: var(--font-meta);
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
    font-size: var(--font-meta);
    line-height: 1.4;
  }

  .run-status span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
  }
</style>
