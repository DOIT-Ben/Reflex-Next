<script lang="ts">
  import { onMount } from "svelte";
  import X from "@lucide/svelte/icons/x";
  import { Button } from "@/components/ui/button";
  import { cn } from "@/utils.js";

  interface Props {
    title: string;
    description?: string;
    size?: "sm" | "md" | "lg" | "sheet";
    variant?: "dialog" | "page";
    z?: number;
    onClose?: () => void;
    closeLabel?: string;
    contentClass?: string;
    autofocusClose?: boolean;
    closeOnBackdrop?: boolean;
    showClose?: boolean;
    icon?: import("svelte").Snippet;
    children?: import("svelte").Snippet;
    actions?: import("svelte").Snippet;
    footer?: import("svelte").Snippet;
  }

  let {
    title,
    description = "",
    size = "md",
    variant = "dialog",
    z = 8,
    onClose = undefined,
    closeLabel = "关闭",
    contentClass = "",
    autofocusClose = true,
    closeOnBackdrop = false,
    showClose = true,
    icon = undefined,
    children = undefined,
    actions = undefined,
    footer = undefined
  }: Props = $props();

  let closeButton = $state<HTMLButtonElement | null>(null);
  let shell = $state<HTMLElement>(undefined as unknown as HTMLElement);

  const focusableSelector =
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

  const sizeClass: Record<"sm" | "md" | "lg" | "sheet", string> = {
    sm: "max-w-sm",
    md: "max-w-lg",
    lg: "max-w-2xl",
    sheet: "max-w-md"
  };

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

<!-- 弹窗外壳：与 CC Switch 同构（50% 黑遮罩+模糊、居中、max-h-90vh、头/底 px-6 py-5 + 分隔线 + muted 底） -->
<div
  class={variant === "page" ? "ui-dialog-page" : "ui-dialog-layer"}
  role="presentation"
  style={variant === "page" ? undefined : `z-index: ${z}`}
  onclick={variant === "page" ? undefined : handleLayerClick}
>
  <section
    class={cn("ui-dialog-shell", variant === "page" ? "page" : sizeClass[size])}
    role={variant === "page" ? "region" : "dialog"}
    aria-modal={variant === "page" ? undefined : "true"}
    aria-label={title}
    bind:this={shell}
  >
    <header>
      <div>
        <h2>{#if icon}<span class="ui-dialog-title-icon" aria-hidden="true">{@render icon()}</span>{/if}{title}</h2>
        {#if description}<p>{description}</p>{/if}
      </div>
      <div class="ui-dialog-header-actions">
        {@render actions?.()}
        {#if onClose && showClose && variant !== "page"}
          <Button
            variant="ghost"
            size="icon-sm"
            class="text-muted-foreground hover:text-foreground"
            aria-label={closeLabel}
            bind:ref={closeButton}
            onclick={onClose}
          >
            <X size={16} strokeWidth={2} />
          </Button>
        {/if}
      </div>
    </header>
    <div class={`ui-dialog-content ${contentClass}`}>
      {@render children?.()}
    </div>
    {#if footer}
      <footer>{@render footer()}</footer>
    {/if}
    </section>
  </div>

<style>
  .ui-dialog-page {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 0;
  }

  .ui-dialog-shell.page {
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    padding: 16px 24px;
    background: hsl(var(--background));
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .ui-dialog-layer {
    position: fixed;
    inset: 0;
    z-index: 40;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgb(0 0 0 / 50%);
    -webkit-backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }

  .ui-dialog-shell {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-height: 0;
    max-height: 90vh;
    overflow: hidden;
    color: hsl(var(--foreground));
    background: hsl(var(--background));
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
    box-shadow:
      0 10px 15px -3px rgb(0 0 0 / 10%),
      0 4px 6px -4px rgb(0 0 0 / 10%);
  }

  .ui-dialog-shell > header {
    display: flex;
    flex: 0 0 auto;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 24px;
    /* CC Switch 的 header/footer 色带：bg-muted/20 */
    background: hsl(var(--muted) / 0.2);
    border-bottom: 1px solid hsl(var(--border));
  }

  /* 整页形态（设置）：页头保持白底，不铺灰带 */
  .ui-dialog-shell.page > header,
  .ui-dialog-shell.page > footer {
    background: transparent;
  }

  .ui-dialog-shell h2,
  .ui-dialog-shell p {
    margin: 0;
  }

  .ui-dialog-shell h2 {
    font-size: var(--font-title);
    font-weight: 600;
    line-height: var(--leading-title);
    letter-spacing: -0.01em;
  }

  /* 标题行内图标（CC Switch 确认框形态：图标与标题同行） */
  .ui-dialog-title-icon {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    margin-right: 8px;
    vertical-align: -3px;
  }

  .ui-dialog-shell header p {
    margin-top: 6px;
    color: hsl(var(--muted-foreground));
    font-size: var(--font-body);
    line-height: var(--leading-body);
  }

  .ui-dialog-content {
    flex: 1 1 auto;
    min-height: 0;
    padding: 16px 24px;
    overflow: auto;
  }

  .ui-dialog-shell > footer {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    padding: 20px 24px;
    background: hsl(var(--muted) / 0.2);
    border-top: 1px solid hsl(var(--border));
  }

  .ui-dialog-header-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 8px;
  }
</style>
