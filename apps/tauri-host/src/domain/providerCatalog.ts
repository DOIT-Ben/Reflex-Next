export type ProviderReleaseStatus = "supported" | "experimental";

export type ProviderModelOption = { id: string; label: string };

export type WorkbenchModelOption = ProviderModelOption & {
  providerId: string;
  providerLabel: string;
  isDefault: boolean;
};

export type ProviderOption = {
  id: string;
  label: string;
  models: ProviderModelOption[];
  defaultModel: string;
  releaseStatus: ProviderReleaseStatus;
  sessionConfigured: boolean;
  source: "runtime" | "cloud" | "fallback";
};

export type RuntimeProviderDescriptor = {
  id: string;
  name: string;
  models: string[];
  defaultModel: string;
  releaseStatus: ProviderReleaseStatus;
  sessionConfigured: boolean;
};

export type ProviderAvailability = "checking" | "ready" | "missing" | "unavailable";

const knownModelLabels: Record<string, string> = {
  "gpt-5.6-luna": "GPT-5.6 Luna",
  "claude-sonnet-4-20250514": "Claude Sonnet 4",
  "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-2.5-pro": "Gemini 2.5 Pro",
  "MiniMax-M2.7-highspeed": "M2.7 高速版",
  "deepseek-chat": "DeepSeek Chat",
  "deepseek-reasoner": "DeepSeek Reasoner",
  "qwen-turbo": "Qwen Turbo",
  "qwen-plus": "Qwen Plus",
  "qwen-max": "Qwen Max",
  "glm-4.5-air": "GLM-4.5 Air",
  "glm-4.7": "GLM-4.7",
  "deepseek-ai/DeepSeek-V3": "DeepSeek V3",
  "Qwen/Qwen2.5-72B-Instruct": "Qwen 2.5 72B"
};

const cloudProvider: ProviderOption = {
  id: "reflex-cloud",
  label: "Reflex Cloud",
  models: [{ id: "MiniMax-M2.7-highspeed", label: "云端 M2.7 高速版" }],
  defaultModel: "MiniMax-M2.7-highspeed",
  releaseStatus: "supported",
  sessionConfigured: true,
  source: "cloud"
};

