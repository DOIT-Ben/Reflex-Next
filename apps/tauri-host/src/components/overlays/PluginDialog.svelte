<script lang="ts">
  import { Button } from "@/components/ui/button";
  import DialogShell from "../ui/DialogShell.svelte";
  import { translator } from "../../domain/i18nStore";

  interface Props {
    onManage: () => void;
    onClose: () => void;
  }

  let { onManage, onClose }: Props = $props();
  let translate = $derived($translator);

  const plugins = [
    { name: "MiniMax 模型服务", description: "生成与优化文本", permission: "网络访问" },
    { name: "内置模板", description: "提供场景、风格与语言模板", permission: "本地内容" },
    { name: "场景识别", description: "根据当前文本选择适合的处理方式", permission: "本地文本" }
  ];
</script>

<DialogShell title={translate("插件")} description={translate("查看当前可用能力及其访问范围。")} z={30} closeLabel={translate("关闭插件")} onClose={onClose} size="sm">
  <div class="plugin-list">
    {#each plugins as plugin}
      <article class="plugin-row">
        <div><strong>{translate(plugin.name)}</strong><span>{translate(plugin.description)}</span></div>
        <span class="permission-badge">{translate(plugin.permission)}</span>
      </article>
    {/each}
  </div>
  <footer slot="footer" class="plugin-footer">
    <span>{translate("3 项内置能力")}</span>
    <Button variant="default" size="sm" onclick={onManage}>{translate("管理设置")}</Button>
  </footer>
</DialogShell>
