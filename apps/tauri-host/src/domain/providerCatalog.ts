export type ProviderOption = { id: string; label: string; models: Array<{ id: string; label: string }> };

export type ProviderAvailability = "checking" | "ready" | "missing" | "unavailable";

export const providerCatalog: ProviderOption[] = [
  { id: "reflex-cloud", label: "Reflex Cloud", models: [{ id: "MiniMax-M2.7-highspeed", label: "云端 M2.7 高速版" }] },
  { id: "minimax", label: "MiniMax", models: [{ id: "MiniMax-M2.7-highspeed", label: "M2.7 高速版" }] },
  { id: "deepseek", label: "DeepSeek", models: [{ id: "deepseek-chat", label: "DeepSeek Chat" }, { id: "deepseek-reasoner", label: "DeepSeek Reasoner" }] },
  { id: "qwen", label: "通义千问", models: [{ id: "qwen-turbo", label: "Qwen Turbo" }, { id: "qwen-plus", label: "Qwen Plus" }, { id: "qwen-max", label: "Qwen Max" }] },
  { id: "zhipu", label: "智谱 GLM", models: [{ id: "glm-4.5-air", label: "GLM-4.5 Air" }, { id: "glm-4.7", label: "GLM-4.7" }] },
  { id: "siliconflow", label: "SiliconFlow", models: [{ id: "deepseek-ai/DeepSeek-V3", label: "DeepSeek V3" }, { id: "Qwen/Qwen2.5-72B-Instruct", label: "Qwen 2.5 72B" }] }
];

export function providerModels(providerId: string | null): ProviderOption["models"] {
  return providerCatalog.find((provider) => provider.id === providerId)?.models ?? providerCatalog[0].models;
}

export function providerName(providerId: string | null): string {
  return providerCatalog.find((provider) => provider.id === providerId)?.label ?? providerId ?? "未配置";
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
