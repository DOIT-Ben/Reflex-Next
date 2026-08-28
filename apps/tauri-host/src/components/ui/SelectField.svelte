<script module lang="ts">
  let selectInstanceCounter = 0;
</script>

<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";

  export type SelectOption = {
    value: string;
    label: string;
    description?: string;
    group?: string;
    disabled?: boolean;
  };

  interface Props {
    options: ReadonlyArray<SelectOption>;
    value: string;
    placeholder?: string;
    unavailableLabel?: string;
    ariaLabel: string;
    disabled?: boolean;
    size?: "default" | "compact";
    fullWidth?: boolean;
    className?: string;
    onValueChange?: (value: string) => void;
  }

  let {
    options,
    value,
    placeholder = "请选择",
    unavailableLabel = "当前选项不可用",
    ariaLabel,
    disabled = false,
    size = "default",
    fullWidth = true,
    className = "",
    onValueChange
  }: Props = $props();

  const instanceId = ++selectInstanceCounter;
  const listId = `reflex-select-list-${instanceId}`;

  let root: HTMLDivElement | undefined;
  let trigger: HTMLButtonElement | undefined;
  let menuElement = $state<HTMLDivElement | undefined>();
  let open = $state(false);
  let highlightedIndex = $state(-1);
  let menuStyle = $state("");
  let selectedOption = $derived(options.find((option) => option.value === value));
  let selectedIndex = $derived(options.findIndex((option) => option.value === selectedOption?.value));
  let hasEnabledOptions = $derived(options.some((option) => !option.disabled));

  function opaqueColor(value: string, fallback: string) {
    const normalized = value.trim();
    const rgb = normalized.match(/^rgba?\(([^)]+)\)$/i);
    if (rgb) {
      const channels = rgb[1].split(/[\s,/]+/).filter(Boolean).slice(0, 3);
      if (channels.length === 3) return `rgb(${channels.join(" ")})`;
    }
    return /^#[0-9a-f]{3,8}$/i.test(normalized) ? normalized : fallback;
  }

  function viewportZoom() {
    const zoomValue = root ? Number.parseFloat(getComputedStyle(root.closest(".window") ?? root).zoom) : 1;
    return Number.isFinite(zoomValue) && zoomValue > 0 ? zoomValue : 1;
  }

  function portal(node: HTMLElement) {
    const placeholder = document.createComment("reflex-select-portal");
    node.parentNode?.insertBefore(placeholder, node);
    document.body.appendChild(node);

    return {
      destroy() {
        node.remove();
        placeholder.remove();
      }
    };
  }

  function optionId(index: number) {
    return `${listId}-option-${index}`;
  }

  function enabledIndex(start: number, direction: 1 | -1): number {
    if (!options.length) return -1;
    for (let offset = 0; offset < options.length; offset += 1) {
      const index = (start + offset * direction + options.length * 2) % options.length;
      if (!options[index]?.disabled) return index;
    }
    return -1;
  }

  function updateMenuPosition() {
    if (!open || !trigger) return;

    const rect = trigger.getBoundingClientRect();
    const theme = root ? getComputedStyle(root) : null;
    const themeStyle = theme
      ? [
          "--text",
          "--muted",
          "--weak",
          "--surface",
          "--surface-strong",
          "--window",
          "--line",
          "--line-strong",
          "--accent",
          "--accent-strong",
          "--accent-soft"
        ]
          .map((name) => `${name}:${theme.getPropertyValue(name).trim()}`)
          .concat(`--select-menu-bg:${opaqueColor(theme.getPropertyValue("--surface-strong"), "#ffffff")}`)
          .join(";")
      : "";
    const viewportPadding = 12;
    const zoom = viewportZoom();
    const maxWidth = Math.max(160, window.innerWidth - viewportPadding * 2);
    const width = Math.min(Math.max(rect.width, 220), maxWidth);
    const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
    const spaceAbove = rect.top - viewportPadding;
    const openAbove = spaceBelow < 180 && spaceAbove > spaceBelow;
    const availableHeight = Math.max(
      108,
      Math.min(320, openAbove ? spaceAbove : spaceBelow)
    );
    const rawLeft = rect.left;
    const left = Math.min(
      Math.max(viewportPadding, rawLeft),
      window.innerWidth - viewportPadding - width
    );
    const rawTop = openAbove ? rect.top - availableHeight - 6 : rect.bottom + 6;
    const top = Math.min(
      Math.max(viewportPadding, rawTop),
      window.innerHeight - viewportPadding - availableHeight
    );

    menuStyle = `${themeStyle};zoom:${zoom};left:${Math.round(left / zoom)}px;top:${Math.round(top / zoom)}px;width:${Math.round(width / zoom)}px;max-height:${Math.round(availableHeight / zoom)}px;`;
  }

  function startTracking() {
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
  }

  function stopTracking() {
    window.removeEventListener("resize", updateMenuPosition);
    window.removeEventListener("scroll", updateMenuPosition, true);
  }

  function closeMenu(returnFocus = false) {
    open = false;
    stopTracking();
    if (returnFocus) trigger?.focus();
  }

  function openMenu() {
    if (disabled || !hasEnabledOptions) return;
    highlightedIndex =
      selectedIndex >= 0 && !options[selectedIndex]?.disabled
        ? selectedIndex
        : enabledIndex(0, 1);
    open = true;
    startTracking();
    updateMenuPosition();
    void tick().then(updateMenuPosition);
  }

  function chooseOption(index: number) {
    const option = options[index];
    if (disabled || !hasEnabledOptions || !option || option.disabled) return;
    highlightedIndex = index;
    onValueChange?.(option.value);
    closeMenu(true);
  }

  function moveHighlight(direction: 1 | -1) {
    const start = highlightedIndex < 0 ? (direction === 1 ? 0 : options.length - 1) : highlightedIndex + direction;
    highlightedIndex = enabledIndex(start, direction);
  }

  function handleTriggerKeydown(event: KeyboardEvent) {
    if (disabled) return;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openMenu();
      } else {
        moveHighlight(event.key === "ArrowDown" ? 1 : -1);
      }
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        openMenu();
      } else if (highlightedIndex >= 0) {
        chooseOption(highlightedIndex);
      }
      return;
    }

    if (event.key === "Home" && open) {
      event.preventDefault();
      highlightedIndex = enabledIndex(0, 1);
      return;
    }

    if (event.key === "End" && open) {
      event.preventDefault();
      highlightedIndex = enabledIndex(options.length - 1, -1);
      return;
    }

    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
      return;
    }

    if (event.key === "Tab" && open) closeMenu();
  }

  function handleWindowKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
    }
  }

  function handleWindowClick(event: MouseEvent) {
    const target = event.target as Node;
    if (open && root && !root.contains(target) && !menuElement?.contains(target)) closeMenu();
  }

  $effect(() => {
    if (open && (disabled || !hasEnabledOptions)) closeMenu();
  });

  $effect(() => {
    const index = highlightedIndex;
    if (!open || index < 0) return;
    void tick().then(() => {
      if (!open || highlightedIndex !== index) return;
      document.getElementById(optionId(index))?.scrollIntoView({ block: "nearest" });
    });
  });

  onDestroy(stopTracking);
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleWindowKeydown} />

