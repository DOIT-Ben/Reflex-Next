<script lang="ts">
  import DialogShell from "../ui/DialogShell.svelte";
  import { translator } from "../../domain/i18nStore";

  interface Props {
    sourceText: string;
    output: string;
    onCopySource: () => void;
    onCopyOutput: () => void;
    onClose: () => void;
  }

  let { sourceText, output, onCopySource, onCopyOutput, onClose }: Props = $props();
  let translate = $derived($translator);
</script>

<DialogShell title={translate("结果对比")} z={8} closeLabel={translate("关闭结果对比")} onClose={onClose} size="lg">
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
  <footer slot="footer">
    <button class="primary small" type="button" onclick={onClose}>{translate("关闭")}</button>
  </footer>
</DialogShell>
