<script lang="ts">
  import MoreHorizontal from "@lucide/svelte/icons/ellipsis";
  import type { HistoryExportFormat } from "../../domain/historyAdminBridge";
  import type { HistoryBackupsState } from "../../domain/historyState";
  import SelectField from "../ui/SelectField.svelte";

  interface Props {
    exportFormat: HistoryExportFormat;
    backups: HistoryBackupsState;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onExportFormatChange: (format: HistoryExportFormat) => void;
    onBackupChange: (id: string) => void;
    onExport: () => void;
    onScan: () => void;
    onRepair: () => void;
    onRetryBackups: () => void;
    onRestore: () => void;
    onRotate: () => void;
    onClear: () => void;
  }

  let {
    exportFormat,
    backups,
    translate,
    onExportFormatChange,
    onBackupChange,
    onExport,
    onScan,
    onRepair,
    onRetryBackups,
    onRestore,
    onRotate,
    onClear
  }: Props = $props();
  const exportOptions = [
    { value: "json", label: "JSON" },
    { value: "csv", label: "CSV" },
    { value: "markdown", label: "Markdown" }
  ];
  let backupOptions = $derived(
    backups.phase === "loading"
      ? [{ value: "", label: translate("正在加载备份...") }]
      : backups.phase === "error"
        ? [{ value: "", label: translate("备份列表暂时不可用") }]
        : backups.items.length
          ? backups.items.map((backup) => ({
              value: backup.id,
              label: `${backup.created_at} · ${backup.record_count}`
            }))
          : [{ value: "", label: translate("暂无备份") }]
  );
</script>

<header class="history-head">
  <div class="history-brand"><span class="history-mark" aria-hidden="true">R</span><div><strong>Reflex Next</strong><span>{translate("历史记录")}</span></div></div>
  <div class="history-actions">
    <details class="history-menu">
      <summary aria-label={translate("历史记录维护")}><MoreHorizontal size={17} strokeWidth={2} /><span>{translate("维护")}</span></summary>
      <div class="history-menu-panel">
        <label>{translate("导出格式")}<SelectField ariaLabel={translate("导出格式")} value={exportFormat} options={exportOptions} size="compact" onValueChange={(value) => onExportFormatChange(value as HistoryExportFormat)} /></label>
        <button type="button" aria-label={translate("导出历史记录")} onclick={onExport}>{translate("导出")}</button>
        <button type="button" onclick={onScan}>{translate("检查记录")}</button>
        <button type="button" aria-label={translate("修复历史记录")} onclick={onRepair}>{translate("修复")}</button>
        <label>{translate("恢复备份")}<SelectField ariaLabel={translate("恢复备份")} value={backups.selectedId} options={backupOptions} size="compact" disabled={backups.phase !== "ready" || !backups.items.length} onValueChange={onBackupChange} /></label>
        {#if backups.phase === "loading" || backups.phase === "error"}<p class:error={backups.phase === "error"} class="history-backup-status" role="status" aria-live="polite">{translate(backups.phase === "loading" ? "正在加载备份..." : "备份列表暂时不可用")}</p>{/if}
        {#if backups.phase === "error"}<button type="button" aria-label={translate("重试加载备份")} onclick={onRetryBackups}>{translate("重试备份")}</button>{/if}
        <button type="button" disabled={backups.phase !== "ready" || !backups.selectedId} onclick={onRestore}>{translate("恢复")}</button>
        <button type="button" onclick={onRotate}>{translate("轮换密钥")}</button>
        <button class="danger" type="button" onclick={onClear}>{translate("清空历史")}</button>
      </div>
    </details>
  </div>
</header>