<div
  class={`ui-select ${className}`}
  class:compact={size === "compact"}
  class:full-width={fullWidth}
  class:open
  bind:this={root}
>
  <button
    class="ui-select-trigger"
    type="button"
    role="combobox"
    aria-label={ariaLabel}
    aria-haspopup="listbox"
    aria-expanded={open}
    aria-controls={listId}
    aria-activedescendant={open && highlightedIndex >= 0 ? optionId(highlightedIndex) : undefined}
    title={selectedOption?.label ?? (value ? unavailableLabel : placeholder)}
    disabled={disabled || !hasEnabledOptions}
    bind:this={trigger}
    onclick={() => (open ? closeMenu(true) : openMenu())}
    onkeydown={handleTriggerKeydown}
  >
    <span
      class:placeholder={!selectedOption && !value}
      class:unavailable={!selectedOption && Boolean(value)}
      class="ui-select-value"
    >
      {selectedOption?.label ?? (value ? unavailableLabel : placeholder)}
    </span>
    <span class="ui-select-chevron" aria-hidden="true"><ChevronDown size={16} strokeWidth={2} /></span>
  </button>

  {#if open}
    <div use:portal class="ui-select-menu" id={listId} role="listbox" aria-label={ariaLabel} style={menuStyle} bind:this={menuElement}>
      {#each options as option, index (option.value)}
        {#if option.group && (index === 0 || options[index - 1]?.group !== option.group)}
          <div class="ui-select-group" role="presentation">{option.group}</div>
        {/if}
        <button
          class="ui-select-option"
          class:selected={value === option.value}
          class:highlighted={highlightedIndex === index}
          class:disabled={option.disabled}
          id={optionId(index)}
          type="button"
          role="option"
          aria-selected={value === option.value}
          disabled={option.disabled}
          tabindex="-1"
          onclick={() => chooseOption(index)}
        >
          <span class="ui-select-option-copy">
            <span class="ui-select-option-label">{option.label}</span>
            {#if option.description}<small>{option.description}</small>{/if}
          </span>
          {#if value === option.value}<Check class="ui-select-check" size={15} strokeWidth={2.4} aria-hidden="true" />{/if}
        </button>
      {:else}
        <p class="ui-select-empty">暂无可选项</p>
      {/each}
    </div>
  {/if}
</div>

<style>
  .ui-select {
    display: block;
    min-width: 0;
    color: var(--text, #27313b);
    font: inherit;
  }

  .ui-select.full-width {
    width: 100%;
  }

  .ui-select-trigger {
    display: flex;
    width: 100%;
    min-width: 0;
    min-height: 40px;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 0 12px;
    color: var(--text, #27313b);
    font: inherit;
    font-size: var(--font-body);
    line-height: 1.2;
    text-align: left;
    background: var(--surface, #fff);
    border: 1px solid var(--line-strong, #d8dfe4);
    border-radius: 10px;
    outline: none;
    cursor: pointer;
    transition: color 160ms ease, background 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
  }

  .ui-select.compact .ui-select-trigger {
    min-height: 32px;
    padding: 0 8px;
    border-radius: 8px;
    font-size: var(--font-meta);
  }

  .ui-select-trigger:hover:not(:disabled) {
    background: color-mix(in srgb, var(--surface, #fff) 78%, var(--accent-soft, #edf2f5));
    border-color: var(--accent, #73899c);
  }

  .ui-select-trigger:focus-visible,
  .ui-select.open .ui-select-trigger {
    border-color: var(--accent, #73899c);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-soft, #edf2f5) 80%, transparent);
  }

  .ui-select-trigger:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .ui-select-value {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ui-select-value.placeholder {
    color: var(--muted, #697682);
  }

  .ui-select-value.unavailable {
    color: var(--muted, #697682);
    font-style: italic;
  }

  .ui-select-chevron {
    flex: 0 0 auto;
    color: var(--muted, #697682);
    transition: color 160ms ease, transform 160ms ease;
  }

  .ui-select.open .ui-select-chevron {
    color: var(--accent-strong, #566b7c);
    transform: rotate(180deg);
  }

  .ui-select-menu {
    position: fixed;
    z-index: 160;
    display: grid;
    gap: 2px;
    box-sizing: border-box;
    padding: 6px;
    overflow: auto;
    color: var(--text, #27313b);
    background: var(--select-menu-bg, #fff);
    border: 1px solid var(--line-strong, #d8dfe4);
    border-radius: 12px;
    box-shadow: 0 18px 40px rgb(39 49 59 / 18%), 0 2px 8px rgb(39 49 59 / 8%);
    animation: ui-select-pop 140ms ease-out;
  }

  .ui-select-group {
    padding: 7px 9px 4px;
    color: var(--muted, #697682);
    font-size: var(--font-meta);
    font-weight: 700;
    line-height: 1.2;
  }

  .ui-select-option {
    display: flex;
    width: 100%;
    min-width: 0;
    min-height: 36px;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 7px 9px;
    color: var(--text, #27313b);
    font: inherit;
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    cursor: pointer;
    transition: color 140ms ease, background 140ms ease, border-color 140ms ease;
  }

  .ui-select-option:hover:not(:disabled),
  .ui-select-option.highlighted {
    background: var(--accent-soft, #edf2f5);
    border-color: color-mix(in srgb, var(--accent, #73899c) 38%, transparent);
  }

  .ui-select-option.selected {
    color: var(--accent-strong, #566b7c);
    background: color-mix(in srgb, var(--accent-soft, #edf2f5) 72%, var(--surface, #fff));
  }

  .ui-select-option.selected.highlighted {
    background: var(--accent-soft, #edf2f5);
  }

  .ui-select-option:disabled,
  .ui-select-option.disabled {
    color: var(--muted, #697682);
    cursor: not-allowed;
    opacity: 0.6;
  }

  .ui-select-option-copy {
    display: grid;
    min-width: 0;
    gap: 2px;
  }

  .ui-select-option-label,
  .ui-select-option-copy small {
    overflow-wrap: anywhere;
  }

  .ui-select-option-label {
    line-height: 1.35;
  }

  .ui-select-option-copy small {
    color: var(--muted, #697682);
    font-size: var(--font-meta);
    line-height: 1.35;
  }

  .ui-select-check {
    flex: 0 0 auto;
    color: var(--accent-strong, #566b7c);
  }

  .ui-select-empty {
    margin: 0;
    padding: 12px 10px;
    color: var(--muted, #697682);
    font-size: var(--font-meta);
    text-align: center;
  }

  @keyframes ui-select-pop {
    from {
      opacity: 0;
      transform: translateY(-3px) scale(0.99);
    }

    to {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .ui-select-trigger,
    .ui-select-chevron,
    .ui-select-option,
    .ui-select-menu {
      transition: none;
      animation: none;
    }
  }
</style>
