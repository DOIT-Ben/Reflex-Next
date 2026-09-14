<script lang="ts">
  import { translator } from "../../domain/i18nStore";
  import Search from "@lucide/svelte/icons/search";
  import type { SceneOption } from "../../domain/reflexSession";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { Input } from "@/components/ui/input";
  import { Button } from "@/components/ui/button";

  interface Props {
    search: string;
    scene: string;
    style: string;
    provider: string;
    scenes: SceneOption[];
    styles: Array<{ id: string; label: string }>;

    onSearchChange: (value: string) => void;
    onSceneChange: (value: string) => void;
    onStyleChange: (value: string) => void;
    onProviderChange: (value: string) => void;
    onSubmit: () => void;
  }

  let { search, scene, style, provider, scenes, styles, onSearchChange, onSceneChange, onStyleChange, onProviderChange, onSubmit }: Props = $props();
  let translate = $derived($translator);
  let sceneOptions = $derived([
    { value: "", label: translate("全部场景") },
    ...scenes.map((item) => ({ value: item.id, label: translate(item.label) }))
  ]);
  let styleOptions = $derived([
    { value: "", label: translate("全部风格") },
    ...styles.map((item) => ({ value: item.id, label: translate(item.label) }))
  ]);
</script>

<section class="history-tools" aria-label={translate("筛选")}>
  <Input class="h-8" aria-label={translate("搜索历史记录")} value={search} placeholder={translate("搜索历史记录")} oninput={(event) => onSearchChange(event.currentTarget.value)} onkeydown={(event) => event.key === "Enter" && onSubmit()} />
  <AppSelect ariaLabel={translate("场景筛选")} value={scene} options={sceneOptions} size="sm" onValueChange={onSceneChange} />
  <AppSelect ariaLabel={translate("风格筛选")} value={style} options={styleOptions} size="sm" onValueChange={onStyleChange} />
  <Input class="h-8" aria-label={translate("Provider 筛选")} value={provider} placeholder={translate("全部 Provider")} oninput={(event) => onProviderChange(event.currentTarget.value)} onkeydown={(event) => event.key === "Enter" && onSubmit()} />
  <Button variant="outline" size="sm" onclick={onSubmit}><Search size={15} strokeWidth={2} />{translate("筛选")}</Button>
</section>
