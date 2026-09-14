<script lang="ts">
  import { Button } from "@/components/ui/button";
  import Download from "@lucide/svelte/icons/download";
  import Upload from "@lucide/svelte/icons/upload";
  import DialogShell from "../ui/DialogShell.svelte";
  import {
    batchCanExport,
    batchCompletedCount,
    batchProcessedCount,
    setBatchConcurrency,
    setBatchFormat,
    setBatchScene,
    setBatchSourceText,
    setBatchStyle,
    type BatchFormat,
    type BatchState
  } from "../../domain/batchState";
  import type { OptimizeStyle, SceneOption } from "../../domain/reflexSession";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { translator } from "../../domain/i18nStore";

  interface Props {
    state: BatchState;
    fileNotice: string | null;
    styles: Array<{ id: OptimizeStyle; label: string }>;
    scenes: SceneOption[];
    onStateChange: (state: BatchState) => void;
    onFileSelected: (file: File) => void;
    onDownloadTemplate: () => void;
    onParse: () => void;
    onCancel: () => void;
    onExport: () => void;
    onRun: () => void;
    onClose: () => void;
  }

  let {
    state,
    fileNotice,
    styles,
    scenes,
    onStateChange,
    onFileSelected,
    onDownloadTemplate,
    onParse,
    onCancel,
    onExport,
    onRun,
    onClose
  }: Props = $props();

  let translate = $derived($translator);

  let fileInput: HTMLInputElement;
  let locked = $derived(state.phase === "parsing" || state.phase === "running");
  let styleOptions = $derived(styles.map((item) => ({ value: item.id, label: translate(item.label) })));
  let sceneSelectOptions = $derived([
    { value: "", label: translate("自动识别"), description: translate("由本地场景路由选择") },
    ...scenes.map((scene) => ({ value: scene.id, label: translate(scene.label) }))
  ]);
  const concurrencyOptions = [1, 2, 3, 4].map((value) => ({ value: String(value), label: String(value) }));

  function chooseFile() {
    if (!locked) fileInput?.click();
  }

  function receiveFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (file && !locked) onFileSelected(file);
  }

  function statusLabel(status: BatchState["items"][number]["status"]) {
    return status === "pending" ? "等待" : status === "running" ? "处理中" : status === "completed" ? "已完成" : status === "cancelled" ? "已停止" : "失败";
  }
</script>

<DialogShell title={translate("批量处理")} description={translate("最多导入 200 条提示词，结果在本机导出。")} z={10} closeLabel={translate("关闭批量处理")} onClose={onClose} size="lg">
  <div class="batch-controls">
      <div class="batch-format" role="group" aria-label={translate("导入格式")}>
        {#each ([{ id: "txt", label: "TXT 每行一条" }, { id: "csv", label: "CSV prompt 列" }] satisfies Array<{ id: BatchFormat; label: string }>) as item}
          <button type="button" class:active={state.format === item.id} aria-pressed={state.format === item.id} disabled={locked} onclick={() => onStateChange(setBatchFormat(state, item.id))}>{translate(item.label)}</button>
        {/each}
      </div>
      <label><span>{translate("处理风格")}</span><AppSelect value={state.style} options={styleOptions} ariaLabel={translate("处理风格")} disabled={state.phase === "running"} onValueChange={(value) => onStateChange(setBatchStyle(state, value as OptimizeStyle))} /></label>
      <label><span>{translate("场景")}</span><AppSelect value={state.scene ?? ""} options={sceneSelectOptions} ariaLabel={translate("场景")} disabled={state.phase === "running"} onValueChange={(value) => onStateChange(setBatchScene(state, value))} /></label>
      <label><span>{translate("并发数")}</span><AppSelect value={String(state.concurrency)} options={concurrencyOptions} ariaLabel={translate("并发数")} size="sm" disabled={state.phase === "running"} onValueChange={(value) => onStateChange(setBatchConcurrency(state, Number(value)))} /></label>
    </div>

    <label class="batch-source">
      <span>{translate(state.format === "csv" ? "粘贴 CSV，需包含 prompt 或 提示词 列" : "粘贴文本，每行一条提示词")}</span>
      <textarea
        aria-label={translate("批量输入内容")}
        value={state.sourceText}
        disabled={locked}
        oninput={(event) => onStateChange(setBatchSourceText(state, event.currentTarget.value))}
        placeholder={state.format === "csv" ? "prompt\nWrite a business email" : translate("写一封商务邮件\n解释什么是机器学习")}
      ></textarea>
    </label>
    <input type="file" accept=".csv,text/csv,.txt,text/plain" hidden bind:this={fileInput} onchange={receiveFile} />

    <div class="batch-action-row">
      <div class="batch-import-actions">
        <Button variant="outline" disabled={locked} onclick={chooseFile}><Upload size={14} strokeWidth={2} />{translate("导入文件")}</Button>
        <Button variant="outline" disabled={locked} onclick={onDownloadTemplate}><Download size={14} strokeWidth={2} />{translate("下载模板")}</Button>
        <Button variant="outline" disabled={locked || !state.sourceText.trim()} onclick={onParse}>{translate(state.phase === "parsing" ? "正在解析" : "解析内容")}</Button>
      </div>
      <p aria-live="polite">
        {#if fileNotice}<span class="error">{translate(fileNotice)}</span>
        {:else if state.phase === "running"}{translate("正在处理 {processed}/{total}，已完成 {completed} 条", { processed: batchProcessedCount(state), total: state.items.length, completed: batchCompletedCount(state) })}
        {:else if state.phase === "completed"}{translate("已完成 {completed}/{total} 条", { completed: batchCompletedCount(state), total: state.items.length })}
        {:else if state.phase === "cancelled"}{translate("已停止，已完成 {completed} 条", { completed: batchCompletedCount(state) })}
        {:else if state.error}<span class="error">{translate(state.error)}</span>
        {:else if state.items.length}{translate("已解析 {count} 条提示词", { count: state.items.length })}
        {:else}{translate("等待导入内容")}{/if}
      </p>
    </div>

    <div class="batch-list" aria-label={translate("批处理列表")}>
      {#if state.items.length}
        {#each state.items as item (item.id)}
          <article class:completed={item.status === "completed"} class:failed={item.status === "failed"} class:running={item.status === "running"} class="batch-item">
            <span class="batch-item-id">{item.id}</span>
            <div><strong>{item.prompt}</strong>{#if item.result}<p>{item.result}</p>{/if}{#if item.error}<p class="error">{translate(item.error)}</p>{/if}</div>
            <span class="batch-status">{translate(statusLabel(item.status))}</span>
          </article>
        {/each}
      {:else}
        <p class="batch-empty">{translate("解析后将在这里显示待处理的提示词。")}</p>
      {/if}
    </div>

    {#snippet footer()}
    <footer>
      {#if state.phase === "running"}<Button variant="outline" onclick={onCancel}>{translate("停止")}</Button>
      {:else}<Button variant="outline" disabled={!batchCanExport(state)} onclick={onExport}>{translate("导出结果")}</Button><Button variant="default" size="sm" disabled={!state.items.length} onclick={onRun}>{translate("开始处理")}</Button>{/if}
    </footer>
    {/snippet}
</DialogShell>
