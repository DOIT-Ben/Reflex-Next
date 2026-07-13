<script lang="ts">
  import type { NavRailItem } from "./types";

  interface Props {
    items?: NavRailItem[];
    activeId?: string | null;
    ariaLabel?: string;
    onSelect?: (id: string) => void;
  }

  const defaultItems: NavRailItem[] = [
    { id: "workbench", label: "工作台", symbol: "⌂" },
    { id: "templates", label: "模板", symbol: "▤" },
    { id: "batch", label: "批处理", symbol: "≋" },
    { id: "translation", label: "翻译", symbol: "译" },
    { id: "markdown", label: "Markdown 预览", symbol: "M" },
    { id: "plugins", label: "插件", symbol: "⊞" },
    { id: "history", label: "历史", symbol: "◷", group: "utility" },
    { id: "settings", label: "设置", symbol: "⚙", shortcut: "Ctrl+,", group: "utility" }
  ];

  let {
    items = defaultItems,
    activeId = "workbench",
    ariaLabel = "主导航",
    onSelect
  }: Props = $props();
</script>

<nav class="nav-rail" aria-label={ariaLabel}>
  {#each items as item, index (item.id)}
    {#if item.group === "utility" && (index === 0 || items[index - 1]?.group !== "utility")}
      <span class="rail-spacer" aria-hidden="true"></span>
    {/if}
    <button
      type="button"
      class:active={activeId === item.id}
      aria-label={item.label}
      aria-current={activeId === item.id ? "page" : undefined}
      title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label}
      disabled={item.disabled || !onSelect}
      onclick={() => onSelect?.(item.id)}
    >
      <span class="active-mark" aria-hidden="true"></span>
      <span class="nav-symbol" aria-hidden="true">{item.symbol}</span>
    </button>
  {/each}
</nav>

<style>
  .nav-rail {
    display: flex;
    flex: 0 0 48px;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    width: 48px;
    min-height: 0;
    padding: 7px 0;
    background: var(--surface, #fff);
    border-right: 1px solid var(--line, #e1e6ee);
    box-sizing: border-box;
  }

  .rail-spacer {
    flex: 1 1 auto;
    min-height: 8px;
  }

  button {
    position: relative;
    display: grid;
    flex: 0 0 34px;
    place-items: center;
    width: 36px;
    height: 34px;
    padding: 0;
    overflow: hidden;
    color: var(--muted, #697386);
    background: transparent;
    border: 0;
    border-radius: 8px;
    font: inherit;
    cursor: pointer;
    transition: color 140ms ease, background 140ms ease, transform 100ms ease;
  }

  button:hover:not(:disabled) {
    color: var(--text, #202535);
    background: color-mix(in srgb, var(--accent-soft, #eef1ff) 68%, transparent);
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
    opacity: 0.4;
  }

  button.active {
    color: var(--accent, #5065c7);
    background: var(--accent-soft, #eef1ff);
  }

  .active-mark {
    position: absolute;
    top: 8px;
    left: 0;
    width: 2px;
    height: 18px;
    background: transparent;
    border-radius: 0 2px 2px 0;
  }

  button.active .active-mark {
    background: var(--accent, #5065c7);
  }

  .nav-symbol {
    font-family: "Segoe UI Symbol", "Microsoft YaHei UI", sans-serif;
    font-size: 15px;
    font-weight: 600;
    line-height: 1;
  }

  @media (max-height: 540px) {
    .nav-rail {
      gap: 2px;
      padding-block: 5px;
    }

    button {
      flex-basis: 32px;
      height: 32px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    button {
      transition: none;
    }
  }
</style>
