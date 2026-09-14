<script lang="ts">
  import { Button } from "@/components/ui/button";
  import DialogShell from "@/components/ui/DialogShell.svelte";
  import SegmentedControl from "@/components/ui/SegmentedControl.svelte";
  import { Input } from "@/components/ui/input";
  import Search from "@lucide/svelte/icons/search";
  import { applySceneSelection, type RequestSettings } from "../../domain/hostState";
  import type { WorkbenchModelOption } from "../../domain/providerCatalog";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { translator } from "../../domain/i18nStore";
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
    onDraftChange,
    onCancel,
    onApply
  }: Props = $props();
  let translate = $derived($translator);
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

<DialogShell
  title={translate("调整生成方案")}
  description={translate("仅影响下一次生成")}
  size="md"
  z={20}
  closeLabel={translate("关闭")}
  onClose={onCancel}
>
  <div class="adjust-body">
    <div class="adjust-group">
      <span class="adjust-label">{translate("模式")}</span>
      <SegmentedControl
        options={modes.map((item) => ({ id: item.id, label: translate(item.label) }))}
        value={draft.mode}
        ariaLabel={translate("模式")}
        onValueChange={(value) => patchDraft({ mode: value })}
      />
    </div>

    <div class="adjust-group">
      <span class="adjust-label">{translate("风格")}</span>
      <SegmentedControl
        options={styles.map((item) => ({ id: item.id, label: translate(item.label) }))}
        value={draft.style}
        ariaLabel={translate("风格")}
        onValueChange={(value) => patchDraft({ style: value })}
      />
    </div>

    <div class="adjust-group">
      <span class="adjust-label">{translate("场景")} · {visibleScenes.length}</span>
      <div class="scene-tools">
        <div class="scene-search">
          <Search size={15} strokeWidth={2} />
          <Input
            class="h-9 pl-8"
            type="search"
            value={sceneQuery}
            aria-label={translate("搜索场景")}
            placeholder={translate("搜索场景")}
            oninput={(event) => (sceneQuery = event.currentTarget.value)}
          />
        </div>
        <AppSelect
          value={sceneCategory ?? ""}
          options={sceneCategoryOptions}
          ariaLabel={translate("场景分类")}
          onValueChange={(value) => (sceneCategory = (value || null) as SceneCategoryId | null)}
        />
      </div>
      <AppSelect
        value={draft.scene ?? ""}
        options={sceneSelectOptions}
        ariaLabel={translate("场景")}
        onValueChange={selectScene}
      />
    </div>

    <div class="adjust-group">
      <span class="adjust-label">{translate("模型")}</span>
      <AppSelect
        value={modelValue(draft.provider ?? "", draft.model ?? "")}
        options={modelOptions}
        ariaLabel={translate("模型")}
        disabled={!models.length}
        placeholder={translate("暂无可用模型")}
        onValueChange={selectModel}
      />
    </div>

    <div class="adjust-preview">
      <span class="adjust-label">{translate("当前输入")}</span>
      <p>{inputText || translate("尚未输入内容")}</p>
    </div>
  </div>

  <div slot="footer" class="adjust-footer">
    <Button variant="outline" onclick={onCancel}>{translate("取消")}</Button>
    <Button variant="default" onclick={onApply}>{translate("应用")}</Button>
  </div>
</DialogShell>

<style>
  .adjust-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-bottom: 4px;
  }

  .adjust-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .adjust-label {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-weight: 500;
  }

  .scene-tools {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(132px, 0.42fr);
    gap: 8px;
    align-items: center;
  }

  .scene-search {
    position: relative;
    display: flex;
    align-items: center;
  }

  .scene-search svg {
    position: absolute;
    top: 50%;
    left: 10px;
    z-index: 1;
    color: hsl(var(--muted-foreground));
    pointer-events: none;
    transform: translateY(-50%);
  }

  .adjust-preview {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    background: color-mix(in srgb, var(--surface, #f4f4f5) 72%, var(--page, #fff));
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
  }

  .adjust-preview p {
    margin: 0;
    overflow: hidden;
    color: hsl(var(--foreground));
    font-size: var(--font-body);
    line-height: var(--leading-prose);
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .adjust-footer {
    display: flex;
    gap: 8px;
  }

  @media (max-width: 620px) {
    .scene-tools {
      grid-template-columns: 1fr;
    }
  }
</style>
