<script lang="ts">
  import { onMount } from "svelte";
  import X from "@lucide/svelte/icons/x";

  export let title: string;
  export let description = "";
  export let size: "sm" | "md" | "lg" = "md";
  export let z = 8;
  export let onClose: (() => void) | undefined = undefined;
  export let closeLabel = "关闭";
  export let contentClass = "";

  let closeButton: HTMLButtonElement;

  onMount(() => {
    if (!onClose) return;
    closeButton?.focus();
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      onClose?.();
    };
    window.addEventListener("keydown", handleKeydown, true);
    return () => window.removeEventListener("keydown", handleKeydown, true);
  });
</script>

<div class="ui-dialog-layer" role="presentation" style={`z-index: ${z}`}>
  <section class={`ui-dialog-shell ${size}`} role="dialog" aria-modal="true" aria-label={title}>
    <header>
      <div>
        <h2>{title}</h2>
        {#if description}<p>{description}</p>{/if}
      </div>
      <div class="ui-dialog-header-actions">
        <slot name="actions" />
        {#if onClose}
          <button class="icon-button" type="button" aria-label={closeLabel} bind:this={closeButton} onclick={onClose}>
            <X size={17} strokeWidth={2} />
          </button>
        {/if}
      </div>
    </header>
    <div class={`ui-dialog-content ${contentClass}`}>
      <slot />
    </div>
    {#if $$slots.footer}
      <footer><slot name="footer" /></footer>
    {/if}
  </section>
</div>

<style>
  .ui-dialog-layer {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    padding: 16px;
    background: var(--overlay, rgb(28 29 32 / 30%));
  }

  .ui-dialog-shell {
    display: flex;
    flex-direction: column;
    min-height: 0;
    max-height: 100%;
    overflow: hidden;
  }

  .ui-dialog-shell.sm {
    width: min(440px, 100%);
    height: fit-content;
  }

  .ui-dialog-shell.md {
    width: min(720px, 100%);
    height: min(508px, 100%);
  }

  .ui-dialog-shell.lg {
    width: min(760px, 100%);
    height: min(540px, 100%);
  }

  .ui-dialog-shell.sm .ui-dialog-content {
    overflow: visible;
  }

  .ui-dialog-header-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 8px;
  }

  .ui-dialog-shell .icon-button {
    display: grid;
    width: 32px;
    height: 32px;
    place-items: center;
    color: var(--muted, #697386);
    background: transparent;
    border: 0;
    border-radius: 8px;
    cursor: pointer;
  }

  .ui-dialog-shell .icon-button:hover {
    color: var(--text, #202535);
    background: var(--accent-soft, #eef1ff);
  }

  .ui-dialog-shell .icon-button:focus-visible {
    outline: 2px solid var(--accent, #5065c7);
    outline-offset: 2px;
  }

  .ui-dialog-content {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
  }

  .ui-dialog-shell > footer {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    padding-top: 14px;
  }
</style>
