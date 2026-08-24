<script lang="ts">
  import Settings2 from "@lucide/svelte/icons/settings-2";
  import X from "@lucide/svelte/icons/x";
  import type { DesktopStatus } from "../../domain/desktopBridge";
  import type { CloudQualityRelease, CloudQuota } from "../../domain/feedbackBridge";
  import {
    SETTINGS_PLUGIN_IDS,
    type HostSettingsDraft,
    type SettingsPluginId
  } from "../../domain/hostState";
  import type { ProviderOption } from "../../domain/providerCatalog";
  import type { OptimizeMode, OptimizeStyle } from "../../domain/reflexSession";
  import type { SecretStatus } from "../../domain/settingsApi";
  import type { SemanticModelState } from "../../domain/semanticModelState";
  import { settingsSections, type SettingsSection } from "./types";

  interface Props {
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
    translate: (source: string, values?: Record<string, string | number>) => string;
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
    translate,
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

<div class="settings-layer" role="presentation">
  <div class="settings-dialog" role="dialog" aria-modal="true" aria-label={translate("设置")}>
    <header class="settings-head">
      <div class="settings-title">
        <span class="settings-title-icon" aria-hidden="true"><Settings2 size={18} strokeWidth={2} /></span>
        <div>
          <h2>{translate("设置")}</h2>
          <p>{translate("管理模型、默认行为和本地隐私。")}</p>
        </div>
      </div>
      <button class="icon-button" type="button" aria-label={translate("关闭设置")} onclick={onClose}>
        <X size={17} strokeWidth={2} />
      </button>
    </header>

    <div class="settings-layout">
      <nav class="settings-nav" aria-label={translate("设置分类")}>
        {#each settingsSections as item}
          <button
            type="button"
            class:active={section === item.id}
            aria-pressed={section === item.id}
            onclick={() => onSectionChange(item.id)}
          >{translate(item.label)}</button>
        {/each}
      </nav>

      <div class="settings-content">
        {#if section === "provider"}
          <h3>{translate("模型与 Provider")}</h3>
          <div class="settings-grid">
            <label>
              <span>{translate("默认 Provider")}</span>
              <select value={draft.default_provider ?? "minimax"} disabled={busy} onchange={(event) => onProviderChange(event.currentTarget.value)}>
                {#each providers as provider}
                  <option value={provider.id}>
                    {translate(provider.label)}{provider.releaseStatus === "experimental" ? ` ${translate("（实验）")}` : ""}
                  </option>
                {/each}
              </select>
            </label>
            <label>
              <span>{translate("默认模型")}</span>
              <select value={draft.default_model ?? ""} disabled={busy} onchange={(event) => patchDraft({ default_model: event.currentTarget.value })}>
                {#each models as model}<option value={model.id}>{translate(model.label)}</option>{/each}
              </select>
            </label>
            {#if supportsCustomModel}
              <label>
                <span>{translate("自定义模型 ID")}</span>
                <input
                  value={customModelId}
                  disabled={busy}
                  autocomplete="off"
                  spellcheck="false"
                  maxlength="256"
                  placeholder="e.g. gpt-5.6-luna"
                  oninput={(event) => (customModelId = event.currentTarget.value)}
                />
              </label>
              <div class="model-candidate-actions">
                <button class="outline" type="button" disabled={busy || !customModelId.trim()} onclick={addCustomModel}>{translate("加入候选")}</button>
                <button class="outline danger" type="button" disabled={busy || models.length <= 1} onclick={removeSelectedModel}>{translate("移除当前")}</button>
              </div>
            {/if}
            {#if draft.default_provider !== "reflex-cloud"}
              <label class="settings-wide-field">
                <span>Base URL</span>
                <input
                  type="url"
                  value={draft.provider_endpoints[currentProviderId] ?? ""}
                  disabled={busy || providerConnectionBusy !== null}
                  autocomplete="url"
                  spellcheck="false"
                  maxlength="2048"
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
              <input
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
            <button class="outline" type="button" disabled={secretBusy} onclick={onSaveSecret}>
              {translate(secretBusy ? "正在保存" : "保存密钥")}
            </button>
            <button class="outline danger" type="button" disabled={secretBusy || !secretStatus.configured} onclick={onDeleteSecret}>
              {translate("删除密钥")}
            </button>
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
            <button class="outline" type="button" disabled={!providerConnectionReady || providerConnectionBusy !== null} onclick={onDiscoverModels}>
              {translate(providerConnectionBusy === "models" ? "正在获取模型" : "获取模型")}
            </button>
            <button class="outline" type="button" disabled={!providerConnectionReady || !draft.default_model || providerConnectionBusy !== null} onclick={onTestConnection}>
              {translate(providerConnectionBusy === "test" ? "正在测试连接" : "测试连接")}
            </button>
          </div>
          <p class="settings-feedback" role="status" aria-live="polite">{providerConnectionNotice ? translate(providerConnectionNotice) : ""}</p>
          {/if}
        {:else if section === "defaults"}
          <h3>{translate("默认行为")}</h3>
          <div class="settings-grid">
            <div>
              <span class="field-label">{translate("默认模式")}</span>
              <div class="segments compact">
                {#each modes as item}
                  <button type="button" class:active={draft.default_mode === item.id} onclick={() => patchDraft({ default_mode: item.id })}>{translate(item.label)}</button>
                {/each}
              </div>
            </div>
            <div>
              <span class="field-label">{translate("默认风格")}</span>
              <div class="segments compact">
                {#each styles as item}
                  <button type="button" class:active={draft.default_style === item.id} onclick={() => patchDraft({ default_style: item.id })}>{translate(item.label)}</button>
                {/each}
              </div>
            </div>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("场景识别策略")}</span>
            <div class="segments compact">
              {#each scenePolicies as item}
                <button type="button" class:active={draft.scene_policy === item.id} onclick={() => patchDraft({ scene_policy: item.id })}>{translate(item.label)}</button>
              {/each}
            </div>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("界面与输出语言")}</span>
            <div class="segments compact">
              {#each languages as item}
                <button type="button" class:active={draft.language === item.id} onclick={() => patchDraft({ language: item.id })}>{translate(item.label)}</button>
              {/each}
            </div>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("界面主题")}</span>
            <div class="segments compact">
              {#each themes as item}
                <button type="button" class:active={draft.theme === item.id} onclick={() => patchDraft({ theme: item.id })}>{translate(item.label)}</button>
              {/each}
            </div>
          </div>
          <label class="desktop-hotkey">
            <span>{translate("全局快捷键")}</span>
            <input value={draft.hotkey} disabled={busy} autocomplete="off" spellcheck="false" oninput={(event) => patchDraft({ hotkey: event.currentTarget.value })} />
            <small class:available={desktopStatus.hotkeyActive}>
              {translate(desktopStatus.message ?? (desktopStatus.hotkeyActive ? "当前快捷键已启用" : "保存后启用快捷键"))}
            </small>
          </label>
        {:else if section === "clipboard"}
          <h3>{translate("剪贴板")}</h3>
          <div class="settings-block">
            <span class="field-label">{translate("读取与替换策略")}</span>
            <div class="segments compact">
              {#each clipboardPolicies as item}
                <button type="button" class:active={draft.clipboard_policy === item.id} onclick={() => patchDraft({ clipboard_policy: item.id })}>{translate(item.label)}</button>
              {/each}
            </div>
            <p class="warning-note">{translate("自动替换会覆盖当前剪贴板内容，首次使用仍需确认。")}</p>
          </div>
        {:else if section === "privacy"}
          <h3>{translate("安全与隐私")}</h3>
          <div class="settings-choice-list">
            <label class="settings-toggle">
              <span><strong>{translate("参与匿名质量分析")}</strong><small>{translate("仅记录质量发布版本与反馈结果，不包含输入或输出正文，默认关闭")}</small></span>
              <input
                type="checkbox"
                checked={cloudUsageMetricsEnabled}
                disabled={busy || cloudPrivacyBusy}
                onchange={(event) => onCloudUsageMetricsChange(event.currentTarget.checked)}
              />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("加入产品改进计划")}</strong><small>{translate("仅在开启后保留脱敏的云端输入和结果，默认关闭")}</small></span>
              <input
                type="checkbox"
                checked={cloudImprovementEnabled}
                disabled={busy || cloudPrivacyBusy}
                onchange={(event) => onCloudImprovementChange(event.currentTarget.checked)}
              />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("主动反馈询问")}</strong><small>{translate("在若干次成功生成后偶尔询问结果是否有帮助")}</small></span>
              <input
                type="checkbox"
                checked={feedbackPromptEnabled}
                disabled={busy}
                onchange={(event) => onFeedbackPromptEnabledChange(event.currentTarget.checked)}
              />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("保存历史记录")}</strong><small>{translate("记录优化结果，便于稍后查看")}</small></span>
              <input type="checkbox" checked={draft.history_enabled} disabled={busy} onchange={(event) => patchDraft({ history_enabled: event.currentTarget.checked })} />
            </label>
            <label class="settings-toggle">
              <span><strong>{translate("隐私模式")}</strong><small>{translate("减少本地内容保留")}</small></span>
              <input type="checkbox" checked={draft.privacy_mode} disabled={busy} onchange={(event) => patchDraft({ privacy_mode: event.currentTarget.checked })} />
            </label>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("云端免费额度")}</span>
            <p class="warning-note">{translate(cloudQuotaText())}</p>
            <p class="warning-note">
              {cloudQualityRelease
                ? translate("当前质量发布：{version} · {title}", { version: cloudQualityRelease.release_version, title: cloudQualityRelease.title })
                : translate("当前尚无已发布的质量改进。")}
            </p>
            <div class="diagnostic-export-actions">
              <button class="outline" type="button" disabled={cloudPrivacyBusy} onclick={onCloudRefresh}>{translate("刷新额度")}</button>
              <button class="outline danger" type="button" disabled={cloudPrivacyBusy} onclick={onCloudDeleteData}>{translate("删除云端数据")}</button>
            </div>
            <p class="settings-feedback" role="status" aria-live="polite">{cloudPrivacyNotice ? translate(cloudPrivacyNotice) : ""}</p>
          </div>
          <div class="settings-block">
            <span class="field-label">{translate("历史内容处理")}</span>
            <div class="segments compact">
              {#each historyRedactions as item}
                <button type="button" class:active={draft.history_redaction === item.id} disabled={busy} onclick={() => patchDraft({ history_redaction: item.id })}>{translate(item.label)}</button>
              {/each}
            </div>
          </div>
          <section class="diagnostic-export-card" aria-label={translate("本地诊断包")}>
            <div>
              <strong>{translate("本地诊断包")}</strong>
              <p>{translate("仅导出脱敏的本地运行信息，不包含输入正文或密钥。")}</p>
            </div>
            <div class="diagnostic-export-actions">
              {#if diagnosticBusy}
                <button class="outline" type="button" onclick={onDiagnosticCancel}>{translate("取消导出")}</button>
              {:else}
                <button class="outline" type="button" onclick={onDiagnosticExport}>{translate("导出诊断包")}</button>
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
                <input
                  type="checkbox"
                  checked={draft.enabled_plugins.includes(plugin.id)}
                  disabled={busy}
                  onchange={(event) => onPluginChange(plugin.id, event.currentTarget.checked)}
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
                <button class="outline" type="button" disabled={!semanticActive || ["loading", "downloading", "deleting"].includes(semanticModel.phase)} onclick={onSemanticRefresh}>{translate("检查状态")}</button>
                {#if semanticModel.phase === "downloading"}
                  <button class="outline" type="button" onclick={onSemanticCancel}>{translate("取消下载")}</button>
                {:else if semanticModel.phase === "ready"}
                  <button class="outline danger" type="button" disabled={!semanticActive} onclick={onSemanticDelete}>{translate("删除模型")}</button>
                {:else}
                  <button class="primary small" type="button" disabled={!semanticActive || ["loading", "deleting"].includes(semanticModel.phase)} onclick={onSemanticDownload}>{translate("下载模型")}</button>
                {/if}
              </div>
            </section>
          {/if}
        {/if}
      </div>
    </div>

    <footer class="settings-footer">
      <p class="settings-save-notice" aria-live="polite">{notice ? translate(notice) : ""}</p>
      <button class="outline" type="button" disabled={busy} onclick={onClose}>{translate("取消")}</button>
      <button class="primary small" type="button" disabled={busy} onclick={onSave}>
        {translate(busy ? "正在保存" : "保存设置")}
      </button>
    </footer>
  </div>
</div>
