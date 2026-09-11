<script lang="ts">
  import type {
    WorkbenchActionHandler,
    WorkbenchInputHandler,
    WorkbenchPhase
  } from "./types";
  import type { QuickAction } from "../../domain/productExperience";
  import { translator } from "../../domain/i18nStore";

  export let value = "";
  export let phase: WorkbenchPhase = "empty";
  export let label = "输入文本";
  export let placeholder = "在此输入或粘贴需要优化的文本。按 Ctrl+Enter 生成。";
  export let notice = "";
  export let maxLength = 100_000;
  export let disabled = false;
  export let clipboardBusy = false;
  export let quickActions: ReadonlyArray<QuickAction> = [];
  export let onInput: WorkbenchInputHandler = () => undefined;
  export let onQuickAction: ((actionId: string) => void) | undefined = undefined;
  export let onRun: WorkbenchActionHandler | undefined = undefined;
  export let onReadClipboard: WorkbenchActionHandler | undefined = undefined;
  export let onClear: WorkbenchActionHandler | undefined = undefined;

  $: translate = $translator;

  let textarea: HTMLTextAreaElement;

  $: running = phase === "running";
  $: locked = disabled || running;
  $: characterCount = value.length;
  $: overLimit = maxLength > 0 && characterCount > maxLength;
  $: hardLimit = maxLength > 0 ? maxLength + Math.max(200, Math.ceil(maxLength * 0.02)) : undefined;
  $: helpText = notice || (maxLength > 0 ? `支持纯文本，${maxLength.toLocaleString()} 字以内` : "支持纯文本");

  function handleInput(event: Event) {
    onInput((event.currentTarget as HTMLTextAreaElement).value);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (
      (event.ctrlKey || event.metaKey) &&
      event.key === "Enter" &&
      !locked &&
      !overLimit &&
      value.trim() &&
      onRun
    ) {
      event.preventDefault();
      event.stopPropagation();
      void onRun();
    }
  }

  function clearInput() {
    if (onClear) {
      void onClear();
    } else {
      onInput("");
    }
    textarea?.focus();
  }
</script>

