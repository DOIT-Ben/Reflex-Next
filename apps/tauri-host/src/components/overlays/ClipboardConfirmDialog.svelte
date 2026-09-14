<script lang="ts">
  import { onMount } from "svelte";
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";
  import { Button } from "@/components/ui/button";
  import DialogShell from "../ui/DialogShell.svelte";
  import { translator } from "../../domain/i18nStore";

  interface Props {
    notice: string | null;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let { notice, onCancel, onConfirm }: Props = $props();
  let translate = $derived($translator);
  let cancelButton = $state<HTMLButtonElement | null>(null);
  onMount(() => cancelButton?.focus());
</script>

<DialogShell title={translate("替换当前剪贴板内容？")} description={translate("原剪贴板内容会被本次结果覆盖。首次使用需要确认，之后可在设置中修改。")} z={80} size="sm">
  <span class="confirm-icon" aria-hidden="true"><ClipboardPaste size={19} strokeWidth={2} /></span>
  {#if notice}<p class="clipboard-feedback" aria-live="polite">{translate(notice)}</p>{/if}
  <div>
    <Button variant="outline" size="sm" bind:ref={cancelButton} onclick={onCancel}>{translate("取消")}</Button>
    <Button size="sm" onclick={onConfirm}>{translate("确认替换")}</Button>
  </div>
</DialogShell>
