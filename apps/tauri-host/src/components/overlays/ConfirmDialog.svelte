<script lang="ts">
  import { onMount } from "svelte";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";

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
  let cancelButton = $state<HTMLButtonElement>();
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

<div class="modal-layer confirm-layer" role="presentation">
  <div class="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description">
    <span class="confirm-icon warning" aria-hidden="true"><TriangleAlert size={19} strokeWidth={2} /></span>
    <h2 id="confirm-title">{title}</h2>
    <p id="confirm-description">{description}</p>
    <div class="confirm-actions">
      <button class="outline" type="button" bind:this={cancelButton} onclick={onCancel}>{cancelLabel}</button>
      <button class:danger-button={danger} class="primary small" type="button" onclick={onConfirm}>{confirmLabel}</button>
    </div>
  </div>
</div>
