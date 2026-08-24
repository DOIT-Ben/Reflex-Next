<script lang="ts">
  import { onMount } from "svelte";
  import Search from "@lucide/svelte/icons/search";
  import X from "@lucide/svelte/icons/x";
  import {
    listSceneCategories,
    type SceneCategoryId,
    type SceneOption
  } from "../../domain/reflexSession";

  interface Props {
    scenes: SceneOption[];
    selectedScene: string;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onSceneChange: (sceneId: string) => void;
    onCancel: () => void;
    onConfirm: () => void;
  }

  let {
    scenes,
    selectedScene,
    translate,
    onSceneChange,
    onCancel,
    onConfirm
  }: Props = $props();

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
  let selectedSceneOption = $derived(scenes.find((scene) => scene.id === selectedScene));

  onMount(() => searchInput?.focus());
</script>

<div class="scene-prompt-layer" role="presentation">
  <button class="scene-backdrop" type="button" aria-label={translate("取消")} onclick={onCancel}></button>
  <div class="scene-prompt" role="dialog" aria-modal="true" aria-labelledby="scene-prompt-title">
    <header>
      <h2 id="scene-prompt-title">{translate("选择本次场景")}</h2>
      <button class="icon-button" type="button" aria-label={translate("关闭")} title={translate("关闭")} onclick={onCancel}>
        <X size={17} strokeWidth={2} />
      </button>
    </header>

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
        <select
          value={category ?? ""}
          onchange={(event) => (category = (event.currentTarget.value || null) as SceneCategoryId | null)}
        >
          <option value="">{translate("全部分类")}</option>
          {#each categories as item}
            <option value={item.id}>{translate(item.label)}</option>
          {/each}
        </select>
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

    <footer>
      <div class="scene-summary">
        <span>{translate("已显示 {count} 个场景", { count: visibleScenes.length })}</span>
        <strong>{translate("当前场景：{scene}", {
          scene: selectedSceneOption ? translate(selectedSceneOption.label) : translate("自动识别")
        })}</strong>
      </div>
      <div>
        <button class="outline" type="button" onclick={onCancel}>{translate("取消")}</button>
        <button class="primary small" type="button" onclick={onConfirm}>{translate("开始生成")}</button>
      </div>
    </footer>
  </div>
</div>

<style>
  .scene-prompt-layer {
    position: absolute;
    inset: 0;
    z-index: 90;
    display: grid;
    place-items: center;
    padding: 18px;
  }

  .scene-backdrop {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    padding: 0;
    background: rgb(15 23 42 / 38%);
    border: 0;
  }

  .scene-prompt {
    position: relative;
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr) auto;
    width: min(720px, 100%);
    max-height: min(720px, calc(100vh - 36px));
    overflow: hidden;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    box-shadow: 0 24px 64px rgb(15 23 42 / 28%);
  }

  header,
  footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 16px;
  }

  header {
    border-bottom: 1px solid var(--line);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    font-size: 16px;
    line-height: 1.35;
  }

  .scene-summary {
    display: grid;
    gap: 2px;
    min-width: 0;
  }

  .scene-summary span {
    margin-top: 3px;
    color: var(--muted);
    font-size: 12px;
  }

  .scene-summary strong {
    overflow: hidden;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .icon-button {
    display: grid;
    flex: 0 0 32px;
    width: 32px;
    height: 32px;
    place-items: center;
    color: var(--muted);
    background: transparent;
    border: 0;
    border-radius: 6px;
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

  input[type="search"],
  select {
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

  select {
    padding: 0 28px 0 10px;
  }

  .scene-list {
    min-height: 0;
    padding: 10px 16px 16px;
    overflow: auto;
  }

  h3 {
    padding: 10px 0 6px;
    color: var(--muted);
    font-size: 11px;
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
    font-size: 13px;
    line-height: 1.35;
  }

  .scene-choice small {
    margin-top: 2px;
    overflow: hidden;
    color: var(--muted);
    font-size: 11px;
    line-height: 1.35;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .automatic {
    margin-bottom: 4px;
  }

  .empty-state {
    padding: 48px 12px;
    color: var(--muted);
    text-align: center;
  }

  footer {
    border-top: 1px solid var(--line);
  }

  footer > div {
    display: flex;
    gap: 8px;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 620px) {
    .scene-prompt-layer {
      padding: 8px;
    }

    .scene-prompt {
      max-height: calc(100vh - 16px);
    }

    .scene-controls,
    .scene-group {
      grid-template-columns: 1fr;
    }

    footer {
      align-items: flex-end;
    }

    .scene-summary {
      max-width: 44%;
    }
  }
</style>
