<script lang="ts">
  import { onMount } from "svelte";
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import { templateVariables, type PromptTemplate, type TemplateDraft } from "../../domain/templateLibrary";

  interface Props {
    query: string;
    category: string | null;
    categories: string[];
    templates: PromptTemplate[];
    selectedId: string | null;
    draft: TemplateDraft;
    values: Record<string, string>;
    notice: string | null;
    busy: boolean;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onQueryChange: (value: string) => void;
    onCategoryChange: (value: string | null) => void;
    onNew: () => void;
    onSelect: (template: PromptTemplate) => void;
    onDraftChange: (draft: TemplateDraft) => void;
    onValuesChange: (values: Record<string, string>) => void;
    onDelete: () => void;
    onSave: () => void;
    onApply: () => void;
    onClose: () => void;
  }

  let {
    query,
    category,
    categories,
    templates,
    selectedId,
    draft,
    values,
    notice,
    busy,
    translate,
    onQueryChange,
    onCategoryChange,
    onNew,
    onSelect,
    onDraftChange,
    onValuesChange,
    onDelete,
    onSave,
    onApply,
    onClose
  }: Props = $props();

  let closeButton: HTMLButtonElement;
  let variables = $derived(templateVariables(draft.content));
  onMount(() => closeButton?.focus());

  function patchDraft(patch: Partial<TemplateDraft>) {
    onDraftChange({ ...draft, ...patch });
  }
</script>

<div class="template-layer" role="presentation">
  <div class="template-dialog" role="dialog" aria-modal="true" aria-label={translate("模板管理")}>
    <header class="template-head">
      <div><h2>{translate("模板管理")}</h2><p>{translate("自定义模板仅保存在本机配置中。")}</p></div>
      <button class="icon-button" type="button" aria-label={translate("关闭模板管理")} bind:this={closeButton} onclick={onClose}><X size={17} strokeWidth={2} /></button>
    </header>
    <div class="template-layout">
      <aside class="template-list">
        <input aria-label={translate("搜索模板")} value={query} placeholder={translate("搜索名称、分类或标签")} oninput={(event) => onQueryChange(event.currentTarget.value)} />
        <select aria-label={translate("模板分类")} value={category ?? ""} onchange={(event) => onCategoryChange(event.currentTarget.value || null)}>
          <option value="">{translate("全部分类")}</option>
          {#each categories as item}<option value={item}>{item}</option>{/each}
        </select>
        <button class="outline template-new" type="button" onclick={onNew}><Plus size={15} strokeWidth={2} />{translate("新建模板")}</button>
        <div class="template-list-items">
          {#each templates as template (template.id)}
            <button class:active={selectedId === template.id} type="button" onclick={() => onSelect(template)}>
              <strong>{template.name}</strong>
              <span>{template.category}{template.tags.length ? ` · ${template.tags.join("、")}` : ""}</span>
            </button>
          {:else}
            <p>{translate("还没有符合条件的模板。")}</p>
          {/each}
        </div>
      </aside>
      <section class="template-editor">
        <div class="template-fields">
          <label><span>{translate("名称")}</span><input value={draft.name} disabled={busy} oninput={(event) => patchDraft({ name: event.currentTarget.value })} /></label>
          <label><span>{translate("分类")}</span><input value={draft.category} disabled={busy} oninput={(event) => patchDraft({ category: event.currentTarget.value })} /></label>
          <label class="wide"><span>{translate("标签（用逗号分隔）")}</span><input value={draft.tags.join(", ")} disabled={busy} oninput={(event) => patchDraft({ tags: event.currentTarget.value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) })} /></label>
          <label class="wide"><span>{translate("说明")}</span><input value={draft.description} disabled={busy} oninput={(event) => patchDraft({ description: event.currentTarget.value })} /></label>
          <label class="wide"><span>{translate("模板内容")}</span><textarea value={draft.content} disabled={busy} placeholder={translate("使用 {变量名} 插入需要填写的内容")} oninput={(event) => patchDraft({ content: event.currentTarget.value })}></textarea></label>
        </div>
        {#if variables.length}
          <div class="template-variables">
            <h3>{translate("填写变量")}</h3>
            {#each variables as variable}
              <label><span>{variable}</span><input value={values[variable] ?? ""} oninput={(event) => onValuesChange({ ...values, [variable]: event.currentTarget.value })} /></label>
            {/each}
          </div>
        {/if}
        <p class="template-notice" aria-live="polite">{notice ? translate(notice) : ""}</p>
        <footer class="template-footer">
          <button class="outline danger" type="button" disabled={!selectedId || busy} onclick={onDelete}>{translate("删除")}</button>
          <span></span>
          <button class="outline" type="button" disabled={busy} onclick={onSave}>{translate("保存模板")}</button>
          <button class="primary small" type="button" onclick={onApply}>{translate("应用到输入区")}</button>
        </footer>
      </section>
    </div>
  </div>
</div>