<section class="input-pane" aria-labelledby="workbench-input-title">
  <header class="pane-header">
    <h2 id="workbench-input-title">{label}</h2>
    <div class="header-actions">
      {#if onReadClipboard}
        <button
          type="button"
          disabled={locked || clipboardBusy}
          aria-label={translate("读取剪贴板")}
          title={translate("读取系统剪贴板内容到输入框")}
          on:click={() => void onReadClipboard?.()}
        >
          {clipboardBusy ? translate("读取中…") : translate("读取剪贴板")}
        </button>
      {/if}
      <button
        class="clear-button"
        type="button"
        disabled={locked || characterCount === 0}
        aria-label={translate("清空输入")}
        title={translate("清空当前输入")}
        on:click={clearInput}
      >
        {translate("清空")}
      </button>
    </div>
  </header>

  {#if quickActions.length > 0}
    <div class="quick-actions" aria-label={translate("常用任务")}>
      {#each quickActions as action (action.id)}
        <button
          class="quick-action"
          type="button"
          disabled={locked || !onQuickAction}
          title={translate(action.hint)}
          on:click={() => onQuickAction?.(action.id)}
        >
          <strong>{translate(action.label)}</strong>
        </button>
      {/each}
    </div>
  {/if}

  <div class:invalid={overLimit} class="editor-frame">
    <textarea
      bind:this={textarea}
      {value}
      maxlength={hardLimit}
      {placeholder}
      spellcheck="false"
      aria-label={label}
      aria-describedby="workbench-input-help workbench-input-count"
      aria-invalid={overLimit}
      disabled={locked}
      on:input={handleInput}
      on:keydown={handleKeydown}
    ></textarea>
    <footer class="editor-footer">
      <span class:error={overLimit} id="workbench-input-help">{helpText}</span>
      <span class:error={overLimit} id="workbench-input-count" aria-live="polite">
        {translate("{count} 字", { count: characterCount.toLocaleString() })}
      </span>
    </footer>
  </div>
</section>

<style>
  .input-pane {
    container-type: inline-size;
    display: flex;
    min-width: 0;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    color: var(--text, #202535);
    background: var(--surface, #fff);
  }

  .pane-header {
    display: flex;
    min-height: 44px;
    flex: 0 0 auto;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 7px 12px;
  }

  h2 {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    font-size: var(--font-body);
    font-weight: 650;
    line-height: 1.4;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-actions {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: flex-end;
    gap: 2px;
  }

  .quick-actions {
    display: flex;
    min-width: 0;
    align-items: stretch;
    gap: 6px;
    padding: 0 12px 9px;
    overflow-x: auto;
  }

  .quick-action {
    display: flex;
    min-width: 98px;
    height: auto;
    flex: 1 1 0;
    align-items: center;
    justify-content: center;
    padding: 7px 9px;
    text-align: center;
  }

  .quick-action strong { color: var(--text, #202535); font-size: var(--font-meta); font-weight: 650; }

  button {
    min-width: 30px;
    height: 30px;
    padding: 0 9px;
    color: var(--muted, #697386);
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    font-size: var(--font-meta);
    font-weight: 560;
    line-height: 1;
    white-space: nowrap;
    transition: color 140ms ease, background 140ms ease, border-color 140ms ease, transform 140ms ease;
  }

  button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 72%, var(--surface, #fff));
    border-color: var(--line, #e1e6ee);
    transform: translateY(-1px);
  }

  button:active:not(:disabled) {
    transform: translateY(0);
  }

  button:focus-visible,
  textarea:focus-visible {
    outline: 2px solid var(--accent, #5065c7);
    outline-offset: 2px;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.44;
  }

  .editor-frame {
    display: flex;
    min-width: 0;
    min-height: 96px;
    margin: 0 12px 10px;
    flex: 1 1 auto;
    flex-direction: column;
    overflow: hidden;
    background: color-mix(in srgb, var(--surface, #fff) 78%, var(--page, #edf1f6));
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 8px;
    transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
  }

  .editor-frame:focus-within {
    background: var(--surface, #fff);
    border-color: color-mix(in srgb, var(--accent, #5065c7) 56%, var(--line, #e1e6ee));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent, #5065c7) 12%, transparent);
  }

  .editor-frame.invalid {
    border-color: var(--danger, #dc2626);
  }

  textarea {
    width: 100%;
    min-width: 0;
    min-height: 56px;
    flex: 1 1 auto;
    resize: none;
    padding: 11px 12px;
    overflow: auto;
    color: var(--text, #202535);
    background: transparent;
    border: 0;
    font: inherit;
    font-size: var(--font-body);
    line-height: 1.68;
    overflow-wrap: anywhere;
  }

  textarea::placeholder {
    color: var(--weak, #98a2b3);
  }

  textarea:focus-visible {
    outline: 0;
  }

  textarea:disabled {
    cursor: not-allowed;
    opacity: 0.64;
  }

  .editor-footer {
    display: flex;
    min-width: 0;
    min-height: 28px;
    flex: 0 0 auto;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 5px 9px;
    color: var(--muted, #697386);
    border-top: 1px solid color-mix(in srgb, var(--line, #e1e6ee) 74%, transparent);
    font-size: var(--font-meta);
    line-height: 1.4;
  }

  .editor-footer span:first-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .editor-footer span:last-child {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .error {
    color: var(--danger, #dc2626);
    font-weight: 620;
  }

  @container (max-width: 360px) {
    .pane-header {
      align-items: flex-start;
      flex-direction: column;
      gap: 4px;
    }

    .header-actions {
      width: 100%;
      justify-content: flex-start;
    }

    .quick-action { min-width: 116px; flex: 0 0 auto; }

    .editor-footer span:first-child {
      max-width: 70%;
    }
  }

  @media (max-height: 520px) {
    .editor-frame {
      min-height: 70px;
    }

    textarea {
      min-height: 40px;
      padding-block: 8px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button,
    .editor-frame {
      transition: none;
    }
  }
</style>
