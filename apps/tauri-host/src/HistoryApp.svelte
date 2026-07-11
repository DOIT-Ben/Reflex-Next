<script lang="ts">
  import { onMount } from "svelte";
  import { CapabilityBridge } from "./domain/capabilityBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import { createHistoryAdminBridge } from "./domain/historyAdminBridge";
  import { appendHistoryPage, createHistoryState, failHistoryQuery, selectHistoryItem, startHistoryQuery, type HistoryPage, type HistorySummary } from "./domain/historyState";

  let capability: CapabilityBridge | null = null;
  let admin: ReturnType<typeof createHistoryAdminBridge> | null = null;
  let state = createHistoryState();
  let search = "";
  let scene = "";
  let style = "";
  let provider = "";
  let exportFormat: "json" | "csv" | "markdown" = "json";
  let detail: Record<string, unknown> | null = null;
  let busy = "";

  onMount(() => { void createTauriHostApi().then((host) => { if (host) { capability = new CapabilityBridge(host); admin = createHistoryAdminBridge(host); void load({}); } else { state = { ...state, phase: "error", error: "历史记录暂时不可用，请稍后重试。" }; } }); });

  async function load(query: Record<string, string>, more = false) {
    const started = more ? { state: { ...state, phase: "loading-more" as const }, request: state.request } : startHistoryQuery(state, query);
    state = started.state;
    try {
      const input = { keyword: state.query.search ?? "", filters: { scene: state.query.scene, style: state.query.style, provider: state.query.provider }, page_size: 30, sort: "created_at", direction: "desc", ...(more && state.cursor ? { cursor: state.cursor } : {}) };
      if (!capability) throw new Error();
      for await (const event of capability.invoke("history-sqlite", "list", input)) {
        if (event.status === "result") state = appendHistoryPage(state, started.request, event.data as unknown as HistoryPage);
      }
    } catch { state = failHistoryQuery(state, started.request, "历史记录暂时不可用，请稍后重试。"); }
  }

  async function open(item: HistorySummary) {
    state = selectHistoryItem(state, item.id); detail = null;
    const request = state.detailRequest;
    try { if (!capability) throw new Error(); for await (const event of capability.invoke("history-sqlite", "detail", { id: item.id })) if (event.status === "result" && state.detailRequest === request && state.selectedId === item.id) detail = (event.data.record ?? {}) as Record<string, unknown>; }
    catch { detail = { message: "无法加载这条历史记录。" }; }
  }

  async function rate(rating: number) {
    if (!state.selectedId) return;
    try { if (!capability) throw new Error(); for await (const _ of capability.invoke("history-sqlite", "rate", { id: state.selectedId, rating })) {} await load(state.query); } catch { busy = "评分未保存，请稍后重试。"; }
  }

  async function operate(operation: "delete" | "clear" | "repair" | "restore" | "rotate") {
    busy = "正在处理历史记录...";
    try { if (!admin) throw new Error(); await admin.run(operation, operation === "delete" && state.selectedId ? { id: state.selectedId } : {}); detail = null; await load(state.query); busy = ""; }
    catch { busy = "历史操作失败，请稍后重试。"; }
  }

  async function exportHistory() { busy = "正在导出历史记录..."; try { if (!admin) throw new Error(); await admin.exportHistory(exportFormat, state.query); busy = ""; } catch { busy = "历史导出失败，请稍后重试。"; } }

  async function reuse(kind: "input" | "result") { if (!state.selectedId) return; try { await hostInvoke("history_reuse_intent", { intent: { kind, history_id: state.selectedId } }); busy = "已发送到主窗口。"; } catch { busy = "无法载入这条历史记录。"; } }
  async function hostInvoke(command: string, args: Record<string, unknown>) { const host = await createTauriHostApi(); if (!host) throw new Error(); return host.invoke(command, args); }
</script>

<main class="history-shell">
  <header class="history-head"><div><strong>Reflex</strong><span>历史记录</span></div><div class="history-actions"><select aria-label="导出格式" bind:value={exportFormat}><option value="json">JSON</option><option value="csv">CSV</option><option value="markdown">Markdown</option></select><button aria-label="导出历史记录" on:click={exportHistory}>导出</button><button aria-label="修复历史记录" on:click={() => operate("repair")}>修复</button></div></header>
  <section class="history-tools"><input aria-label="搜索历史记录" bind:value={search} placeholder="搜索历史记录" /><select aria-label="场景筛选" bind:value={scene}><option value="">全部场景</option><option value="general">通用</option><option value="email">邮件</option></select><select aria-label="风格筛选" bind:value={style}><option value="">全部风格</option><option value="balanced">平衡</option><option value="concise">简洁</option></select><select aria-label="Provider 筛选" bind:value={provider}><option value="">全部 Provider</option><option value="minimax">MiniMax</option></select><button on:click={() => load({ search, scene, style, provider })}>筛选</button></section>
  {#if busy}<p class="history-notice">{busy}</p>{/if}
  <section class="history-workspace">
    <aside class="history-list" aria-label="历史记录列表">
      {#if state.phase === "loading"}<p class="history-state">正在加载历史记录...</p>
      {:else if state.phase === "empty"}<p class="history-state">暂无历史记录。</p>
      {:else if state.phase === "error"}<p class="history-state error">{state.error}</p>
      {:else}{#each state.items as item (item.id)}<button class:active={item.id === state.selectedId} class="history-row" on:click={() => open(item)}><time>{item.created_at}</time><span>{item.scene} · {item.style}</span><small>{item.provider} · {item.rating ?? "未评分"}</small></button>{/each}{#if state.cursor}<button class="more" on:click={() => load(state.query, true)} disabled={state.phase === "loading-more"}>{state.phase === "loading-more" ? "正在加载..." : "加载更多"}</button>{/if}{/if}
    </aside>
    <article class="history-detail">
      {#if !state.selectedId}<p class="history-state">选择一条历史记录查看详情。</p>
      {:else if !detail}<p class="history-state">正在加载详情...</p>
      {:else}<div class="detail-actions"><span>评分</span>{#each [1,2,3,4,5] as score}<button aria-label={`评分 ${score}`} on:click={() => rate(score)}>{score}</button>{/each}<button aria-label="删除当前历史记录" on:click={() => operate("delete")}>删除</button></div><dl class="history-fields"><div><dt>场景</dt><dd>{detail.scene ?? "-"}</dd></div><div><dt>Provider</dt><dd>{detail.provider ?? "-"}</dd></div><div><dt>模式</dt><dd>{detail.mode ?? "-"}</dd></div><div><dt>耗时</dt><dd>{detail.duration_ms ?? "-"}</dd></div></dl><h2>原文</h2><pre>{detail.input ?? ""}</pre><h2>结果</h2><pre>{detail.output ?? ""}</pre><div class="detail-actions"><button on:click={() => reuse("input")}>载入原文</button><button on:click={() => reuse("result")}>使用结果</button><button on:click={() => operate("clear")}>清空历史</button><button on:click={() => operate("restore")}>恢复备份</button><button on:click={() => operate("rotate")}>轮换密钥</button></div>{/if}
    </article>
  </section>
</main>
