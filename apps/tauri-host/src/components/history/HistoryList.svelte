<script lang="ts">
  import { translator } from "../../domain/i18nStore";
  import type { HistoryState, HistorySummary } from "../../domain/historyState";
  import EmptyState from "../ui/EmptyState.svelte";

  interface Props {
    state: HistoryState;

    sceneLabel: (id: string) => string;
    styleLabel: (id: string) => string;
    onSelect: (item: HistorySummary) => void;
    onMore: () => void;
  }

  let { state, sceneLabel, styleLabel, onSelect, onMore }: Props = $props();
  let translate = $derived($translator);
</script>

<aside class="history-list" aria-label={translate("历史记录列表")}>
  {#if state.phase === "loading"}<p class="history-state">{translate("正在加载历史记录...")}</p>
  {:else if state.phase === "empty"}<EmptyState title={translate("暂无历史记录。")} detail={translate("完成一次处理后，记录会出现在这里。")} />
  {:else if state.phase === "error"}<EmptyState tone="error" title={translate("历史记录尚未开启")} detail={translate(state.error ?? "历史记录暂时不可用，请稍后重试。")} />
  {:else}
    {#each state.items as item (item.id)}
      <button class:active={item.id === state.selectedId} class="history-row" type="button" onclick={() => onSelect(item)}>
        <time>{item.created_at}</time><span>{sceneLabel(item.scene)} · {styleLabel(item.style)}</span><small>{item.provider} · {item.rating ?? translate("未评分")}</small>
      </button>
    {/each}
    {#if state.cursor}<button class="more" type="button" onclick={onMore} disabled={state.phase === "loading-more"}>{translate(state.phase === "loading-more" ? "正在加载..." : "加载更多")}</button>{/if}
  {/if}
</aside>
