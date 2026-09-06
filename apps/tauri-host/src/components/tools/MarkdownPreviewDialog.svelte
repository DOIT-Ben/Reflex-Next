<script lang="ts">
  import DialogShell from "../ui/DialogShell.svelte";
  import type { MarkdownPreviewMode, MarkdownPreviewState } from "../../domain/markdownPreviewState";

  interface Props {
    state: MarkdownPreviewState;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onModeChange: (mode: MarkdownPreviewMode) => void;
    onCopySource: () => void;
    onRetry: () => void;
    onClose: () => void;
  }

  let { state, translate, onModeChange, onCopySource, onRetry, onClose }: Props = $props();
  const modes: Array<{ id: MarkdownPreviewMode; label: string }> = [
    { id: "split", label: "分栏" },
    { id: "source", label: "源码" },
    { id: "preview", label: "预览" }
  ];
</script>

<DialogShell title={translate("Markdown 预览")} z={9} closeLabel={translate("关闭 Markdown 预览")} onClose={onClose} size="lg">
  <div class="markdown-toolbar">
    <div class="markdown-segments" role="group" aria-label={translate("预览方式")}>
      {#each modes as item}
        <button type="button" class:active={state.mode === item.id} aria-pressed={state.mode === item.id} onclick={() => onModeChange(item.id)}>{translate(item.label)}</button>
      {/each}
    </div>
    <button class="outline" type="button" onclick={onCopySource}>{translate("复制源码")}</button>
  </div>
  <div class:source-only={state.mode === "source"} class:preview-only={state.mode === "preview"} class="markdown-content">
    <section class="markdown-source" aria-label={translate("Markdown 源码")}>
      <h3>{translate("源码")}</h3>
      <pre>{state.sourceText}</pre>
    </section>
    <section class="markdown-rendered" aria-label={translate("渲染预览")} aria-live="polite">
      <h3>{translate("预览")}</h3>
      {#if state.phase === "loading"}
        <p class="markdown-message">{translate("正在渲染…")}</p>
      {:else if state.phase === "error"}
        <p class="markdown-message error">{translate(state.error ?? "Markdown 预览暂时不可用，请重试。")}</p>
      {:else}
        <article>{@html state.html}</article>
      {/if}
    </section>
  </div>
  <footer slot="footer">
    {#if state.phase === "error"}<button class="outline" type="button" onclick={onRetry}>{translate("重试")}</button>{/if}
    <button class="primary small" type="button" onclick={onClose}>{translate("关闭")}</button>
  </footer>
</DialogShell>
