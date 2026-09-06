<script lang="ts">
  import { onMount } from "svelte";
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";
  import BaseButton from "../ui/BaseButton.svelte";
  import DialogShell from "../ui/DialogShell.svelte";

  interface Props {
    notice: string | null;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let { notice, translate, onCancel, onConfirm }: Props = $props();
  let cancelButton: { focus: () => void };
  onMount(() => cancelButton?.focus());
</script>

<DialogShell title={translate("替换当前剪贴板内容？")} description={translate("原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。")} z={80} size="sm">
  <span class="confirm-icon" aria-hidden="true"><ClipboardPaste size={19} strokeWidth={2} /></span>
  {#if notice}<p class="clipboard-feedback" aria-live="polite">{translate(notice)}</p>{/if}
  <div>
    <BaseButton variant="secondary" bind:this={cancelButton} onclick={onCancel}>{translate("取消")}</BaseButton>
    <BaseButton variant="primary" onclick={onConfirm}>{translate("确认替换")}</BaseButton>
  </div>
</DialogShell>
