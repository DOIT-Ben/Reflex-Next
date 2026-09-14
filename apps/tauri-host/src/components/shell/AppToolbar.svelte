<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import { Button } from "@/components/ui/button";
  import { cn } from "@/utils.js";
  import type { Snippet } from "svelte";

  export type ToolbarItem = {
    id: string;
    label: string;
    disabled?: boolean;
  };

  interface Props {
    items: ToolbarItem[];
    activeId: string | null;
    providerLabel?: string;
    onSelect: (id: string) => void;
    onCommand?: () => void;
    actions?: Snippet;
  }

  let { items, activeId, providerLabel = "", onSelect, onCommand, actions }: Props = $props();
</script>

<!-- 顶部工具栏：与 CC Switch 同构（品牌 + bg-muted 圆角分段快捷导航 + 状态/命令入口） -->
<header class="app-toolbar">
  <div class="app-toolbar-brand">
    <span class="app-mark" aria-hidden="true">R</span>
    <strong>Reflex</strong>
  </div>

  <div class="toolbar-shortcuts">
    {#each items as item (item.id)}
      <Button
        variant={activeId === item.id ? "secondary" : "ghost"}
        size="sm"
        disabled={item.disabled}
        aria-label={item.label}
        title={item.label}
        class={cn(
          "h-8 gap-1.5 px-2.5 text-muted-foreground transition-all duration-200 ease-in-out hover:text-foreground",
          activeId === item.id && "bg-background text-foreground shadow-sm"
        )}
        onclick={() => onSelect(item.id)}
      >
        <span class="text-xs font-medium">{item.label}</span>
      </Button>
    {/each}
  </div>

  <div class="toolbar-spacer"></div>

  {#if providerLabel}
    <span class="toolbar-provider" title={providerLabel}>{providerLabel}</span>
  {/if}

  {#if actions}
    {@render actions()}
  {/if}

  {#if onCommand}
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="搜索命令"
      title="搜索命令 (Ctrl+K)"
      class="text-muted-foreground hover:text-foreground"
      onclick={onCommand}
    >
      <Search size={15} strokeWidth={2} />
    </Button>
  {/if}
</header>
