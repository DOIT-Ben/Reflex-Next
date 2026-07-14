<script lang="ts">
  import { onMount } from "svelte";
  import Command from "@lucide/svelte/icons/command";
  import X from "@lucide/svelte/icons/x";

  export type CommandItem = {
    id: string;
    label: string;
    disabled?: boolean;
    run: () => void;
  };

  interface Props {
    items: CommandItem[];
    translate: (source: string, values?: Record<string, string | number>) => string;
    onClose: () => void;
  }

  let { items, translate, onClose }: Props = $props();
  let firstAction = $state<HTMLButtonElement>();
  onMount(() => firstAction?.focus());
</script>

<div class="command-layer" role="presentation">
  <div class="command-dialog" role="dialog" aria-modal="true" aria-label={translate("命令面板")}>
    <header>
      <span class="command-title"><Command size={16} strokeWidth={2} /><strong>{translate("命令")}</strong></span>
      <button type="button" aria-label={translate("关闭命令面板")} onclick={onClose}><X size={16} strokeWidth={2} /></button>
    </header>
    <div class="command-list">
      {#if items[0]}
        <button bind:this={firstAction} type="button" disabled={items[0].disabled} onclick={items[0].run}>{translate(items[0].label)}</button>
      {/if}
      {#each items.slice(1) as item (item.id)}
        <button type="button" disabled={item.disabled} onclick={item.run}>{translate(item.label)}</button>
      {/each}
    </div>
  </div>
</div>
