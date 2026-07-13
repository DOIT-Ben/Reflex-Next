<script lang="ts">
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import X from "@lucide/svelte/icons/x";
  import type { RequestSettings } from "../../domain/hostState";
  import type { OptimizeMode, OptimizeStyle, SceneOption } from "../../domain/reflexSession";

  interface Props {
    draft: RequestSettings;
    inputText: string;
    modes: Array<{ id: OptimizeMode; label: string }>;
    styles: Array<{ id: OptimizeStyle; label: string }>;
    scenes: SceneOption[];
    models: Array<{ id: string; label: string }>;
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

  function patchDraft(patch: Partial<RequestSettings>) {
    onDraftChange({ ...draft, ...patch });
  }

  function selectScene(value: string) {
    patchDraft({ scene: value.trim() || null });
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

      <label class="adjust-field">
        <span>{translate("场景")}</span>
        <select value={draft.scene ?? ""} onchange={(event) => selectScene(event.currentTarget.value)}>
          <option value="">{translate("自动识别")}</option>
          {#each scenes as scene}
            <option value={scene.id}>{translate(scene.label)}</option>
          {/each}
        </select>
      </label>

      <label class="adjust-field">
        <span>{translate("模型")}</span>
        <select value={draft.model ?? ""} onchange={(event) => patchDraft({ model: event.currentTarget.value })}>
          {#each models as model}<option value={model.id}>{translate(model.label)}</option>{/each}
        </select>
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
