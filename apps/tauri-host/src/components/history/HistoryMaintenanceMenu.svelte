<script lang="ts">
  import { Button } from "@/components/ui/button";
  import MoreHorizontal from "@lucide/svelte/icons/ellipsis";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { translator } from "../../domain/i18nStore";
  import type { HistoryExportFormat } from "../../domain/historyAdminBridge";
  import type { HistoryBackupsState } from "../../domain/historyState";

  interface Props {
    exportFormat: HistoryExportFormat;
    backups: HistoryBackupsState;
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
  let translate = $derived($translator);
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

<!-- 历史维护菜单（下拉）：从旧的历史窗口头部抽出，供视图工具栏复用 -->
<details class="history-menu">
      <summary aria-label={translate("历史记录维护")}><MoreHorizontal size={17} strokeWidth={2} /><span>{translate("维护")}</span></summary>
      <div class="history-menu-panel">
        <label>{translate("导出格式")}<AppSelect ariaLabel={translate("导出格式")} value={exportFormat} options={exportOptions} size="sm" onValueChange={(value) => onExportFormatChange(value as HistoryExportFormat)} /></label>
        <Button variant="outline" size="sm" aria-label={translate("导出历史记录")} onclick={onExport}>{translate("导出")}</Button>
        <Button variant="outline" size="sm" onclick={onScan}>{translate("检查记录")}</Button>
        <Button variant="outline" size="sm" aria-label={translate("修复历史记录")} onclick={onRepair}>{translate("修复")}</Button>
        <label>{translate("恢复备份")}<AppSelect ariaLabel={translate("恢复备份")} value={backups.selectedId} options={backupOptions} size="sm" disabled={backups.phase !== "ready" || !backups.items.length} onValueChange={onBackupChange} /></label>
        {#if backups.phase === "loading" || backups.phase === "error"}<p class:error={backups.phase === "error"} class="history-backup-status" role="status" aria-live="polite">{translate(backups.phase === "loading" ? "正在加载备份..." : "备份列表暂时不可用")}</p>{/if}
        {#if backups.phase === "error"}<Button variant="outline" size="sm" aria-label={translate("重试加载备份")} onclick={onRetryBackups}>{translate("重试备份")}</Button>{/if}
        <Button variant="outline" size="sm" disabled={backups.phase !== "ready" || !backups.selectedId} onclick={onRestore}>{translate("恢复")}</Button>
        <Button variant="outline" size="sm" onclick={onRotate}>{translate("轮换密钥")}</Button>
        <Button variant="outline" size="sm" class="text-destructive hover:text-destructive" onclick={onClear}>{translate("清空历史")}</Button>
      </div>
    </details>
