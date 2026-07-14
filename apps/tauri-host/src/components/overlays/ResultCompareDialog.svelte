<script lang="ts">
  import { onMount } from "svelte";
  import X from "@lucide/svelte/icons/x";

  interface Props {
    sourceText: string;
    output: string;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onCopySource: () => void;
    onCopyOutput: () => void;
    onClose: () => void;
  }

  let { sourceText, output, translate, onCopySource, onCopyOutput, onClose }: Props = $props();
  let closeButton: HTMLButtonElement;
  onMount(() => closeButton?.focus());
</script>

<div class="translation-layer" role="presentation">
  <div class="translation-dialog" role="dialog" aria-modal="true" aria-label={translate("结果对比")}>
    <header class="translation-head">
      <div><h2>{translate("结果对比")}</h2></div>
      <button class="icon-button" type="button" aria-label={translate("关闭结果对比")} bind:this={closeButton} onclick={onClose}><X size={17} strokeWidth={2} /></button>
    </header>
    <div class="translation-content">
      <section class="translation-pane" aria-label={translate("原文")}>
        <div class="translation-pane-head"><h3>{translate("原文")}</h3><button class="outline small" type="button" onclick={onCopySource}>{translate("复制")}</button></div>
        <pre>{sourceText}</pre>
      </section>
      <section class="translation-pane translated" aria-label={translate("优化结果")}>
        <div class="translation-pane-head"><h3>{translate("优化结果")}</h3><button class="outline small" type="button" onclick={onCopyOutput}>{translate("复制")}</button></div>
        <pre>{output}</pre>
      </section>
    </div>
    <footer class="translation-footer"><button class="primary small" type="button" onclick={onClose}>{translate("关闭")}</button></footer>
  </div>
</div>
