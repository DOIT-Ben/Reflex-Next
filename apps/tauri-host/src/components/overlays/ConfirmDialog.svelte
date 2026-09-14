<script lang="ts">
  import { onMount } from "svelte";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "@/components/ui/button";
  import DialogShell from "../ui/DialogShell.svelte";

  interface Props {
    title: string;
    description: string;
    confirmLabel: string;
    cancelLabel: string;
    danger?: boolean;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let { title, description, confirmLabel, cancelLabel, danger = false, onCancel, onConfirm }: Props = $props();
  let cancelButton = $state<HTMLButtonElement | null>(null);
  onMount(() => {
    cancelButton?.focus();
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      onCancel();
    };
    window.addEventListener("keydown", handleKeydown, true);
    return () => window.removeEventListener("keydown", handleKeydown, true);
  });
</script>

<!-- CC Switch 确认框形态：图标与标题同行，按钮放 footer 按钮带并使用默认尺寸 -->
{#snippet icon()}
  <TriangleAlert size={18} strokeWidth={2} class={danger ? "text-destructive" : "text-blue-500"} />
{/snippet}

<DialogShell title={title} description={description} z={80} size="sm" {icon}>
  {#snippet footer()}
    <Button variant="outline" bind:ref={cancelButton} onclick={onCancel}>{cancelLabel}</Button>
    <Button variant={danger ? "destructive" : "default"} onclick={onConfirm}>{confirmLabel}</Button>
  {/snippet}
</DialogShell>
