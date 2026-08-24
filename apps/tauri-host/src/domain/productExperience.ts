import type { RequestSettings } from "./hostState";

export type QuickActionId = "polish" | "summarize" | "meeting_notes";

export type QuickAction = {
  id: QuickActionId;
  label: string;
  hint: string;
};

export const quickActions: readonly QuickAction[] = [
  { id: "polish", label: "优化表达", hint: "让文字更清楚、自然" },
  { id: "summarize", label: "压缩成摘要", hint: "保留重点，减少冗余" },
  { id: "meeting_notes", label: "整理会议纪要", hint: "提炼决策与行动项" }
];

export function applyQuickAction(request: RequestSettings, actionId: string): RequestSettings {
  if (actionId === "polish") {
    return { ...request, mode: "content", style: "balanced", scene: null, scene_policy: "auto" };
  }
  if (actionId === "summarize") {
    return { ...request, mode: "content", style: "concise", scene: null, scene_policy: "auto" };
  }
  if (actionId === "meeting_notes") {
    return {
      ...request,
      mode: "content",
      style: "balanced",
      scene: "meeting_summary",
      scene_policy: "manual"
    };
  }
  return request;
}

export function primaryNavigationIds(): readonly ["workbench", "tools", "history", "settings"] {
  return ["workbench", "tools", "history", "settings"];
}

export function preferredByokProvider(
  currentProviderId: string | null | undefined,
  providerIds: readonly string[]
): string | null {
  const current = currentProviderId?.trim().toLowerCase();
  if (current && current !== "reflex-cloud" && providerIds.includes(current)) return current;
  return providerIds.find((providerId) => providerId.trim().toLowerCase() !== "reflex-cloud") ?? null;
}

export type GenerationTrustInput = {
  route: "cloud" | "byok";
  providerLabel: string;
  historyEnabled: boolean;
  privacyMode: boolean;
  quota: { requestsUsed: number; requestsLimit: number } | null;
};

export function generationTrustSummary(
  input: GenerationTrustInput,
  language: "zh-CN" | "en-US" = "zh-CN"
): string {
  const history = historySummary(input.historyEnabled, input.privacyMode, language);
  const isEnglish = language === "en-US";
  if (input.route === "cloud") {
    const quota = input.quota;
    const remaining = quota === null ? null : Math.max(0, quota.requestsLimit - quota.requestsUsed);
    const quotaSummary = remaining === null
      ? isEnglish ? "free quota status is unavailable" : "免费额度状态暂不可用"
      : isEnglish ? `${remaining} free requests remaining` : `剩余 ${remaining} 次免费请求`;
    return isEnglish
      ? `This request is processed through ${input.providerLabel} with ${quotaSummary}; ${history}`
      : `本次将通过 ${input.providerLabel} 处理，${quotaSummary}；${history}`;
  }
  return isEnglish
    ? `This text is sent to ${input.providerLabel}, not Reflex Cloud; ${history}`
    : `本次文本将发送至 ${input.providerLabel}，不上传至 Reflex Cloud；${history}`;
}

function historySummary(
  historyEnabled: boolean,
  privacyMode: boolean,
  language: "zh-CN" | "en-US"
): string {
  if (privacyMode || !historyEnabled) return language === "en-US" ? "history is not saved." : "不保存历史。";
  return language === "en-US"
    ? "results are saved to encrypted local history."
    : "结果会保存到本地加密历史。";
}
