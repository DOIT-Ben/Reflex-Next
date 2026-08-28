<script lang="ts">
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import Minus from "@lucide/svelte/icons/minus";
  import PanelTop from "@lucide/svelte/icons/panel-top";
  import RectangleHorizontal from "@lucide/svelte/icons/rectangle-horizontal";
  import RectangleVertical from "@lucide/svelte/icons/rectangle-vertical";
  import Search from "@lucide/svelte/icons/search";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import X from "@lucide/svelte/icons/x";
  import ZoomIn from "@lucide/svelte/icons/zoom-in";
  import ZoomOut from "@lucide/svelte/icons/zoom-out";
  import type { ProviderAvailability, WindowSizePreset } from "./types";

  interface Props {
    appName?: string;
    providerName?: string;
    modelName?: string;
    availability?: ProviderAvailability;
    availabilityLabel?: string;
    scale?: number;
    minimumScale?: number;
    maximumScale?: number;
    windowSize?: WindowSizePreset;
    commandLabel?: string;
    commandShortcut?: string;
    onOpenProvider?: () => void;
    onOpenCommand?: () => void;
    onZoomOut?: () => void;
    onResetZoom?: () => void;
    onZoomIn?: () => void;
    onWindowSizeChange?: (size: WindowSizePreset) => void;
    onMinimize?: () => void;
    onMaximize?: () => void;
    onClose?: () => void;
  }

  let {
    appName = "Reflex Next",
    providerName = "MiniMax",
    modelName = "",
    availability = "checking",
    availabilityLabel = "正在检查",
    scale = 1,
    minimumScale = 0.85,
    maximumScale = 1.15,
    windowSize = "default",
    commandLabel = "搜索命令",
    commandShortcut = "Ctrl K",
    onOpenProvider,
    onOpenCommand,
    onZoomOut,
    onResetZoom,
    onZoomIn,
    onWindowSizeChange,
    onMinimize,
    onMaximize,
    onClose
  }: Props = $props();

  const sizeOptions: Array<{
    id: WindowSizePreset;
    label: string;
  }> = [
    { id: "compact", label: "紧凑尺寸" },
    { id: "default", label: "默认尺寸" },
    { id: "wide", label: "宽屏尺寸" }
  ];

  async function dragWindow(event: MouseEvent) {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest("button, input, select, textarea, a, summary, details")) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().startDragging();
    } catch {
      // Browser preview and non-Tauri tests do not expose window dragging.
    }
  }
</script>

