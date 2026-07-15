export type ProviderReleaseStatus = "supported" | "experimental";

export type ProviderModelOption = { id: string; label: string };

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

export function providerName(
  providerId: string | null,
  catalog: readonly ProviderOption[] = providerCatalog
): string {
  const normalized = providerId?.trim().toLowerCase();
  return catalog.find((provider) => provider.id === normalized)?.label ?? providerId ?? "未配置";
}

export function resolveProviderAvailability(
  providerId: string | null,
  secretStatus: { providerId: string; configured: boolean } | null,
  settingsReady: boolean,
  statusError: boolean
): ProviderAvailability {
  if (!settingsReady || !providerId) return "checking";

  const activeId = providerId.trim().toLowerCase();
  if (activeId === "reflex-cloud") return "ready";
  if (statusError) return "unavailable";
  if (!secretStatus) return "checking";
  const statusId = secretStatus.providerId.trim().toLowerCase();
  if (!activeId || activeId !== statusId) return "checking";
  return secretStatus.configured ? "ready" : "missing";
}
