import type { HostState, ResultStyle } from "./hostState";
import type { ProviderAvailability } from "./providerCatalog";
import { listSceneOptions, type OptimizeMode } from "./reflexSession";
import type { TranslationLanguage } from "./translationState";
import type { WorkbenchPhase } from "../components/workbench/types";

export type Translate = (source: string, values?: Record<string, string | number>) => string;

export const WORKBENCH_MODES: Array<{ id: OptimizeMode; label: string }> = [
  { id: "content", label: "内容优化" },
  { id: "prompt", label: "提示词生成" }
];

export const WORKBENCH_STYLES: Array<{ id: ResultStyle; label: string }> = [
  { id: "concise", label: "简洁" },
  { id: "balanced", label: "平衡" },
  { id: "detailed", label: "详细" },
  { id: "creative", label: "创意" }
];

export function listWorkbenchScenes() {
  return listSceneOptions();
}

export function isGeneratingPhase(phase: HostState["phase"]): boolean {
  return phase === "analyzing_scene" || phase === "connecting_provider" || phase === "streaming";
}

export function deriveWorkbenchPhase(
  phase: HostState["phase"],
  output: string
): WorkbenchPhase {
  if (isGeneratingPhase(phase)) return "running";
  if (phase === "completed") return "completed";
  if (phase === "error") return "error";
  if (phase === "cancelled") return "cancelled";
  return output ? "completed" : "empty";
}

export type BridgeState = "initializing" | "ready" | "unavailable";

export function deriveWorkbenchStatusMessage(
  input: { coreBridgeState: BridgeState; bridgeUnavailable: boolean; phase: HostState["phase"] },
  translate: Translate
): string {
  const { coreBridgeState, bridgeUnavailable, phase } = input;
  if (coreBridgeState === "initializing" && !isGeneratingPhase(phase)) {
    return translate("正在连接运行服务");
  }
  if (bridgeUnavailable && !isGeneratingPhase(phase)) {
    return translate("运行服务暂不可用");
  }
  if (phase === "analyzing_scene") return translate("正在分析场景");
  if (phase === "connecting_provider") return translate("正在连接模型服务");
  if (phase === "streaming") return translate("正在生成结果");
  if (phase === "completed") return translate("生成完成");
  if (phase === "error") return translate("生成失败");
  if (phase === "cancelled") return translate("已取消生成");
  return translate("准备就绪");
}

export function deriveStatusTone(input: {
  bridgeUnavailable: boolean;
  phase: HostState["phase"];
}): "idle" | "working" | "success" | "error" | "warning" {
  const { bridgeUnavailable, phase } = input;
  if (bridgeUnavailable && !isGeneratingPhase(phase)) return "warning";
  if (isGeneratingPhase(phase)) return "working";
  if (phase === "completed") return "success";
  if (phase === "error") return "error";
  if (phase === "cancelled") return "warning";
  return "idle";
}

export function providerAvailabilityLabel(
  translate: Translate,
  value: ProviderAvailability
): string {
  if (value === "ready") return translate("已配置");
  if (value === "missing") return translate("未配置");
  if (value === "unavailable") return translate("暂不可用");
  return translate("检查中");
}

export function modeLabel(translate: Translate, value: OptimizeMode): string {
  return translate(WORKBENCH_MODES.find((item) => item.id === value)?.label ?? "内容优化");
}

export function styleLabel(translate: Translate, value: ResultStyle): string {
  if (value === "precise") return translate("精准");
  return translate(WORKBENCH_STYLES.find((item) => item.id === value)?.label ?? "平衡");
}

export function sceneLabel(translate: Translate, value: string | null): string {
  return translate(listSceneOptions().find((item) => item.id === value)?.label ?? "自动识别");
}

export function translationLanguageLabel(
  translate: Translate,
  value: TranslationLanguage | null
): string {
  if (value === "zh") return translate("中文");
  if (value === "en") return "English";
  return translate("自动识别");
}

export function saveStatusLabel(translate: Translate, status: string): string {
  if (status === "saved") return translate("已保存到本机");
  if (status === "private") return translate("隐私模式");
  if (status === "saving") return translate("正在保存");
  return translate("未保存");
}

export function buildNavItems(translate: Translate) {
  return [
    { id: "workbench", label: translate("工作台"), symbol: "" },
    { id: "tools", label: translate("更多工具"), symbol: "" },
    { id: "history", label: translate("历史记录"), symbol: "", group: "utility" as const },
    { id: "settings", label: translate("设置"), symbol: "", shortcut: "Ctrl+,", group: "utility" as const }
  ];
}

export function buildConfigSummaryItems(
  translate: Translate,
  draft: HostState["requestDraft"]
) {
  return [
    { id: "mode", label: translate("模式"), value: modeLabel(translate, draft.mode) },
    { id: "style", label: translate("风格"), value: styleLabel(translate, draft.style) },
    { id: "scene", label: translate("场景"), value: sceneLabel(translate, draft.scene) }
  ];
}

export function buildResultMetaItems(
  translate: Translate,
  input: {
    result: HostState["currentResult"];
    draft: HostState["requestDraft"];
    providerLabel: string;
  }
) {
  const { result, draft, providerLabel } = input;
  return [
    { id: "mode", label: translate("模式"), value: modeLabel(translate, result?.mode ?? draft.mode) },
    { id: "style", label: translate("风格"), value: styleLabel(translate, result?.style ?? draft.style) },
    { id: "provider", label: "Provider", value: providerLabel }
  ];
}
