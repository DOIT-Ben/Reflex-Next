<script lang="ts">
  import { onMount, tick } from "svelte";
  import type { DesktopStatus } from "../../domain/desktopBridge";
  import type { CloudQualityRelease, CloudQuota } from "../../domain/feedbackBridge";
  import {
    SETTINGS_PLUGIN_IDS,
    type HostSettingsDraft,
    type SettingsPluginId
  } from "../../domain/hostState";
  import { translator } from "../../domain/i18nStore";
  import type { ProviderOption } from "../../domain/providerCatalog";
  import type { OptimizeMode, OptimizeStyle } from "../../domain/reflexSession";
  import type { SecretStatus } from "../../domain/settingsApi";
  import type { SemanticModelState } from "../../domain/semanticModelState";
  import DialogShell from "../ui/DialogShell.svelte";
  import { Button } from "@/components/ui/button";
  import SegmentedControl from "@/components/ui/SegmentedControl.svelte";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { Input } from "@/components/ui/input";
  import { Switch } from "@/components/ui/switch";
  import { settingsSections, type SettingsSection } from "./types";

  interface Props {
    variant?: "dialog" | "page";
    draft: HostSettingsDraft;
    section: SettingsSection;
    busy: boolean;
    secretBusy: boolean;
    secretInput: string;
    secretStatus: SecretStatus;
    secretNotice: string | null;
    providerConnectionBusy: "models" | "test" | null;
    providerConnectionNotice: string | null;
    notice: string | null;
    providerCatalogNotice: string | null;
    providers: ProviderOption[];
    models: ProviderOption["models"];
    modes: Array<{ id: OptimizeMode; label: string }>;
    styles: Array<{ id: OptimizeStyle; label: string }>;
    desktopStatus: DesktopStatus;
    semanticModel: SemanticModelState;
    semanticEnabled: boolean;
    semanticActive: boolean;
    semanticStatusText: string;
    diagnosticBusy: boolean;
    diagnosticNotice: string | null;
    cloudUsageMetricsEnabled: boolean;
    cloudImprovementEnabled: boolean;
    feedbackPromptEnabled: boolean;
    cloudQualityRelease: CloudQualityRelease | null;
    cloudQuota: CloudQuota | null;
    cloudPrivacyBusy: boolean;
    cloudPrivacyNotice: string | null;
    onClose: () => void;
    onSave: () => void;
    onSectionChange: (section: SettingsSection) => void;
    onDraftChange: (draft: HostSettingsDraft) => void;
    onProviderChange: (provider: string) => void;
    onSecretInput: (value: string) => void;
    onSaveSecret: () => void;
    onDeleteSecret: () => void;
    onBaseUrlChange: (value: string) => void;
    onDiscoverModels: () => void;
    onTestConnection: () => void;
    onModelCandidatesChange: (models: string[]) => void;
    onPluginChange: (plugin: SettingsPluginId, enabled: boolean) => void;
    onSemanticRefresh: () => void;
    onSemanticCancel: () => void;
    onSemanticDelete: () => void;
    onSemanticDownload: () => void;
    onDiagnosticExport: () => void;
    onDiagnosticCancel: () => void;
    onCloudUsageMetricsChange: (enabled: boolean) => void;
    onCloudImprovementChange: (enabled: boolean) => void;
    onFeedbackPromptEnabledChange: (enabled: boolean) => void;
    onCloudRefresh: () => void;
    onCloudDeleteData: () => void;
  }

  let {
    variant = "dialog",
    draft,
    section,
    busy,
    secretBusy,
    secretInput,
    secretStatus,
    secretNotice,
    providerConnectionBusy,
    providerConnectionNotice,
    notice,
    providerCatalogNotice,
    providers,
    models,
    modes,
    styles,
    desktopStatus,
    semanticModel,
    semanticEnabled,
    semanticActive,
    semanticStatusText,
    diagnosticBusy,
    diagnosticNotice,
    cloudUsageMetricsEnabled,
    cloudImprovementEnabled,
    feedbackPromptEnabled,
    cloudQualityRelease,
    cloudQuota,
    cloudPrivacyBusy,
    cloudPrivacyNotice,
    onClose,
    onSave,
    onSectionChange,
    onDraftChange,
    onProviderChange,
    onSecretInput,
    onSaveSecret,
    onDeleteSecret,
    onBaseUrlChange,
    onDiscoverModels,
    onTestConnection,
    onModelCandidatesChange,
    onPluginChange,
    onSemanticRefresh,
    onSemanticCancel,
    onSemanticDelete,
    onSemanticDownload,
    onDiagnosticExport,
    onDiagnosticCancel,
    onCloudUsageMetricsChange,
    onCloudImprovementChange,
    onFeedbackPromptEnabledChange,
    onCloudRefresh,
    onCloudDeleteData
  }: Props = $props();
  let translate = $derived($translator);
  let body: HTMLDivElement | undefined;
  let restoreFocus: HTMLElement | null = null;
  const focusableSelector =
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

  function focusableElements(): HTMLElement[] {
    return Array.from(body?.querySelectorAll<HTMLElement>(focusableSelector) ?? []).filter(
      (element) => element.offsetWidth > 0 || element.offsetHeight > 0
    );
  }

  function canRestoreFocus(element: HTMLElement | null): element is HTMLElement {
    return Boolean(
      element?.isConnected &&
        element !== document.body &&
        element !== document.documentElement &&
        !element.closest("[inert]")
    );
  }

  onMount(() => {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void tick().then(() => focusableElements()[0]?.focus());
    return () => {
      const fallback = document.querySelector<HTMLElement>("[data-dialog-focus-fallback]");
      if (canRestoreFocus(restoreFocus)) {
        restoreFocus.focus();
      } else {
        fallback?.focus();
      }
    };
  });

  let selectedProvider = $derived(
    providers.find((provider) => provider.id === (draft.default_provider ?? "minimax"))
  );
  let supportsCustomModel = $derived(draft.default_provider !== "reflex-cloud");
  let currentProviderId = $derived(draft.default_provider ?? "minimax");
  let providerCredentialReady = $derived(secretStatus.configured);
  let providerConnectionReady = $derived(
    currentProviderId === "reflex-cloud" || (
      providerCredentialReady && Boolean((draft.provider_endpoints[currentProviderId] ?? "").trim())
    )
  );
  let providerSelectOptions = $derived(
    providers.map((provider) => ({
      value: provider.id,
      label: `${translate(provider.label)}${provider.releaseStatus === "experimental" ? ` ${translate("（实验）")}` : ""}`
    }))
  );
  let modelSelectOptions = $derived(
    models.map((model) => ({ value: model.id, label: translate(model.label) }))
  );

  const scenePolicies: Array<{ id: HostSettingsDraft["scene_policy"]; label: string }> = [
    { id: "auto", label: "自动" },
    { id: "ask", label: "每次询问" }
  ];
  const clipboardPolicies: Array<{ id: HostSettingsDraft["clipboard_policy"]; label: string }> = [
    { id: "startup", label: "启动时读取" },
    { id: "manual", label: "仅手动读取" },
    { id: "auto_replace", label: "生成后自动替换" }
  ];
  const historyRedactions: Array<{ id: HostSettingsDraft["history_redaction"]; label: string }> = [
    { id: "secrets", label: "隐藏敏感内容" },
    { id: "none", label: "保留原文" }
  ];
  const languages: Array<{ id: HostSettingsDraft["language"]; label: string }> = [
    { id: "zh-CN", label: "简体中文" },
    { id: "en-US", label: "English" }
  ];
  const themes: Array<{ id: HostSettingsDraft["theme"]; label: string }> = [
    { id: "system", label: "跟随系统" },
    { id: "light", label: "浅色" },
    { id: "dark", label: "深色" }
  ];
  const plugins: Array<{ id: SettingsPluginId; label: string; description: string }> = [
    { id: SETTINGS_PLUGIN_IDS[0], label: "翻译", description: "跨语言转换" },
    { id: SETTINGS_PLUGIN_IDS[1], label: "Markdown 预览", description: "渲染 Markdown 内容" },
    { id: SETTINGS_PLUGIN_IDS[2], label: "批处理", description: "导入与导出批量提示词" },
    { id: SETTINGS_PLUGIN_IDS[3], label: "语义识别", description: "使用已安装的本地模型增强场景识别" }
  ];

  function patchDraft(patch: Partial<HostSettingsDraft>) {
    onDraftChange({ ...draft, ...patch });
  }

  let customModelId = $state("");
  function addCustomModel() {
    const modelId = customModelId.trim();
    if (!modelId || modelId.length > 256 || models.some((model) => model.id === modelId)) return;
    onModelCandidatesChange([...models.map((model) => model.id), modelId]);
    patchDraft({ default_model: modelId });
    customModelId = "";
  }

  function removeSelectedModel() {
    const modelId = draft.default_model?.trim() ?? "";
    const remaining = models.map((model) => model.id).filter((id) => id !== modelId);
    if (remaining.length === 0) return;
    onModelCandidatesChange(remaining);
    patchDraft({ default_model: remaining[0] });
  }

  function pluginDescription(plugin: (typeof plugins)[number]) {
    if (plugin.id !== "semantic-detector") return plugin.description;
    return semanticEnabled
      ? "已启用。仅在优化时检查已安装的本地模型；模型不可用时自动回退通用场景。"
      : "未启用。启用后只检查本地已安装模型，不会自动下载。";
  }

  function cloudQuotaText() {
    if (!cloudQuota) return "额度状态暂不可用";
    const remaining = Math.max(0, cloudQuota.requests_limit - cloudQuota.requests_used);
    return `今日剩余 ${remaining} / ${cloudQuota.requests_limit} 次`;
  }
