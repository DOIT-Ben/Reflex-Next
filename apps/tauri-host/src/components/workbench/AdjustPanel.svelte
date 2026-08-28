<script lang="ts">
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import Search from "@lucide/svelte/icons/search";
  import X from "@lucide/svelte/icons/x";
  import { applySceneSelection, type RequestSettings } from "../../domain/hostState";
  import type { WorkbenchModelOption } from "../../domain/providerCatalog";
  import SelectField from "../ui/SelectField.svelte";
  import {
    listSceneCategories,
    type OptimizeMode,
    type OptimizeStyle,
    type SceneCategoryId,
    type SceneOption
  } from "../../domain/reflexSession";

  interface Props {
    draft: RequestSettings;
    inputText: string;
    modes: Array<{ id: OptimizeMode; label: string }>;
    styles: Array<{ id: OptimizeStyle; label: string }>;
    scenes: SceneOption[];
    models: WorkbenchModelOption[];
    translate: (source: string, values?: Record<string, string | number>) => string;
    onDraftChange: (draft: RequestSettings) => void;
    onCancel: () => void;
    onApply: () => void;
  }

  let {
    draft,
    inputText,
    modes,
    styles,
    scenes,
    models,
    translate,
    onDraftChange,
    onCancel,
    onApply
  }: Props = $props();
  const sceneCategories = listSceneCategories();
  let sceneQuery = $state("");
  let sceneCategory = $state<SceneCategoryId | null>(null);
  let visibleScenes = $derived(
    scenes.filter((scene) => {
      if (sceneCategory && scene.category !== sceneCategory) return false;
      const query = sceneQuery.trim().toLocaleLowerCase();
      if (!query) return true;
      const categoryLabel = sceneCategories.find((item) => item.id === scene.category)?.label ?? "";
      return [scene.id, translate(scene.label), translate(scene.hint), translate(categoryLabel)]
        .some((value) => value.toLocaleLowerCase().includes(query));
    })
  );
  const sceneCategoryOptions = $derived([
    { value: "", label: translate("全部分类") },
    ...sceneCategories.map((category) => ({ value: category.id, label: translate(category.label) }))
  ]);
  const sceneSelectOptions = $derived([
    {
      value: "",
      label: translate("自动识别"),
      description: translate("由本地场景路由选择")
    },
    ...(draft.scene && !visibleScenes.some((scene) => scene.id === draft.scene)
      ? [{
          value: draft.scene,
          label: translate(scenes.find((scene) => scene.id === draft.scene)?.label ?? draft.scene)
        }]
      : []),
    ...sceneCategories.flatMap((category) =>
      visibleScenes
        .filter((scene) => scene.category === category.id)
        .map((scene) => ({
          value: scene.id,
          label: translate(scene.label),
          description: translate(scene.hint),
          group: translate(category.label)
        }))
    )
  ]);
  const modelOptions = $derived(
    models.map((model) => ({
      value: modelValue(model.providerId, model.id),
      label: `${model.providerLabel} · ${translate(model.label)}${model.isDefault ? ` · ${translate("默认")}` : ""}`
    }))
  );

  function patchDraft(patch: Partial<RequestSettings>) {
    onDraftChange({ ...draft, ...patch });
  }

  function selectScene(value: string) {
    onDraftChange(applySceneSelection(draft, value));
  }

  function modelValue(providerId: string, modelId: string): string {
    return JSON.stringify([providerId, modelId]);
  }

  function selectModel(value: string) {
    try {
      const [provider, model] = JSON.parse(value) as unknown[];
      if (typeof provider === "string" && typeof model === "string") patchDraft({ provider, model });
    } catch {
      // Ignore malformed values that did not originate from the model list.
    }
  }
</script>