export const fallbackProviderCatalog: ProviderOption[] = [
  cloudProvider,
  {
    id: "openai-responses",
    label: "OpenAI Responses",
    models: [{ id: "gpt-5.6-luna", label: "GPT-5.6 Luna" }],
    defaultModel: "gpt-5.6-luna",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "anthropic",
    label: "Anthropic",
    models: [
      { id: "claude-sonnet-4-20250514", label: "Claude Sonnet 4" },
      { id: "claude-3-5-haiku-20241022", label: "Claude 3.5 Haiku" }
    ],
    defaultModel: "claude-sonnet-4-20250514",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "gemini",
    label: "Google Gemini",
    models: [
      { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" }
    ],
    defaultModel: "gemini-2.5-flash",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "minimax",
    label: "MiniMax",
    models: [{ id: "MiniMax-M2.7-highspeed", label: "M2.7 高速版" }],
    defaultModel: "MiniMax-M2.7-highspeed",
    releaseStatus: "supported",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    models: [
      { id: "deepseek-chat", label: "DeepSeek Chat" },
      { id: "deepseek-reasoner", label: "DeepSeek Reasoner" }
    ],
    defaultModel: "deepseek-chat",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "qwen",
    label: "通义千问",
    models: [
      { id: "qwen-turbo", label: "Qwen Turbo" },
      { id: "qwen-plus", label: "Qwen Plus" },
      { id: "qwen-max", label: "Qwen Max" }
    ],
    defaultModel: "qwen-turbo",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    models: [
      { id: "glm-4.5-air", label: "GLM-4.5 Air" },
      { id: "glm-4.7", label: "GLM-4.7" }
    ],
    defaultModel: "glm-4.5-air",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  },
  {
    id: "siliconflow",
    label: "SiliconFlow",
    models: [
      { id: "deepseek-ai/DeepSeek-V3", label: "DeepSeek V3" },
      { id: "Qwen/Qwen2.5-72B-Instruct", label: "Qwen 2.5 72B" }
    ],
    defaultModel: "deepseek-ai/DeepSeek-V3",
    releaseStatus: "experimental",
    sessionConfigured: false,
    source: "fallback"
  }
];

// Browser previews and the Demo bridge need a deterministic catalog. A Tauri
// host replaces this list with the Runtime catalog after startup.
export const providerCatalog = fallbackProviderCatalog;

export function providerOptionsFromRuntime(
  descriptors: RuntimeProviderDescriptor[]
): ProviderOption[] {
  const runtimeOptions = descriptors.map((descriptor) => ({
    id: descriptor.id,
    label: descriptor.name,
    models: descriptor.models.map((id) => ({ id, label: knownModelLabels[id] ?? id })),
    defaultModel: descriptor.defaultModel,
    releaseStatus: descriptor.releaseStatus,
    sessionConfigured: descriptor.sessionConfigured,
    source: "runtime" as const
  }));
  return [cloudProvider, ...runtimeOptions.filter((provider) => provider.id !== cloudProvider.id)];
}

export function providerModels(
  providerId: string | null,
  catalog: readonly ProviderOption[] = providerCatalog
): ProviderOption["models"] {
  const normalized = providerId?.trim().toLowerCase();
  return catalog.find((provider) => provider.id === normalized)?.models ?? catalog[0]?.models ?? [];
}

export function providerDefaultModel(
  providerId: string | null,
  catalog: readonly ProviderOption[] = providerCatalog
): string | null {
  const normalized = providerId?.trim().toLowerCase();
  const provider = catalog.find((candidate) => candidate.id === normalized);
  return provider?.defaultModel ?? provider?.models[0]?.id ?? catalog[0]?.models[0]?.id ?? null;
}

export function workbenchModelOptions(
  config: Record<string, unknown> | null,
  catalog: readonly ProviderOption[] = providerCatalog
): WorkbenchModelOption[] {
  const configured = configuredProviderModels(config?.provider_models);
  const defaultProvider = typeof config?.provider === "string"
    ? config.provider.trim().toLowerCase()
    : "";
  const defaultModel = typeof config?.model === "string" ? config.model.trim() : "";
  const providers = configured.size > 0
    ? catalog.filter((provider) => configured.has(provider.id))
    : catalog.filter((provider) =>
        provider.source === "cloud" ||
        provider.sessionConfigured ||
        provider.id === defaultProvider
      );

  return providers.flatMap((provider) => {
    const configuredIds = configured.get(provider.id);
    const models = configuredIds
      ? configuredIds.map((id) => provider.models.find((model) => model.id === id) ?? { id, label: id })
      : provider.models;
    return models.map((model) => ({
      ...model,
      providerId: provider.id,
      providerLabel: provider.label,
      isDefault: provider.id === defaultProvider && model.id === defaultModel
    }));
  });
}

function configuredProviderModels(value: unknown): Map<string, string[]> {
  const result = new Map<string, string[]>();
  if (!value || typeof value !== "object" || Array.isArray(value)) return result;
  for (const [providerId, rawModels] of Object.entries(value)) {
    const normalizedProvider = providerId.trim().toLowerCase();
    if (!/^[a-z0-9._-]{1,64}$/.test(normalizedProvider) || !Array.isArray(rawModels)) continue;
    const models = [...new Set(rawModels
      .filter((model): model is string => typeof model === "string")
      .map((model) => model.trim())
      .filter((model) => model.length > 0 && model.length <= 256))];
    if (models.length > 0) result.set(normalizedProvider, models);
  }
  return result;
}

export function providerName(
  providerId: string | null,
  catalog: readonly ProviderOption[] = providerCatalog
): string {
  const normalized = providerId?.trim().toLowerCase();
  return catalog.find((provider) => provider.id === normalized)?.label ?? providerId ?? "未配置";
}

export function withConfiguredModels(
  catalog: readonly ProviderOption[],
  configuredModels: Record<string, string[]>
): ProviderOption[] {
  return catalog.map((provider) => {
    const models = configuredModels[provider.id];
    if (!models?.length) return { ...provider, models: provider.models.map((model) => ({ ...model })) };
    const options = [...new Set(models)].map((id) => ({ id, label: knownModelLabels[id] ?? id }));
    return {
      ...provider,
      models: options,
      defaultModel: options.some((model) => model.id === provider.defaultModel)
        ? provider.defaultModel
        : options[0].id
    };
  });
}

export function resolveProviderAvailability(
  providerId: string | null,
  secretStatus: { providerId: string; configured: boolean } | null,
  settingsReady: boolean,
  statusError: boolean,
  cloudAvailability: ProviderAvailability = "checking"
): ProviderAvailability {
  if (!settingsReady || !providerId) return "checking";

  const activeId = providerId.trim().toLowerCase();
  if (activeId === "reflex-cloud") return cloudAvailability;
  if (statusError) return "unavailable";
  if (!secretStatus) return "checking";
  const statusId = secretStatus.providerId.trim().toLowerCase();
  if (!activeId || activeId !== statusId) return "checking";
  return secretStatus.configured ? "ready" : "missing";
}
