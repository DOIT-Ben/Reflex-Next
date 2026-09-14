<script lang="ts">
  import { onMount } from "svelte";
  import HistoryDetail from "./HistoryDetail.svelte";
  import HistoryFilters from "./HistoryFilters.svelte";
  import HistoryMaintenanceMenu from "./HistoryMaintenanceMenu.svelte";
  import HistoryList from "./HistoryList.svelte";
  import { CapabilityBridge } from "../../domain/capabilityBridge";
  import { createTauriHostApi } from "../../domain/tauriHostApi";
  import { createSettingsApi } from "../../domain/settingsApi";
  import { createHistoryAdminBridge } from "../../domain/historyAdminBridge";
  import { appendHistoryPage, applyHistoryDetailFailure, applyHistoryDetailTerminal, applyHistoryRatingToDetail, createHistoryBackupsState, createHistoryState, failHistoryBackupsLoad, failHistoryQuery, finishHistoryBackupsLoad, historyExportFilters, historyListInput, historyScanMessage, removeHistoryItem, selectHistoryItem, startHistoryBackupsLoad, startHistoryQuery, updateHistoryRating, type HistoryPage, type HistorySummary } from "../../domain/historyState";
  import { listSceneOptions } from "../../domain/reflexSession";
  import { translate, type UiLanguage } from "../../domain/i18n";
  import { setTranslator } from "../../domain/i18nStore";

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
  let backupsState = createHistoryBackupsState();
  let busy = "";
  let uiLanguage: UiLanguage = "zh-CN";

  function tr(source: string, values: Record<string, string | number> = {}): string {
    return translate(uiLanguage, source, values);
  }

  setTranslator(tr);

  function sceneLabel(id: string): string {
    return tr(scenes.find((item) => item.id === id)?.label ?? id);
  }

  function styleLabel(id: string): string {
    return tr(styles.find((item) => item.id === id)?.label ?? id);
  }

  onMount(() => {
    void createTauriHostApi().then(async (host) => {
      if (!host) {
        state = { ...state, phase: "error", error: "历史记录暂时不可用，请稍后重试。" };
        return;
      }
      capability = new CapabilityBridge(host);
      admin = createHistoryAdminBridge(host);
      try {
        const config = await createSettingsApi(host).loadConfig();
        uiLanguage = config.language;
        if (!config.history_enabled) {
          state = { ...state, phase: "error", error: "历史记录未启用，请先在设置中开启。" };
          backupsState = { ...backupsState, phase: "error", items: [], selectedId: "" };
          return;
        }
      } catch {
        uiLanguage = "zh-CN";
      }
      void load({});
      void loadBackups();
    });
  });

  async function load(query: Record<string, string>, more = false) {
    const started = more ? { state: { ...state, phase: "loading-more" as const }, request: state.request } : startHistoryQuery(state, query);
    state = started.state;
    try {
      const input = historyListInput(state.query, more ? state.cursor : null);
      if (!capability) throw new Error();
      let received = false;
      for await (const event of capability.invoke("history-sqlite", "list", input)) {
        if (event.status === "result") {
          state = appendHistoryPage(state, started.request, event.data as unknown as HistoryPage);
          received = true;
        } else if (event.status === "error" || event.status === "cancelled") {
          throw new Error();
        }
      }
      if (!received) throw new Error();
    } catch { state = failHistoryQuery(state, started.request, "历史记录暂时不可用，请稍后重试。"); }
  }

  async function open(item: HistorySummary) {
    state = selectHistoryItem(state, item.id); detail = null;
    const request = state.detailRequest;
    try {
      if (!capability) throw new Error();
      let received = false;
      for await (const event of capability.invoke("history-sqlite", "detail", { id: item.id })) {
        if (event.status === "result" && state.detailRequest === request && state.selectedId === item.id) {
          detail = (event.data.record ?? {}) as Record<string, unknown>;
          received = true;
        } else if (event.status === "error" || event.status === "cancelled") {
          detail = applyHistoryDetailTerminal(state, detail, item.id, request, event.status);
          received = true;
        }
      }
      if (!received) detail = applyHistoryDetailFailure(state, detail, item.id, request);
    }
    catch { detail = applyHistoryDetailFailure(state, detail, item.id, request); }
  }

  async function rate(rating: number) {
    if (!state.selectedId) return;
    const selectedId = state.selectedId;
    const detailRequest = state.detailRequest;
    try {
      if (!capability) throw new Error();
      let completed = false;
      for await (const event of capability.invoke("history-sqlite", "rate", { id: selectedId, rating })) {
        if (event.status === "result") completed = true;
        else if (event.status === "error" || event.status === "cancelled") throw new Error();
      }
      if (!completed) throw new Error();
      state = updateHistoryRating(state, selectedId, rating);
      detail = applyHistoryRatingToDetail(state, detail, selectedId, detailRequest, rating);
      busy = "评分已保存。";
    } catch { busy = "评分未保存，请稍后重试。"; }
  }

  async function operate(operation: "delete" | "clear" | "repair" | "restore" | "rotate") {
    if (operation === "restore" && (backupsState.phase !== "ready" || !backupsState.selectedId)) { busy = "请先选择要恢复的备份。"; return; }
    busy = "正在处理历史记录...";
    try {
      if (!admin) throw new Error();
      const selectedId = state.selectedId;
      const input = operation === "delete" && selectedId ? { id: selectedId } : operation === "restore" ? { backup_id: backupsState.selectedId } : {};
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
    const started = startHistoryBackupsLoad(backupsState);
    backupsState = started.state;
    try {
      if (!capability) throw new Error();
      let received = false;
      for await (const event of capability.invoke("history-sqlite", "backups", {})) {
        if (event.status === "result") {
          backupsState = finishHistoryBackupsLoad(backupsState, started.request, event.data);
          received = true;
        }
      }
      if (!received) throw new Error();
    } catch { backupsState = failHistoryBackupsLoad(backupsState, started.request); }
  }

  async function scanHistory() {
    busy = "正在扫描历史记录...";
    try {
      if (!capability) throw new Error();
      let completed = false;
      for await (const event of capability.invoke("history-sqlite", "scan", {})) {
        if (event.status === "result") {
          busy = historyScanMessage(event.data);
          completed = true;
        } else if (event.status === "error" || event.status === "cancelled") {
          throw new Error();
        }
      }
      if (!completed) throw new Error();
    } catch { busy = "历史记录检查失败，请稍后重试。"; }
  }

  async function reuse(kind: "input" | "result") { if (!state.selectedId) return; try { await hostInvoke("history_reuse_intent", { intent: { kind, history_id: state.selectedId } }); busy = "已发送到主窗口。"; } catch { busy = "无法载入这条历史记录。"; } }
  async function hostInvoke(command: string, args: Record<string, unknown>) { const host = await createTauriHostApi(); if (!host) throw new Error(); return host.invoke(command, args); }
</script>

<div class="history-view animate-fade-in">

  <div class="history-toolbar">
    <HistoryFilters
    {search}
    {scene}
    {style}
    {provider}
    {scenes}
    {styles}

    onSearchChange={(value) => (search = value)}
    onSceneChange={(value) => (scene = value)}
    onStyleChange={(value) => (style = value)}
    onProviderChange={(value) => (provider = value)}
      onSubmit={() => load({ search, scene, style, provider })}
    />
    <HistoryMaintenanceMenu
      {exportFormat}
      backups={backupsState}
      onExportFormatChange={(value) => (exportFormat = value)}
      onBackupChange={(value) => (backupsState = { ...backupsState, selectedId: value })}
      onExport={exportHistory}
      onScan={scanHistory}
      onRepair={() => operate("repair")}
      onRetryBackups={loadBackups}
      onRestore={() => operate("restore")}
      onRotate={() => operate("rotate")}
      onClear={() => operate("clear")}
    />
  </div>
  {#if busy}<p class="history-notice" role="status" aria-live="polite">{tr(busy)}</p>{/if}
  <section class="history-workspace">
    <HistoryList {state} {sceneLabel} {styleLabel} onSelect={open} onMore={() => load(state.query, true)} />
    <HistoryDetail
      {state}
      {detail}

      {sceneLabel}
      onRate={rate}
      onDelete={() => operate("delete")}
      onReuseInput={() => reuse("input")}
      onReuseResult={() => reuse("result")}
    />
  </section>
</div>

<style>
  .history-view {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    width: 100%;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    background: hsl(var(--background));
  }

  .history-toolbar {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 8px;
  }

  .history-toolbar :global(.history-tools) {
    flex: 1 1 auto;
    border-bottom: 0;
  }

  .history-view :global(.history-workspace) {
    flex: 1 1 auto;
    min-height: 0;
    margin: 0;
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
  }

  .history-view :global(.history-notice) {
    flex: 0 0 auto;
    padding: 6px 0;
    border-bottom: 0;
  }
</style>
