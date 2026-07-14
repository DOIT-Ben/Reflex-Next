<script lang="ts">
  import type { HistoryState, HistorySummary } from "../../domain/historyState";

  interface Props {
    state: HistoryState;
    translate: (source: string, values?: Record<string, string | number>) => string;
    sceneLabel: (id: string) => string;
    styleLabel: (id: string) => string;
    onSelect: (item: HistorySummary) => void;
    onMore: () => void;
  }

  let { state, translate, sceneLabel, styleLabel, onSelect, onMore }: Props = $props();
</script>

<aside class="history-list" aria-label={translate("历史记录列表")}>
  {#if state.phase === "loading"}<p class="history-state">{translate("正在加载历史记录...")}</p>
  {:else if state.phase === "empty"}<p class="history-state">{translate("暂无历史记录。")}</p>
  {:else if state.phase === "error"}<p class="history-state error">{translate(state.error ?? "历史记录暂时不可用，请稍后重试。")}</p>
  {:else}
    {#each state.items as item (item.id)}
      <button class:active={item.id === state.selectedId} class="history-row" type="button" onclick={() => onSelect(item)}>
        <time>{item.created_at}</time><span>{sceneLabel(item.scene)} · {styleLabel(item.style)}</span><small>{item.provider} · {item.rating ?? translate("未评分")}</small>
      </button>
    {/each}
    {#if state.cursor}<button class="more" type="button" onclick={onMore} disabled={state.phase === "loading-more"}>{translate(state.phase === "loading-more" ? "正在加载..." : "加载更多")}</button>{/if}
  {/if}
</aside>
