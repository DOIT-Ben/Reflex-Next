<script lang="ts">
  import { onMount } from "svelte";
  import { CapabilityBridge } from "./domain/capabilityBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import { createHistoryAdminBridge } from "./domain/historyAdminBridge";
  import { appendHistoryPage, applyHistoryRatingToDetail, createHistoryState, failHistoryQuery, historyElapsedLabel, historyExportFilters, historyScanMessage, normalizeHistoryBackups, removeHistoryItem, selectHistoryItem, startHistoryQuery, updateHistoryRating, type HistoryBackup, type HistoryPage, type HistorySummary } from "./domain/historyState";
  import { listSceneOptions } from "./domain/reflexSession";

  const scenes = listSceneOptions();
  const styles = [
    { id: "concise", label: "简洁" },
    { id: "balanced", label: "平衡" },
    { id: "detailed", label: "详细" },
    { id: "creative", label: "创意" }
  ];

  let capability: CapabilityBridge | null = null;
  let admin: ReturnType<typeof createHistoryAdminBridge> | null = null;
  let state = createHistoryState();
  let search = "";
  let scene = "";
  let style = "";
  let provider = "";
  let exportFormat: "json" | "csv" | "markdown" = "json";
  let detail: Record<string, unknown> | null = null;
  let backups: HistoryBackup[] = [];
  let selectedBackupId = "";
  let busy = "";

  onMount(() => {
    void createTauriHostApi().then((host) => {
      if (!host) {
        state = { ...state, phase: "error", error: "历史记录暂时不可用，请稍后重试。" };
        return;
      }
      capability = new CapabilityBridge(host);
      admin = createHistoryAdminBridge(host);
      void load({});
      void loadBackups();
    });
  });

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
    const selectedId = state.selectedId;
    const detailRequest = state.detailRequest;
    try {
      if (!capability) throw new Error();
      for await (const _ of capability.invoke("history-sqlite", "rate", { id: selectedId, rating })) {}
      state = updateHistoryRating(state, selectedId, rating);
      detail = applyHistoryRatingToDetail(state, detail, selectedId, detailRequest, rating);
      busy = "评分已保存。";
    } catch { busy = "评分未保存，请稍后重试。"; }
  }

  async function operate(operation: "delete" | "clear" | "repair" | "restore" | "rotate") {
    if (operation === "restore" && !selectedBackupId) { busy = "请先选择要恢复的备份。"; return; }
    busy = "正在处理历史记录...";
    try {
      if (!admin) throw new Error();
      const selectedId = state.selectedId;
      const input = operation === "delete" && selectedId ? { id: selectedId } : operation === "restore" ? { backup_id: selectedBackupId } : {};
      const result = await admin.run(operation, input);
      if (result === "cancelled") { busy = ""; return; }
      if (operation === "delete" && selectedId) {
        state = removeHistoryItem(state, selectedId);
        detail = null;
        const next = state.items.find((item) => item.id === state.selectedId);
        if (next) await open(next);
      } else if (operation === "clear") {
        state = { ...state, phase: "empty", items: [], cursor: null, selectedId: null };
        detail = null;
      } else {
        detail = null;
        await load(state.query);
      }
      if (operation === "repair" || operation === "restore" || operation === "rotate") await loadBackups();
      busy = "历史操作已完成。";
    }
    catch { busy = "历史操作失败，请稍后重试。"; }
  }

  async function exportHistory() {
    const filters = historyExportFilters(state.query);
    if (!filters) { busy = "当前搜索条件暂不支持导出，请先清除搜索。"; return; }
    busy = "正在导出历史记录...";
    try { if (!admin) throw new Error(); await admin.exportHistory(exportFormat, filters); busy = ""; } catch { busy = "历史导出失败，请稍后重试。"; }
  }

  async function loadBackups() {
    try {
      if (!capability) throw new Error();
      for await (const event of capability.invoke("history-sqlite", "backups", {})) {
        if (event.status === "result") backups = normalizeHistoryBackups(event.data);
      }
      if (!backups.some((backup) => backup.id === selectedBackupId)) selectedBackupId = backups[0]?.id ?? "";
    } catch { backups = []; selectedBackupId = ""; }
  }

  async function scanHistory() {
    busy = "正在扫描历史记录...";
    try {
      if (!capability) throw new Error();
      for await (const event of capability.invoke("history-sqlite", "scan", {})) {
        if (event.status === "result") busy = historyScanMessage(event.data);
      }
    } catch { busy = "历史记录检查失败，请稍后重试。"; }
  }

  async function reuse(kind: "input" | "result") { if (!state.selectedId) return; try { await hostInvoke("history_reuse_intent", { intent: { kind, history_id: state.selectedId } }); busy = "已发送到主窗口。"; } catch { busy = "无法载入这条历史记录。"; } }
  async function hostInvoke(command: string, args: Record<string, unknown>) { const host = await createTauriHostApi(); if (!host) throw new Error(); return host.invoke(command, args); }
