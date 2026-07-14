<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import type { SceneOption } from "../../domain/reflexSession";

  interface Props {
    search: string;
    scene: string;
    style: string;
    provider: string;
    scenes: SceneOption[];
    styles: Array<{ id: string; label: string }>;
    translate: (source: string, values?: Record<string, string | number>) => string;
    onSearchChange: (value: string) => void;
    onSceneChange: (value: string) => void;
    onStyleChange: (value: string) => void;
    onProviderChange: (value: string) => void;
    onSubmit: () => void;
  }

  let { search, scene, style, provider, scenes, styles, translate, onSearchChange, onSceneChange, onStyleChange, onProviderChange, onSubmit }: Props = $props();
</script>

<section class="history-tools" aria-label={translate("筛选")}>
  <input aria-label={translate("搜索历史记录")} value={search} placeholder={translate("搜索历史记录")} oninput={(event) => onSearchChange(event.currentTarget.value)} onkeydown={(event) => event.key === "Enter" && onSubmit()} />
  <select aria-label={translate("场景筛选")} value={scene} onchange={(event) => onSceneChange(event.currentTarget.value)}><option value="">{translate("全部场景")}</option>{#each scenes as item (item.id)}<option value={item.id}>{translate(item.label)}</option>{/each}</select>
  <select aria-label={translate("风格筛选")} value={style} onchange={(event) => onStyleChange(event.currentTarget.value)}><option value="">{translate("全部风格")}</option>{#each styles as item (item.id)}<option value={item.id}>{translate(item.label)}</option>{/each}</select>
  <input aria-label={translate("Provider 筛选")} value={provider} placeholder={translate("全部 Provider")} oninput={(event) => onProviderChange(event.currentTarget.value)} onkeydown={(event) => event.key === "Enter" && onSubmit()} />
  <button type="button" onclick={onSubmit}><Search size={15} strokeWidth={2} />{translate("筛选")}</button>
</section>
