<script lang="ts">
  import type {
    ConfigSummaryItem,
    WorkbenchActionHandler,
    WorkbenchModelHandler,
    WorkbenchPhase
  } from "./types";
  import type { WorkbenchModelOption } from "../../domain/providerCatalog";
  import { Button } from "@/components/ui/button";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import Spinner from "../ui/Spinner.svelte";
  import { translator } from "../../domain/i18nStore";

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

  $: translate = $translator;

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
      <summary>
        <ChevronRight class="disclosure-caret" size={14} strokeWidth={2} aria-hidden="true" />
        {translate("更多设置")}
      </summary>
      <div class="advanced-config-content">
        {#if models.length > 0 && onModelChange}
          <label class="model-picker">
            <span>{translate("模型")}</span>
            <AppSelect
              ariaLabel={translate("切换润色模型")}
              disabled={running}
              value={optionValue(selectedProvider ?? "", selectedModel ?? "")}
              options={modelOptions}
              className="model-select"
              size="sm"
              onValueChange={changeModel}
            />
          </label>
        {/if}
        {#if onAdjust}
          <Button variant="outline" size="sm" class="adjust-button" disabled={running} onclick={() => void onAdjust?.()}>
            {adjustLabel}
          </Button>
        {/if}
      </div>
    </details>
  {/if}

  <div class="action-row">
    {#if running}
      <Button
        variant="outline"
        class="cancel-button"
        disabled={!onCancel}
        onclick={() => void onCancel?.()}
      >
        <span class="stop-mark" aria-hidden="true"></span>
        {cancelLabel}
      </Button>
      <p class="run-status" role="status" aria-live="polite">
        <Spinner size={13} thickness={2} />
        <span>{statusMessage}</span>
      </p>
    {:else}
      <Button
        class="run-button"
        disabled={!canRun || !onRun}
        onclick={() => void onRun?.()}
      >
        <span>{runLabel}</span>
        <kbd>Ctrl+Enter</kbd>
      </Button>
    {/if}
  </div>
  {#if trustSummary}
    <p class="trust-summary" aria-live="polite">{trustSummary}</p>
  {/if}
</section>

<style>
  :global(.run-button),
  :global(.cancel-button) {
    flex: 1 1 auto;
    min-width: 0;
  }

  :global(.cancel-button) {
    color: var(--danger);
    background: var(--danger-soft);
    border-color: var(--danger-line);
  }

  :global(.cancel-button:hover:not(:disabled)) {
    background: color-mix(in srgb, var(--danger-soft) 76%, var(--danger));
    border-color: color-mix(in srgb, var(--danger) 46%, var(--danger-line));
  }

  .config-summary {
    container-type: inline-size;
    display: flex;
    min-width: 0;
    flex: 0 0 auto;
    flex-direction: column;
    gap: 8px;
    padding: 8px 12px;
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
    line-height: var(--leading-meta);
    overflow-wrap: anywhere;
  }

  .summary-items {
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    flex-wrap: wrap;
    gap: 4px;
  }

  .advanced-config {
    min-width: 0;
  }

  .advanced-config summary {
    display: flex;
    width: fit-content;
    align-items: center;
    gap: 4px;
    color: var(--muted, #71717a);
    cursor: pointer;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-weight: 600;
    list-style: none;
  }

  .advanced-config summary::-webkit-details-marker {
    display: none;
  }

  .advanced-config summary::marker {
    content: "";
  }

  /* 展开指示交给 lucide 图标，与全库图标语言一致（原生 ▶ 在不同渲染后端会长得不一样） */
  .advanced-config :global(.disclosure-caret) {
    flex: 0 0 auto;
    color: var(--weak, #98a2b3);
    transition: transform 150ms ease;
  }

  .advanced-config[open] :global(.disclosure-caret) {
    transform: rotate(90deg);
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
    min-height: 24px;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    overflow: hidden;
    color: var(--muted, #697386);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 38%, var(--surface, #fff));
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 6px;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
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
    font-weight: 600;
    text-overflow: ellipsis;
  }

  .model-picker {
    display: inline-flex;
    min-width: 0;
    max-width: min(100%, 300px);
    min-height: 24px;
    align-items: center;
    gap: 4px;
    padding-left: 8px;
    color: var(--weak, #98a2b3);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 8px;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  /* 标签不可被 select 挤成竖排两行 */
  .model-picker > span {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .model-picker :global(.model-select) {
    min-width: 0;
    max-width: 230px;
    flex: 1 1 auto;
  }










  :global(.run-button) kbd {
    padding: 2px 4px;
    color: inherit;
    background: rgb(255 255 255 / 15%);
    border: 1px solid rgb(255 255 255 / 22%);
    border-radius: 6px;
    font: inherit;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-weight: 500;
  }



  .stop-mark {
    width: 8px;
    height: 8px;
    flex: 0 0 8px;
    background: currentColor;
    border-radius: 4px;
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
    line-height: var(--leading-meta);
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
      padding-block: 6px;
    }

    .run-button,
    .cancel-button {
      height: 36px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }
  }
</style>
