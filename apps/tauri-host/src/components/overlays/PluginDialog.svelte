<script lang="ts">
  import { onMount } from "svelte";
  import Plug from "@lucide/svelte/icons/plug";
  import X from "@lucide/svelte/icons/x";

  interface Props {
    translate: (source: string, values?: Record<string, string | number>) => string;
    onManage: () => void;
    onClose: () => void;
  }

  let { translate, onManage, onClose }: Props = $props();
  let closeButton: HTMLButtonElement;
  onMount(() => closeButton?.focus());

  const plugins = [
    { name: "MiniMax 模型服务", description: "生成与优化文本", permission: "网络访问" },
    { name: "内置模板", description: "提供场景、风格与语言模板", permission: "本地内容" },
    { name: "场景识别", description: "根据当前文本选择适合的处理方式", permission: "本地文本" }
  ];
</script>

<div class="settings-layer" role="presentation">
  <div class="plugin-dialog" role="dialog" aria-modal="true" aria-label={translate("插件")}>
    <header class="settings-head">
      <div class="settings-title">
        <span class="settings-title-icon" aria-hidden="true"><Plug size={18} strokeWidth={2} /></span>
        <div><h2>{translate("插件")}</h2><p>{translate("查看当前可用能力及其访问范围。")}</p></div>
      </div>
      <button class="icon-button" type="button" aria-label={translate("关闭插件")} bind:this={closeButton} onclick={onClose}><X size={17} strokeWidth={2} /></button>
    </header>
    <div class="plugin-list">
      {#each plugins as plugin}
        <article class="plugin-row">
          <div><strong>{translate(plugin.name)}</strong><span>{translate(plugin.description)}</span></div>
          <span class="permission-badge">{translate(plugin.permission)}</span>
        </article>
      {/each}
    </div>
    <footer class="plugin-footer"><span>{translate("3 项内置能力")}</span><button class="primary small" type="button" onclick={onManage}>{translate("管理设置")}</button></footer>
  </div>
</div>
