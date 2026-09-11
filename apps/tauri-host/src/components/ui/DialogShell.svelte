<script lang="ts">
  import { onMount } from "svelte";
  import X from "@lucide/svelte/icons/x";

  export let title: string;
  export let description = "";
  export let size: "sm" | "md" | "lg" | "sheet" = "md";
  export let z = 8;
  export let onClose: (() => void) | undefined = undefined;
  export let closeLabel = "关闭";
  export let contentClass = "";
  export let autofocusClose = true;
  export let closeOnBackdrop = false;
  export let showClose = true;

  let closeButton: HTMLButtonElement;
  let shell: HTMLElement;

  const focusableSelector =
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

  onMount(() => {
    if (!onClose) return;
    if (autofocusClose) closeButton?.focus();
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose?.();
        return;
      }
      if (event.key === "Tab") trapFocus(event);
    };
    window.addEventListener("keydown", handleKeydown, true);
    return () => window.removeEventListener("keydown", handleKeydown, true);
  });

  function focusableElements(): HTMLElement[] {
    return Array.from(shell?.querySelectorAll<HTMLElement>(focusableSelector) ?? []).filter(
      (element) => element.offsetWidth > 0 || element.offsetHeight > 0
    );
  }

  function trapFocus(event: KeyboardEvent) {
    const elements = focusableElements();
    if (elements.length === 0) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !shell.contains(active as Node))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !shell.contains(active as Node))) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleLayerClick(event: MouseEvent) {
    if (!closeOnBackdrop || event.target !== event.currentTarget) return;
    event.preventDefault();
    onClose?.();
  }
</script>

<div class="ui-dialog-layer" role="presentation" style={`z-index: ${z}`} onclick={handleLayerClick}>
  <section class={`ui-dialog-shell ${size}`} role="dialog" aria-modal="true" aria-label={title} bind:this={shell}>
    <header>
      <div>
        <h2>{title}</h2>
        {#if description}<p>{description}</p>{/if}
      </div>
      <div class="ui-dialog-header-actions">
        <slot name="actions" />
        {#if onClose && showClose}
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

  .ui-dialog-layer.sheet {
    inset: 44px 0 24px;
    padding: 12px;
    background: var(--window, #fff);
  }

  .ui-dialog-shell.sheet {
    width: 100%;
    height: 100%;
    background: var(--surface, #fff);
    border-color: var(--line, #e1e6ee);
    border-radius: 8px;
    box-shadow: none;
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
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