</script>

<main class="history-shell">
  <header class="history-head"><div><strong>Reflex</strong><span>历史记录</span></div><div class="history-actions"><details class="history-menu"><summary aria-label="历史记录维护">维护</summary><div class="history-menu-panel"><label>导出格式<select aria-label="导出格式" bind:value={exportFormat}><option value="json">JSON</option><option value="csv">CSV</option><option value="markdown">Markdown</option></select></label><button aria-label="导出历史记录" on:click={exportHistory}>导出</button><button on:click={scanHistory}>检查记录</button><button aria-label="修复历史记录" on:click={() => operate("repair")}>修复</button><label>恢复备份<select aria-label="恢复备份" bind:value={selectedBackupId} disabled={!backups.length}><option value="">暂无备份</option>{#each backups as backup (backup.id)}<option value={backup.id}>{backup.created_at} · {backup.record_count} 条</option>{/each}</select></label><button disabled={!selectedBackupId} on:click={() => operate("restore")}>恢复</button><button on:click={() => operate("rotate")}>轮换密钥</button><button class="danger" on:click={() => operate("clear")}>清空历史</button></div></details></div></header>
  <section class="history-tools"><input aria-label="搜索历史记录" bind:value={search} placeholder="搜索历史记录" /><select aria-label="场景筛选" bind:value={scene}><option value="">全部场景</option>{#each scenes as item (item.id)}<option value={item.id}>{item.label}</option>{/each}</select><select aria-label="风格筛选" bind:value={style}><option value="">全部风格</option>{#each styles as item (item.id)}<option value={item.id}>{item.label}</option>{/each}</select><input aria-label="Provider 筛选" bind:value={provider} placeholder="全部 Provider" /><button on:click={() => load({ search, scene, style, provider })}>筛选</button></section>
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
      {:else}<div class="detail-actions"><span>评分</span>{#each [1,2,3,4,5] as score}<button aria-label={`评分 ${score}`} on:click={() => rate(score)}>{score}</button>{/each}<button aria-label="删除当前历史记录" on:click={() => operate("delete")}>删除</button></div><dl class="history-fields"><div><dt>场景</dt><dd>{detail.scene ?? "-"}</dd></div><div><dt>Provider</dt><dd>{detail.provider ?? "-"}</dd></div><div><dt>模式</dt><dd>{detail.mode ?? "-"}</dd></div><div><dt>耗时</dt><dd>{historyElapsedLabel(detail)}</dd></div></dl><h2>原文</h2><pre>{detail.input ?? ""}</pre><h2>结果</h2><pre>{detail.output ?? ""}</pre><div class="detail-actions"><button on:click={() => reuse("input")}>载入原文</button><button on:click={() => reuse("result")}>使用结果</button></div>{/if}
    </article>
  </section>
</main>
