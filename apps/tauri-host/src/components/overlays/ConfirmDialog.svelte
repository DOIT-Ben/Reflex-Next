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

<DialogShell title={title} description={description} z={80} size="sm">
    <span class="confirm-icon warning" aria-hidden="true"><TriangleAlert size={19} strokeWidth={2} /></span>
    <div class="confirm-actions">
      <Button variant="outline" size="sm" bind:ref={cancelButton} onclick={onCancel}>{cancelLabel}</Button>
      <Button variant={danger ? "destructive" : "default"} size="sm" onclick={onConfirm}>{confirmLabel}</Button>
    </div>
  </DialogShell>