</script>

<DialogShell
  {variant}
  title={translate("设置")}
  description={translate("管理模型、默认行为和本地隐私。")}
  size="sheet"
  z={30}
  closeLabel={translate("关闭设置")}
  onClose={onClose}
  autofocusClose={false}
>
  <div class="settings-body" bind:this={body}>
    <nav class="settings-nav" aria-label={translate("设置分类")}>
      {#each settingsSections as item}
        <Button
          variant={section === item.id ? "secondary" : "ghost"}
          size="sm"
          class={`settings-nav-item${section === item.id ? " settings-nav-item-active" : ""}`}
          aria-pressed={section === item.id}
          onclick={() => onSectionChange(item.id)}
        ><span class="text-xs font-medium">{translate(item.label)}</span></Button>
      {/each}
    </nav>

    <div class="settings-layout">
      <div class="settings-content">
        {#if section === "provider"}
          <h3>{translate("模型与 Provider")}</h3>
          <div class="settings-grid">
            <label>
              <span>{translate("默认 Provider")}</span>
              <AppSelect
                value={draft.default_provider ?? "minimax"}
                options={providerSelectOptions}
                ariaLabel={translate("默认 Provider")}
                disabled={busy}
                onValueChange={onProviderChange}
              />
            </label>
            <label>
              <span>{translate("默认模型")}</span>
              <AppSelect
                value={draft.default_model ?? ""}
                options={modelSelectOptions}
                ariaLabel={translate("默认模型")}
                placeholder={translate("暂无可用模型")}
                disabled={busy || !models.length}
                onValueChange={(value) => patchDraft({ default_model: value })}
              />
            </label>
            {#if supportsCustomModel}
              <label>
                <span>{translate("自定义模型 ID")}</span>
                <Input
                  value={customModelId}
                  disabled={busy}
                  autocomplete="off"
                  spellcheck="false"
                  maxlength={256}
                  placeholder="e.g. gpt-5.6-luna"
                  oninput={(event) => (customModelId = event.currentTarget.value)}
                />
              </label>
              <div class="model-candidate-actions">
                <Button variant="outline" disabled={busy || !customModelId.trim()} onclick={addCustomModel}>{translate("加入候选")}</Button>
                <Button variant="outline" class="text-destructive hover:text-destructive" disabled={busy || models.length < 1} onclick={removeSelectedModel}>{translate("移除当前")}</Button>
              </div>
            {/if}
            {#if draft.default_provider !== "reflex-cloud"}
              <label class="settings-wide-field">
                <span>Base URL</span>
                <Input
                  type="url"
                  value={draft.provider_endpoints[currentProviderId] ?? ""}
                  disabled={busy || providerConnectionBusy !== null}
                  autocomplete="url"
                  spellcheck="false"
                  maxlength={2048}
                  placeholder="https://api.example.com/v1"
                  oninput={(event) => onBaseUrlChange(event.currentTarget.value)}
                />
              </label>
            {/if}
          </div>
          {#if providerCatalogNotice}
            <p class="settings-feedback" role="status" aria-live="polite">{translate(providerCatalogNotice)}</p>
          {/if}
          {#if selectedProvider?.releaseStatus === "experimental"}
            <p class="warning-note" role="status">
              {translate("此 Provider 仍在实验支持阶段，协议或模型可用性可能变化。")}
            </p>
          {/if}

          {#if draft.default_provider === "reflex-cloud"}
            <div class="credential-status configured">
              <span class="status-dot" aria-hidden="true"></span>
              <div>
                <strong>{translate("无需本地 API Key")}</strong>
                <span>{translate("使用 Reflex Cloud 免费额度")}</span>
              </div>
            </div>
          {:else}
          <div class="api-key-row">
            <label>
              <span>API Key</span>
              <Input
                type="password"
                value={secretInput}
                autocomplete="off"
                spellcheck="false"
                disabled={secretBusy}
                placeholder={translate("输入新的 API Key")}
                aria-describedby="secret-feedback"
                oninput={(event) => onSecretInput(event.currentTarget.value)}
              />
            </label>
            <Button variant="outline" size="sm" disabled={secretBusy} onclick={onSaveSecret}>
              {translate(secretBusy ? "正在保存" : "保存密钥")}
            </Button>
            <Button variant="outline" size="sm" class="text-destructive hover:text-destructive" disabled={secretBusy || !secretStatus.configured} onclick={onDeleteSecret}>
              {translate("删除密钥")}
            </Button>
          </div>
          <p id="secret-feedback" class="settings-feedback" aria-live="polite">
            {translate(secretNotice ?? "密钥只保存在系统安全存储中，输入不会保留。")}
          </p>
          <div class="credential-status" class:configured={secretStatus.configured}>
            <span class="status-dot" aria-hidden="true"></span>
            <div>
              <strong>{translate(secretStatus.configured ? "密钥已保存" : "尚未配置密钥")}</strong>
              <span>
                {secretStatus.configured && secretStatus.maskedTail
                  ? translate("尾号 {tail}", { tail: secretStatus.maskedTail })
                  : translate("保存后即可使用当前 Provider")}
              </span>
            </div>
          </div>
          <div class="provider-connection-actions">
            <Button variant="outline" size="sm" disabled={!providerConnectionReady || providerConnectionBusy !== null} onclick={onDiscoverModels}>
              {translate(providerConnectionBusy === "models" ? "正在获取模型" : "获取模型")}
            </Button>
            <Button variant="outline" size="sm" disabled={!providerConnectionReady || !draft.default_model || providerConnectionBusy !== null} onclick={onTestConnection}>
              {translate(providerConnectionBusy === "test" ? "正在测试连接" : "测试连接")}
            </Button>
          </div>
          <p class="settings-feedback" role="status" aria-live="polite">{providerConnectionNotice ? translate(providerConnectionNotice) : ""}</p>
          {/if}
        {:else if section === "defaults"}
          <h3>{translate("默认行为")}</h3>
          <div class="settings-block">
            <span class="field-label">{translate("默认模式")}</span>
            <SegmentedControl
              options={modes.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.default_mode}
              onValueChange={(value) => patchDraft({ default_mode: value })} 
            />
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("默认风格")}</span>
            <SegmentedControl
              options={styles.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.default_style}
              onValueChange={(value) => patchDraft({ default_style: value })} 
            />
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("场景识别策略")}</span>
            <SegmentedControl
              options={scenePolicies.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.scene_policy}
              onValueChange={(value) => patchDraft({ scene_policy: value })} 
            />
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("界面与输出语言")}</span>
            <SegmentedControl
              options={languages.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.language}
              onValueChange={(value) => patchDraft({ language: value })} 
            />
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("界面主题")}</span>
            <SegmentedControl
              options={themes.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.theme}
              onValueChange={(value) => patchDraft({ theme: value })} 
            />
          </div>
          <label class="desktop-hotkey">
            <span>{translate("全局快捷键")}</span>
            <input value={draft.hotkey} disabled={busy} autocomplete="off" spellcheck="false" oninput={(event) => patchDraft({ hotkey: event.currentTarget.value })} />
            <small class:available={desktopStatus.hotkeyActive}>
              {translate(desktopStatus.message ?? (desktopStatus.hotkeyActive ? "当前快捷键已启用" : "保存后启用快捷键"))}
            </small>
          </label>
          <label class="desktop-hotkey">
            <span>{translate("快捷面板快捷键")}</span>
            <input value={draft.panel_hotkey} disabled={busy} autocomplete="off" spellcheck="false" oninput={(event) => patchDraft({ panel_hotkey: event.currentTarget.value })} />
            <small class:available={desktopStatus.panelHotkeyActive}>
              {translate(desktopStatus.panelMessage ?? (desktopStatus.panelHotkeyActive ? "当前快捷键已启用" : "保存后启用快捷键"))}
            </small>
          </label>
          <div class="desktop-hotkey checkbox-row">
            <span>{translate("开机自动启动（静默进入托盘）")}</span>
            <Switch
              checked={draft.autostart_enabled}
              disabled={busy}
              onCheckedChange={(checked) => patchDraft({ autostart_enabled: checked })}
            />
          </div>
        {:else if section === "clipboard"}
          <h3>{translate("剪贴板")}</h3>
          <div class="settings-block">
            <span class="field-label">{translate("读取与替换策略")}</span>
            <SegmentedControl
              options={clipboardPolicies.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.clipboard_policy}
              onValueChange={(value) => patchDraft({ clipboard_policy: value })} 
            />
            <p class="warning-note">{translate("自动替换会覆盖当前剪贴板内容，首次使用仍需确认。")}</p>
          </div>
        {:else if section === "privacy"}
          <h3>{translate("安全与隐私")}</h3>
          <div class="settings-choice-list">
            <label class="settings-toggle">
              <span><strong>{translate("参与匿名质量分析")}</strong><small>{translate("仅记录质量发布版本与反馈结果，不包含输入或输出正文，默认关闭")}</small></span>
              <Switch checked={cloudUsageMetricsEnabled} disabled={busy || cloudPrivacyBusy} onCheckedChange={(checked) => onCloudUsageMetricsChange(checked)} />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("加入产品改进计划")}</strong><small>{translate("仅在开启后保留脱敏的云端输入和结果，默认关闭")}</small></span>
              <Switch checked={cloudImprovementEnabled} disabled={busy || cloudPrivacyBusy} onCheckedChange={(checked) => onCloudImprovementChange(checked)} />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("主动反馈询问")}</strong><small>{translate("在若干次成功生成后偶尔询问结果是否有帮助")}</small></span>
              <Switch checked={feedbackPromptEnabled} disabled={busy} onCheckedChange={(checked) => onFeedbackPromptEnabledChange(checked)} />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("保存历史记录")}</strong><small>{translate("记录优化结果，便于稍后查看")}</small></span>
              <Switch
                checked={draft.history_enabled}
                disabled={busy}
                onCheckedChange={(checked) => patchDraft({ history_enabled: checked })}
              />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("隐私模式")}</strong><small>{translate("减少本地内容保留")}</small></span>
              <Switch
                checked={draft.privacy_mode}
                disabled={busy}
                onCheckedChange={(checked) => patchDraft({ privacy_mode: checked })}
              />
            </label>
          </div>
          <div class="settings-block stacked">
            <span class="field-label">{translate("云端免费额度")}</span>
            <p class="warning-note">{translate(cloudQuotaText())}</p>
            <p class="warning-note">
              {cloudQualityRelease
                ? translate("当前质量发布：{version} · {title}", { version: cloudQualityRelease.release_version, title: cloudQualityRelease.title })
                : translate("当前尚无已发布的质量改进。")}
            </p>
            <div class="diagnostic-export-actions">
              <Button variant="outline" disabled={cloudPrivacyBusy} onclick={onCloudRefresh}>{translate("刷新额度")}</Button>
              <Button variant="outline" class="text-destructive hover:text-destructive" disabled={cloudPrivacyBusy} onclick={onCloudDeleteData}>{translate("删除云端数据")}</Button>
            </div>
            <p class="settings-feedback" role="status" aria-live="polite">{cloudPrivacyNotice ? translate(cloudPrivacyNotice) : ""}</p>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("历史内容处理")}</span>
            <SegmentedControl
              options={historyRedactions.map((item) => ({ id: item.id, label: translate(item.label) }))}
              value={draft.history_redaction}
              disabled={busy}
              onValueChange={(value) => patchDraft({ history_redaction: value })} 
            />
          </div>
          <section class="diagnostic-export-card" aria-label={translate("本地诊断包")}>
            <div>
              <strong>{translate("本地诊断包")}</strong>
              <p>{translate("仅导出脱敏的本地运行信息，不包含输入正文或密钥。")}</p>
            </div>
            <div class="diagnostic-export-actions">
              {#if diagnosticBusy}
                <Button variant="outline" onclick={onDiagnosticCancel}>{translate("取消导出")}</Button>
              {:else}
                <Button variant="outline" onclick={onDiagnosticExport}>{translate("导出诊断包")}</Button>
              {/if}
            </div>
            <p class="settings-feedback" role="status" aria-live="polite">{diagnosticNotice ? translate(diagnosticNotice) : ""}</p>
          </section>
        {:else}
          <h3>{translate("插件")}</h3>
          <div class="settings-choice-list">
            {#each plugins as plugin}
              <label class="settings-toggle">
                <span><strong>{translate(plugin.label)}</strong><small>{translate(pluginDescription(plugin))}</small></span>
                <Switch
                  checked={draft.enabled_plugins.includes(plugin.id)}
                  disabled={busy}
                  onCheckedChange={(checked) => onPluginChange(plugin.id, checked)}
                />
              </label>
            {/each}
          </div>
          {#if semanticEnabled}
            <section
              class="semantic-model-card"
              class:semantic-model-ready={semanticModel.phase === "ready"}
              class:semantic-model-error={semanticModel.phase === "error"}
              aria-label={translate("本地语义模型")}
              aria-busy={semanticModel.phase === "loading" || semanticModel.phase === "downloading" || semanticModel.phase === "deleting"}
            >
              <div>
                <strong>{translate("本地语义模型")}</strong>
                <p class:semantic-model-status-error={semanticModel.phase === "error"} role={semanticModel.phase === "error" ? "alert" : "status"} aria-live="polite">{translate(semanticStatusText)}</p>
              </div>
              {#if semanticModel.phase === "downloading"}
                <progress max="100" value={semanticModel.percent} aria-label={translate("模型下载进度")}></progress>
              {/if}
              <div class="semantic-model-actions">
                <Button variant="outline" disabled={!semanticActive || ["loading", "downloading", "deleting"].includes(semanticModel.phase)} onclick={onSemanticRefresh}>{translate("检查状态")}</Button>
                {#if semanticModel.phase === "downloading"}
                  <Button variant="outline" onclick={onSemanticCancel}>{translate("取消下载")}</Button>
                {:else if semanticModel.phase === "ready"}
                  <Button variant="outline" class="text-destructive hover:text-destructive" disabled={!semanticActive} onclick={onSemanticDelete}>{translate("删除模型")}</Button>
                {:else}
                  <Button variant="default" size="sm" disabled={!semanticActive || ["loading", "deleting"].includes(semanticModel.phase)} onclick={onSemanticDownload}>{translate("下载模型")}</Button>
                {/if}
              </div>
            </section>
          {/if}
        {/if}
      </div>
    </div>
  </div>

  <div class="settings-footer" slot="footer">
    <p class="settings-save-notice" aria-live="polite">{notice ? translate(notice) : ""}</p>
    {#if variant !== "page"}
      <Button variant="outline" size="sm" disabled={busy} onclick={onClose}>{translate("取消")}</Button>
    {/if}
    <Button disabled={busy} onclick={onSave}>
      {translate(busy ? "正在保存" : "保存设置")}
    </Button>
  </div>
</DialogShell>

<style>
  .settings-body {
    display: flex;
    flex-direction: column;
    gap: 16px;
    height: 100%;
    min-height: 0;
  }

  .settings-body :global(.settings-layout) {
    flex: 1 1 auto;
    min-height: 0;
  }

  .settings-footer {
    flex: 0 0 auto;
    min-width: 0;
  }
</style>
