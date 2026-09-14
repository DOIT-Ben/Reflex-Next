<script lang="ts">
  import { onMount } from "svelte";
  import Command from "@lucide/svelte/icons/command";
  import DialogShell from "../ui/DialogShell.svelte";
  import { Button } from "@/components/ui/button";
  import { Input } from "@/components/ui/input";
  import { cn } from "@/utils.js";
  import { translator } from "../../domain/i18nStore";

  export type CommandItem = {
    id: string;
    label: string;
    disabled?: boolean;
    run: () => void;
  };

  interface Props {
    items: CommandItem[];
    onClose: () => void;
  }

  let { items, onClose }: Props = $props();
  let translate = $derived($translator);
  let query = $state("");
  let searchInput = $state<HTMLInputElement | null>(null);

  const visibleItems = $derived(
    items.filter((item) =>
      translate(item.label).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
    )
  );

  onMount(() => searchInput?.focus());

  function runItem(item: CommandItem) {
    item.run();
  }
</script>

<DialogShell
  title={translate("命令")}
  description={translate("搜索并执行命令")}
  size="md"
  z={60}
  closeLabel={translate("关闭命令面板")}
  autofocusClose={false}
  onClose={onClose}
>
  <div class="command-panel">
    <div class="command-search">
      <span class="command-search-icon" aria-hidden="true"><Command size={15} strokeWidth={2} /></span>
      <Input
        bind:ref={searchInput}
        class="h-9 border-0 pl-8 shadow-none focus-visible:ring-0"
        value={query}
        aria-label={translate("搜索命令")}
        placeholder={translate("搜索命令")}
        oninput={(event) => (query = event.currentTarget.value)}
        onkeydown={(event) => {
          if (event.key === "Enter" && visibleItems[0]) runItem(visibleItems[0]);
        }}
      />
    </div>

    <div class="command-list" role="listbox" aria-label={translate("命令列表")}>
      {#each visibleItems as item, index (item.id)}
        <Button
          variant="ghost"
          class={cn(
            "h-9 w-full justify-start gap-2 px-2 text-sm font-normal text-muted-foreground",
            index === 0 && "bg-muted text-foreground"
          )}
          disabled={item.disabled}
          onclick={() => runItem(item)}
        >
          {translate(item.label)}
        </Button>
      {/each}
      {#if visibleItems.length === 0}
        <p class="command-empty">{translate("没有匹配的命令")}</p>
      {/if}
    </div>
  </div>
</DialogShell>

<style>
  .command-panel {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .command-search {
    position: relative;
    display: flex;
    align-items: center;
    padding-bottom: 10px;
    border-bottom: 1px solid hsl(var(--border));
  }

  .command-search-icon {
    position: absolute;
    top: calc(50% - 5px);
    left: 10px;
    display: grid;
    color: hsl(var(--muted-foreground));
    pointer-events: none;
    transform: translateY(-50%);
  }

  .command-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: min(360px, calc(90vh - 220px));
    overflow-y: auto;
  }

  .command-empty {
    margin: 0;
    padding: 12px 8px;
    color: hsl(var(--muted-foreground));
    font-size: var(--font-body);
    line-height: var(--leading-body);
  }
</style>
