<script lang="ts">
  import { onMount } from "svelte";
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";

  interface Props {
    notice: string | null;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let { notice, translate, onCancel, onConfirm }: Props = $props();
  let cancelButton: HTMLButtonElement;
  onMount(() => cancelButton?.focus());
</script>

<div class="modal-layer" role="presentation">
  <div class="clipboard-modal" role="dialog" aria-modal="true" aria-label={translate("替换剪贴板确认")}>
    <span class="confirm-icon" aria-hidden="true"><ClipboardPaste size={19} strokeWidth={2} /></span>
    <h2>{translate("替换当前剪贴板内容？")}</h2>
    <p>{translate("原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。")}</p>
    {#if notice}<p class="clipboard-feedback" aria-live="polite">{translate(notice)}</p>{/if}
    <div>
      <button class="outline" type="button" bind:this={cancelButton} onclick={onCancel}>{translate("取消")}</button>
      <button class="primary small" type="button" onclick={onConfirm}>{translate("确认替换")}</button>
    </div>
  </div>
</div>
