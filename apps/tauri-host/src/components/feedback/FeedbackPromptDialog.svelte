<script lang="ts">
  import { Button } from "@/components/ui/button";
  import MessageSquareText from "@lucide/svelte/icons/message-square-text";
  import ThumbsDown from "@lucide/svelte/icons/thumbs-down";
  import ThumbsUp from "@lucide/svelte/icons/thumbs-up";
  import X from "@lucide/svelte/icons/x";
  import { translator } from "../../domain/i18nStore";

  export let onPositive: () => void;
  export let onNegative: () => void;
  export let onLater: () => void;
  export let onDisable: () => void;
  export let busy = false;
  export let notice: string | null = null;

  $: translate = $translator;
</script>

<div class="feedback-prompt-layer" role="presentation">
  <div
    class="feedback-prompt"
    role="region"
    aria-live="polite"
    aria-busy={busy}
    aria-labelledby="feedback-prompt-title"
  >
    <header>
      <span class="prompt-icon" aria-hidden="true"><MessageSquareText size={18} strokeWidth={2} /></span>
      <div>
        <h2 id="feedback-prompt-title">{translate("这次结果有帮助吗？")}</h2>
        <p>{translate("你的选择会帮助我们改进场景和模型效果，不会附带输入或结果。")}</p>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={translate("稍后反馈")}
        title={translate("稍后")}
        disabled={busy}
        onclick={onLater}
      >
        <X size={17} strokeWidth={2} />
      </Button>
    </header>

    <div class="sentiment-actions">
      <Button variant="outline" size="sm" disabled={busy} onclick={onPositive}>
        <ThumbsUp size={17} strokeWidth={2} />{translate(busy ? "正在记录" : "有帮助")}
      </Button>
      <Button variant="outline" size="sm" disabled={busy} onclick={onNegative}>
        <ThumbsDown size={17} strokeWidth={2} />{translate(busy ? "正在记录" : "需要改进")}
      </Button>
    </div>

    {#if notice}<p class="prompt-notice" role="status">{translate(notice)}</p>{/if}

    <footer>
      <Button variant="ghost" size="sm" disabled={busy} onclick={onLater}>{translate("稍后再问")}</Button>
      <Button variant="ghost" size="sm" disabled={busy} onclick={onDisable}>{translate("不再主动询问")}</Button>
    </footer>
  </div>
</div>

<style>
  .feedback-prompt-layer {
    position: absolute;
    inset: 0;
    z-index: 29;
    display: flex;
    align-items: flex-end;
    justify-content: flex-end;
    padding: 16px;
    pointer-events: none;
  }

  .feedback-prompt {
    width: min(390px, 100%);
    overflow: hidden;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--line-strong);
    border-radius: 12px;
    box-shadow: 0 18px 44px rgb(18 24 38 / 22%);
    pointer-events: auto;
  }

  header {
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr) 32px;
    gap: 10px;
    align-items: start;
    padding: 14px 14px 10px;
  }

  .prompt-icon,
  .icon-button {
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    color: var(--accent);
    background: var(--accent-soft);
    border: 0;
    border-radius: 8px;
  }

  .icon-button {
    color: var(--muted);
    background: transparent;
  }

  h2 {
    margin: 0;
    font-size: var(--font-body);
    line-height: var(--leading-body);
  }

  p {
    margin: 4px 0 0;
    color: var(--muted);
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  .sentiment-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 4px 14px 14px;
  }

  .sentiment-actions button {
    display: inline-flex;
    min-height: 40px;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    font-weight: 600;
  }

  .sentiment-actions button:hover {
    color: var(--accent);
    background: var(--accent-soft);
    border-color: var(--accent);
  }

  .sentiment-actions button:disabled,
  footer button:disabled,
  .icon-button:disabled {
    cursor: default;
    opacity: 0.55;
  }

  .prompt-notice {
    margin: -6px 14px 12px;
    color: var(--danger);
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 8px 12px;
    background: color-mix(in srgb, var(--window) 72%, var(--surface));
    border-top: 1px solid var(--line);
  }

  footer button {
    padding: 4px 0;
    color: var(--muted);
    background: transparent;
    border: 0;
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  footer button:hover,
  .icon-button:hover {
    color: var(--text);
  }

  @media (max-width: 560px) {
    .feedback-prompt-layer {
      padding: 10px;
    }

    .feedback-prompt {
      width: 100%;
    }
  }
</style>
