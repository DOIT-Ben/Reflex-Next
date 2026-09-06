<script lang="ts">
  import DialogShell from "../ui/DialogShell.svelte";
  import type { TranslationState, TranslationTarget } from "../../domain/translationState";

  interface Props {
    state: TranslationState;
    sourceLanguageLabel: string;
    targetLanguageLabel: string;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onTargetChange: (target: TranslationTarget) => void;
    onCancel: () => void;
    onRetry: () => void;
    onCopy: () => void;
    onUseResult: () => void;
    onClose: () => void;
  }

  let {
    state,
    sourceLanguageLabel,
    targetLanguageLabel,
    translate,
    onTargetChange,
    onCancel,
    onRetry,
    onCopy,
    onUseResult,
    onClose
  }: Props = $props();

  const targets: Array<{ id: TranslationTarget; label: string }> = [
    { id: "auto", label: "自动" },
    { id: "zh", label: "中文" },
    { id: "en", label: "English" }
  ];

  $: description = state.sourceLanguage && state.targetLanguage
    ? `${sourceLanguageLabel} → ${targetLanguageLabel}`
    : "";
</script>

<DialogShell
  title={translate("翻译结果")}
  {description}
  z={8}
  closeLabel={translate("关闭翻译")}
  onClose={onClose}
  size="md"
>
  <div class="translation-toolbar">
    <span>{translate("目标语言")}</span>
    <div class="translation-segments" role="group" aria-label={translate("目标语言")}>
      {#each targets as item}
        <button
          type="button"
          class:active={state.target === item.id}
          aria-pressed={state.target === item.id}
          disabled={state.phase === "streaming"}
          onclick={() => onTargetChange(item.id)}
        >{translate(item.label)}</button>
      {/each}
    </div>
  </div>

  <div class="translation-content">
    <section class="translation-pane" aria-label={translate("原文")}>
      <h3>{translate("原文")}</h3>
      <pre>{state.sourceText}</pre>
    </section>
    <section class="translation-pane translated" aria-label={translate("译文")} aria-live="polite">
      <h3>{translate("译文")}</h3>
      {#if state.phase === "error"}
        <p class="translation-message error">{translate(state.error ?? "翻译结果不可用，请重试。")}</p>
      {:else if state.phase === "cancelled" && !state.translatedText}
        <p class="translation-message">{translate("翻译已取消。")}</p>
      {:else if state.translatedText}
        <pre>{state.translatedText}</pre>
      {:else if state.phase === "streaming"}
        <p class="translation-message">{translate("正在翻译…")}</p>
      {:else}
        <p class="translation-message">{translate("准备翻译")}</p>
      {/if}
    </section>
  </div>

  <footer slot="footer">
    {#if state.phase === "streaming"}
      <button class="outline" type="button" onclick={onCancel}>{translate("取消翻译")}</button>
    {:else}
      <button class="outline" type="button" onclick={onRetry}>{translate(state.phase === "completed" ? "重新翻译" : "重试")}</button>
    {/if}
    {#if state.phase === "completed"}
      <button class="outline" type="button" onclick={onCopy}>{translate("复制译文")}</button>
      <button class="primary small" type="button" onclick={onUseResult}>{translate("作为当前结果")}</button>
    {/if}
  </footer>
</DialogShell>
