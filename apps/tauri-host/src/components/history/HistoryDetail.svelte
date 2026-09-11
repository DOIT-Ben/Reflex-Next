<script lang="ts">
  import { translator } from "../../domain/i18nStore";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import { historyElapsedLabel, type HistoryState } from "../../domain/historyState";
  import EmptyState from "../ui/EmptyState.svelte";

  interface Props {
    state: HistoryState;
    detail: Record<string, unknown> | null;
    sceneLabel: (id: string) => string;
    onRate: (score: number) => void;
    onDelete: () => void;
    onReuseInput: () => void;
    onReuseResult: () => void;
  }

  let { state, detail, sceneLabel, onRate, onDelete, onReuseInput, onReuseResult }: Props = $props();
  let translate = $derived($translator);
</script>

<article class="history-detail">
  {#if !state.selectedId}<EmptyState title={translate("选择一条记录")} detail={translate("在左侧查看处理时间、场景和评分。")} />
  {:else if !detail}<p class="history-state" role="status" aria-live="polite">{translate("正在加载详情...")}</p>
  {:else if typeof detail.error === "string"}<p class="history-state error" role="alert">{translate(detail.error)}</p>
  {:else}
    <div class="detail-actions history-rating"><span>{translate("评分")}</span>{#each [1, 2, 3, 4, 5] as score}<button type="button" aria-label={`${translate("评分")} ${score}`} aria-pressed={detail.rating === score} onclick={() => onRate(score)}>{score}</button>{/each}<button class="danger-icon" type="button" aria-label={translate("删除当前历史记录")} title={translate("删除当前历史记录")} onclick={onDelete}><Trash2 size={15} strokeWidth={2} /></button></div>
    <dl class="history-fields">
      <div><dt>{translate("场景")}</dt><dd>{typeof detail.scene === "string" ? sceneLabel(detail.scene) : "-"}</dd></div>
      <div><dt>Provider</dt><dd>{detail.provider ?? "-"}</dd></div>
      <div><dt>{translate("模式")}</dt><dd>{typeof detail.mode === "string" ? translate(detail.mode === "prompt" ? "提示词生成" : "内容优化") : "-"}</dd></div>
      <div><dt>{translate("耗时")}</dt><dd>{historyElapsedLabel(detail)}</dd></div>
    </dl>
    <h2>{translate("原文")}</h2><pre>{detail.input ?? ""}</pre>
    <h2>{translate("结果")}</h2><pre>{detail.output ?? ""}</pre>
    <div class="detail-actions"><button type="button" onclick={onReuseInput}>{translate("载入原文")}</button><button type="button" onclick={onReuseResult}>{translate("使用结果")}</button></div>
  {/if}
</article>