<div class="adjust-layer" role="presentation">
  <button class="adjust-backdrop" type="button" aria-label={translate("关闭")} onclick={onCancel}></button>
  <div
    class="adjust-dialog"
    role="dialog"
    aria-modal="true"
    aria-label={translate("生成设置")}
  >
    <header class="adjust-head">
      <div class="adjust-title">
        <span class="adjust-icon" aria-hidden="true"><SlidersHorizontal size={17} strokeWidth={2} /></span>
        <div>
          <h2>{translate("调整生成方案")}</h2>
          <p>{translate("仅影响下一次生成")}</p>
        </div>
      </div>
      <button class="icon-button" type="button" aria-label={translate("关闭")} onclick={onCancel}>
        <X size={17} strokeWidth={2} />
      </button>
    </header>

    <div class="adjust-content">
      <fieldset class="adjust-group">
        <legend>{translate("模式")}</legend>
        <div class="segments adjust-segments">
          {#each modes as item}
            <button
              type="button"
              class:active={draft.mode === item.id}
              aria-pressed={draft.mode === item.id}
              onclick={() => patchDraft({ mode: item.id })}
            >{translate(item.label)}</button>
          {/each}
        </div>
      </fieldset>

      <fieldset class="adjust-group">
        <legend>{translate("风格")}</legend>
        <div class="segments compact adjust-segments">
          {#each styles as item}
            <button
              type="button"
              class:active={draft.style === item.id}
              aria-pressed={draft.style === item.id}
              onclick={() => patchDraft({ style: item.id })}
            >{translate(item.label)}</button>
          {/each}
        </div>
      </fieldset>

      <div class="scene-tools">
        <label class="scene-search">
          <span class="sr-only">{translate("搜索场景")}</span>
          <span class="scene-search-icon" aria-hidden="true"><Search size={15} strokeWidth={2} /></span>
          <input
            type="search"
            value={sceneQuery}
            placeholder={translate("搜索场景")}
            oninput={(event) => (sceneQuery = event.currentTarget.value)}
          />
        </label>
        <label class="scene-category">
          <span class="sr-only">{translate("场景分类")}</span>
          <SelectField
            value={sceneCategory ?? ""}
            options={sceneCategoryOptions}
            ariaLabel={translate("场景分类")}
            onValueChange={(value) => (sceneCategory = (value || null) as SceneCategoryId | null)}
          />
        </label>
      </div>

      <label class="adjust-field scene-field">
        <span>{translate("场景")} · {visibleScenes.length}</span>
        <SelectField
          value={draft.scene ?? ""}
          options={sceneSelectOptions}
          ariaLabel={translate("场景")}
          onValueChange={selectScene}
        />
      </label>

      <label class="adjust-field">
        <span>{translate("模型")}</span>
        <SelectField
          value={modelValue(draft.provider ?? "", draft.model ?? "")}
          options={modelOptions}
          ariaLabel={translate("模型")}
          disabled={!models.length}
          placeholder={translate("暂无可用模型")}
          onValueChange={selectModel}
        />
      </label>

      <section class="adjust-preview" aria-label={translate("当前输入")}>
        <span>{translate("当前输入")}</span>
        <p>{inputText || translate("尚未输入内容")}</p>
      </section>
    </div>

    <footer class="adjust-footer">
      <button class="outline" type="button" onclick={onCancel}>{translate("取消")}</button>
      <button class="primary small" type="button" onclick={onApply}>{translate("应用")}</button>
    </footer>
  </div>
</div>

<style>
  .scene-tools {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(132px, 0.42fr);
    gap: 8px;
  }

  .scene-search {
    position: relative;
    display: block;
  }

  .scene-search-icon {
    position: absolute;
    top: 50%;
    left: 10px;
    z-index: 1;
    display: grid;
    color: var(--muted);
    pointer-events: none;
    transform: translateY(-50%);
  }

  .scene-search input {
    width: 100%;
    min-height: 36px;
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--line-strong);
    border-radius: 6px;
  }

  .scene-search input {
    padding: 0 10px 0 32px;
  }

  .scene-field > span {
    font-variant-numeric: tabular-nums;
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
    .scene-tools {
      grid-template-columns: 1fr;
    }
  }
</style>