<header class="title-bar" role="toolbar" tabindex="-1" aria-label="应用标题栏" onmousedown={dragWindow}>
  <div class="identity" title={appName} data-tauri-drag-region="true">
    <span class="app-mark" aria-hidden="true">R</span>
    <strong>{appName}</strong>
  </div>

  <span class="separator" aria-hidden="true"></span>

  <button
    class="provider-status"
    type="button"
    data-availability={availability}
    aria-label={`Provider：${providerName}，${availabilityLabel}`}
    title={`${providerName} ${modelName} ${availabilityLabel}`.trim()}
    disabled={!onOpenProvider}
    onclick={onOpenProvider}
  >
    <span class="provider-dot" aria-hidden="true"></span>
    <span class="provider-copy">
      <strong>{providerName}</strong>
      {#if modelName}
        <span class="model">· {modelName}</span>
      {/if}
      <span class="availability">· {availabilityLabel}</span>
    </span>
  </button>

  <button
    class="command-trigger"
    type="button"
    aria-label={`${commandLabel}，${commandShortcut}`}
    title={`${commandLabel} (${commandShortcut})`}
    disabled={!onOpenCommand}
    onclick={onOpenCommand}
  >
    <Search size={14} strokeWidth={1.8} aria-hidden="true" />
    <span class="command-label">{commandLabel}</span>
    <kbd>{commandShortcut}</kbd>
  </button>

  <span class="bar-spacer" data-tauri-drag-region="true"></span>

  <details class="workspace-controls">
    <summary aria-label="工作区显示选项" title="工作区显示选项">
      <SlidersHorizontal size={15} strokeWidth={1.8} aria-hidden="true" />
    </summary>
    <div class="workspace-control-popover">
      <div class="control-cluster zoom-controls" role="group" aria-label="页面缩放">
        <button
          type="button"
          aria-label="缩小页面"
          title="缩小页面"
          disabled={!onZoomOut || scale <= minimumScale}
          onclick={onZoomOut}
        ><ZoomOut size={14} strokeWidth={1.8} aria-hidden="true" /></button>
        <button
          class="scale-value"
          type="button"
          aria-label={`重置页面缩放，当前 ${Math.round(scale * 100)}%`}
          title="重置页面缩放"
          disabled={!onResetZoom}
          onclick={onResetZoom}
        >{Math.round(scale * 100)}%</button>
        <button
          type="button"
          aria-label="放大页面"
          title="放大页面"
          disabled={!onZoomIn || scale >= maximumScale}
          onclick={onZoomIn}
        ><ZoomIn size={14} strokeWidth={1.8} aria-hidden="true" /></button>
      </div>

      <div class="control-cluster size-controls" role="group" aria-label="窗口尺寸">
        {#each sizeOptions as option (option.id)}
          <button
            type="button"
            aria-label={option.label}
            aria-pressed={windowSize === option.id}
            title={option.label}
            disabled={!onWindowSizeChange}
            onclick={() => onWindowSizeChange?.(option.id)}
          >
            {#if option.id === "compact"}
              <RectangleVertical size={14} strokeWidth={1.8} aria-hidden="true" />
            {:else if option.id === "default"}
              <PanelTop size={14} strokeWidth={1.8} aria-hidden="true" />
            {:else}
              <RectangleHorizontal size={14} strokeWidth={1.8} aria-hidden="true" />
            {/if}
          </button>
        {/each}
      </div>
    </div>
  </details>

  <div class="window-controls" role="group" aria-label="窗口控制">
    <button type="button" aria-label="最小化窗口" title="最小化" disabled={!onMinimize} onclick={onMinimize}>
      <Minus size={14} strokeWidth={1.8} aria-hidden="true" />
    </button>
    <button type="button" aria-label="最大化或还原窗口" title="最大化或还原" disabled={!onMaximize} onclick={onMaximize}>
      <Maximize2 size={13} strokeWidth={1.8} aria-hidden="true" />
    </button>
    <button class="close" type="button" aria-label="关闭窗口" title="关闭" disabled={!onClose} onclick={onClose}>
      <X size={14} strokeWidth={1.8} aria-hidden="true" />
    </button>
  </div>
</header>

<style>
  .title-bar {
    container-type: inline-size;
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    min-width: 0;
    height: 44px;
    padding: 0 8px 0 10px;
    color: var(--text, #202535);
    background: var(--surface, #fff);
    border-bottom: 1px solid var(--line, #e1e6ee);
    box-sizing: border-box;
    user-select: none;
  }

  .identity,
  .provider-status,
  .command-trigger,
  .control-cluster,
  .window-controls {
    display: flex;
    align-items: center;
  }

  .identity {
    flex: 0 0 auto;
    gap: 7px;
    min-width: 0;
  }

  .identity strong {
    overflow: hidden;
    max-width: 112px;
    font-size: var(--font-body);
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .app-mark {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    color: #fff;
    background: var(--accent, #5065c7);
    border-radius: 7px;
    box-shadow: 0 2px 6px rgb(39 49 96 / 18%);
    font-size: var(--font-meta);
    font-weight: 750;
  }

  .separator {
    flex: 0 0 1px;
    width: 1px;
    height: 16px;
    background: var(--line, #e1e6ee);
  }

  .provider-status {
    gap: 6px;
    width: auto;
    height: 28px;
    min-width: 0;
    padding: 0 5px;
    color: var(--muted, #697386);
    background: transparent;
    border: 0;
    font-size: var(--font-meta);
  }

  .provider-dot {
    flex: 0 0 auto;
    width: 7px;
    height: 7px;
    background: #8b95a7;
    border-radius: 50%;
    box-shadow: 0 0 0 2px color-mix(in srgb, #8b95a7 16%, transparent);
  }

  .provider-status[data-availability="ready"] .provider-dot {
    background: #2f9e62;
    box-shadow: 0 0 0 2px color-mix(in srgb, #2f9e62 16%, transparent);
  }

  .provider-status[data-availability="missing"] .provider-dot {
    background: #d08724;
    box-shadow: 0 0 0 2px color-mix(in srgb, #d08724 16%, transparent);
  }

  .provider-status[data-availability="unavailable"] .provider-dot {
    background: #cf4b4b;
    box-shadow: 0 0 0 2px color-mix(in srgb, #cf4b4b 16%, transparent);
  }

  .provider-copy {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .provider-copy strong {
    color: var(--text, #202535);
    font-weight: 600;
  }

  button {
    display: inline-grid;
    place-items: center;
    min-width: 28px;
    height: 28px;
    padding: 0;
    color: var(--muted, #697386);
    background: transparent;
    border: 0;
    border-radius: 7px;
    font: inherit;
    line-height: 1;
    cursor: pointer;
    transition: color 140ms ease, background 140ms ease, transform 100ms ease;
  }

  button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 70%, transparent);
  }

  button:active:not(:disabled) {
    transform: scale(0.94);
  }

  button:focus-visible {
    outline: 2px solid var(--accent, #5065c7);
    outline-offset: 1px;
  }

  button:disabled {
    cursor: default;
    opacity: 0.42;
  }

  .command-trigger {
    display: flex;
    flex: 0 1 auto;
    gap: 5px;
    min-width: 0;
    width: auto;
    padding: 0 5px 0 7px;
    border: 1px solid var(--line, #e1e6ee);
    background: color-mix(in srgb, var(--surface, #fff) 72%, var(--accent-soft, #eef1ff));
    font-size: var(--font-meta);
  }

  .command-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  kbd {
    padding: 2px 4px;
    color: var(--muted, #697386);
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 4px;
    font-family: inherit;
    font-size: var(--font-meta);
    line-height: 1;
    white-space: nowrap;
  }

  .bar-spacer {
    flex: 1 1 auto;
    min-width: 0;
  }

  .control-cluster {
    flex: 0 0 auto;
    gap: 1px;
    padding: 1px;
    background: color-mix(in srgb, var(--surface, #fff) 68%, var(--accent-soft, #eef1ff));
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 8px;
  }

  .workspace-controls {
    position: relative;
    flex: 0 0 auto;
  }

  .workspace-controls summary {
    display: grid;
    width: 28px;
    height: 28px;
    place-items: center;
    color: var(--muted, #697386);
    border-radius: 7px;
    cursor: pointer;
    list-style: none;
  }

  .workspace-controls summary::-webkit-details-marker {
    display: none;
  }

  .workspace-controls summary:hover {
    color: var(--text, #202535);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 70%, transparent);
  }

  .workspace-controls[open] summary {
    color: var(--accent, #5065c7);
    background: var(--accent-soft, #eef1ff);
  }

  .workspace-control-popover {
    position: absolute;
    z-index: 6;
    top: calc(100% + 7px);
    right: 0;
    display: none;
    gap: 6px;
    min-width: max-content;
    max-width: min(280px, calc(100vw - 16px));
    box-sizing: border-box;
    padding: 8px;
    background: var(--surface, #fff);
    border: 1px solid var(--line, #e1e6ee);
    border-radius: 10px;
    box-shadow: 0 10px 24px rgb(32 37 53 / 14%);
  }

  .workspace-controls[open] .workspace-control-popover {
    display: grid;
  }

  .control-cluster button {
    min-width: 25px;
    height: 24px;
    border-radius: 6px;
    font-size: var(--font-meta);
  }

  .control-cluster button[aria-pressed="true"] {
    color: var(--accent, #5065c7);
    background: var(--accent-soft, #eef1ff);
  }

  .scale-value {
    min-width: 38px !important;
    padding: 0 4px !important;
    font-size: var(--font-meta) !important;
    font-variant-numeric: tabular-nums;
  }

  .window-controls {
    flex: 0 0 auto;
    gap: 1px;
    padding-left: 5px;
    border-left: 1px solid var(--line, #e1e6ee);
  }

  .window-controls .close:hover:not(:disabled) {
    color: #b42318;
    background: #fdeceb;
  }

  @container (max-width: 760px) {
    .model,
    .command-label {
      display: none;
    }

    .identity strong {
      max-width: 90px;
    }
  }

  @container (max-width: 620px) {
    .availability,
    .command-trigger,
    .size-controls {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }
  }
</style>
