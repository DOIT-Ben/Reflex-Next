<script lang="ts">
  import { onMount } from "svelte";
  import Search from "@lucide/svelte/icons/search";
  import DialogShell from "../ui/DialogShell.svelte";
  import SelectField from "../ui/SelectField.svelte";
  import { translator } from "../../domain/i18nStore";
  import {
    listSceneCategories,
    type SceneCategoryId,
    type SceneOption
  } from "../../domain/reflexSession";

  interface Props {
    scenes: SceneOption[];
    selectedScene: string;
    onSceneChange: (sceneId: string) => void;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let {
    scenes,
    selectedScene,
    onSceneChange,
    onCancel,
    onConfirm
  }: Props = $props();
  let translate = $derived($translator);

  const categories = listSceneCategories();
  let query = $state("");
  let category = $state<SceneCategoryId | null>(null);
  let searchInput: HTMLInputElement;
  let visibleScenes = $derived(
    scenes.filter((scene) => {
      if (category && scene.category !== category) return false;
      const normalized = query.trim().toLocaleLowerCase();
      if (!normalized) return true;
      const categoryLabel = categories.find((item) => item.id === scene.category)?.label ?? "";
      return [scene.id, translate(scene.label), translate(scene.hint), translate(categoryLabel)]
        .some((value) => value.toLocaleLowerCase().includes(normalized));
    })
  );
  const categoryOptions = $derived([
    { value: "", label: translate("全部分类") },
    ...categories.map((item) => ({ value: item.id, label: translate(item.label) }))
  ]);
  let selectedSceneOption = $derived(scenes.find((scene) => scene.id === selectedScene));

  onMount(() => searchInput?.focus());
</script>

<DialogShell
  title={translate("选择本次场景")}
  z={90}
  closeLabel={translate("关闭")}
  onClose={onCancel}
  closeOnBackdrop={true}
  autofocusClose={false}
  size="md"
>
  <div class="scene-controls">
    <label class="scene-search">
      <span class="sr-only">{translate("搜索场景")}</span>
      <span class="scene-search-icon" aria-hidden="true"><Search size={15} strokeWidth={2} /></span>
      <input
        type="search"
        bind:this={searchInput}
        value={query}
        placeholder={translate("搜索场景")}
        oninput={(event) => (query = event.currentTarget.value)}
      />
    </label>
    <label>
      <span class="sr-only">{translate("场景分类")}</span>
      <SelectField
        value={category ?? ""}
        options={categoryOptions}
        ariaLabel={translate("场景分类")}
        onValueChange={(value) => (category = (value || null) as SceneCategoryId | null)}
      />
    </label>
  </div>

  <div class="scene-list" role="radiogroup" aria-label={translate("场景")}>
    {#if !query.trim() && !category}
      <label class:selected={!selectedScene} class="scene-choice automatic">
        <input
          type="radio"
          name="scene-choice"
          value=""
          checked={!selectedScene}
          onchange={() => onSceneChange("")}
        />
        <span><strong>{translate("自动识别")}</strong><small>{translate("由本地场景路由选择")}</small></span>
      </label>
    {/if}

    {#each categories as group}
      {@const groupScenes = visibleScenes.filter((scene) => scene.category === group.id)}
      {#if groupScenes.length > 0}
        <h3>{translate(group.label)}</h3>
        <div class="scene-group">
          {#each groupScenes as scene}
            <label class:selected={selectedScene === scene.id} class="scene-choice">
              <input
                type="radio"
                name="scene-choice"
                value={scene.id}
                checked={selectedScene === scene.id}
                onchange={() => onSceneChange(scene.id)}
              />
              <span><strong>{translate(scene.label)}</strong><small>{translate(scene.hint)}</small></span>
            </label>
          {/each}
        </div>
      {/if}
    {/each}

    {#if visibleScenes.length === 0}
      <p class="empty-state">{translate("没有匹配的场景")}</p>
    {/if}
  </div>

  <footer slot="footer">
    <div class="scene-footer-inner">
      <div class="scene-summary">
        <span>{translate("已显示 {count} 个场景", { count: visibleScenes.length })}</span>
        <strong>{translate("当前场景：{scene}", {
          scene: selectedSceneOption ? translate(selectedSceneOption.label) : translate("自动识别")
        })}</strong>
      </div>
      <div class="scene-footer-actions">
        <button class="outline" type="button" onclick={onCancel}>{translate("取消")}</button>
        <button class="primary small" type="button" onclick={onConfirm}>{translate("开始生成")}</button>
      </div>
    </div>
  </footer>
</DialogShell>

<style>
  .scene-footer-inner {
    display: flex;
    flex: 1 1 auto;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-width: 0;
  }

  .scene-footer-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 8px;
  }

  .scene-controls {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(150px, 0.36fr);
    gap: 8px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--line);
  }

  .scene-search {
    position: relative;
  }

  .scene-search-icon {
    position: absolute;
    top: 50%;
    left: 10px;
    display: grid;
    color: var(--muted);
    pointer-events: none;
    transform: translateY(-50%);
  }

  input[type="search"] {
    width: 100%;
    min-height: 36px;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--line-strong);
    border-radius: 6px;
  }

  input[type="search"] {
    padding: 0 10px 0 32px;
  }

  .scene-list {
    min-height: 0;
    padding: 10px 16px 16px;
    overflow: auto;
  }

  h3 {
    margin: 0;
    padding: 10px 0 6px;
    color: var(--muted);
    font-size: var(--font-meta);
    font-weight: 700;
  }

  .scene-group {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }

  .scene-choice {
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr);
    gap: 8px;
    align-items: start;
    min-height: 54px;
    padding: 8px 10px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 6px;
    cursor: pointer;
  }

  .scene-choice:hover,
  .scene-choice.selected {
    background: var(--accent-soft);
    border-color: var(--accent);
  }

  .scene-choice input {
    width: 15px;
    height: 15px;
    margin: 2px 0 0;
    accent-color: var(--accent);
  }

  .scene-choice span {
    min-width: 0;
  }

  .scene-choice strong,
  .scene-choice small {
    display: block;
  }

  .scene-choice strong {
    font-size: var(--font-body);
    line-height: 1.4;
  }

  .scene-choice small {
    margin-top: 3px;
    color: var(--muted);
    font-size: var(--font-meta);
    line-height: 1.45;
  }

  .empty-state {
    padding: 18px 0;
    color: var(--muted);
    text-align: center;
  }

  .scene-summary {
    display: grid;
    gap: 2px;
    min-width: 0;
  }

  .scene-summary span {
    margin-top: 3px;
    color: var(--muted);
    font-size: var(--font-meta);
  }

  .scene-summary strong {
    overflow: hidden;
    font-size: var(--font-meta);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @media (max-width: 620px) {
    .scene-group {
      grid-template-columns: 1fr;
    }
  }
</style>
