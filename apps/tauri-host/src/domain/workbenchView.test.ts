import { describe, expect, it } from "vitest";
import {
  buildConfigSummaryItems,
  buildNavItems,
  buildResultMetaItems,
  deriveStatusTone,
  deriveWorkbenchPhase,
  deriveWorkbenchStatusMessage,
  isGeneratingPhase,
  modeLabel,
  providerAvailabilityLabel,
  saveStatusLabel,
  sceneLabel,
  styleLabel,
  translationLanguageLabel,
  WORKBENCH_MODES,
  WORKBENCH_STYLES
} from "./workbenchView";

const identity = (source: string) => source;

describe("phase derivation", () => {
  it("maps generating phases to running", () => {
    expect(isGeneratingPhase("streaming")).toBe(true);
    expect(isGeneratingPhase("completed")).toBe(false);
    expect(deriveWorkbenchPhase("connecting_provider", "")).toBe("running");
  });

  it("keeps a completed result visible after cancel when output exists", () => {
    expect(deriveWorkbenchPhase("cancelled", "已有输出")).toBe("cancelled");
    expect(deriveWorkbenchPhase("empty", "遗留输出")).toBe("completed");
    expect(deriveWorkbenchPhase("empty", "")).toBe("empty");
  });

  it("derives status messages with bridge priority", () => {
    expect(
      deriveWorkbenchStatusMessage({ coreBridgeState: "initializing", bridgeUnavailable: false, phase: "empty" }, identity)
    ).toBe("正在连接运行服务");
    expect(
      deriveWorkbenchStatusMessage({ coreBridgeState: "unavailable", bridgeUnavailable: true, phase: "empty" }, identity)
    ).toBe("运行服务暂不可用");
    expect(
      deriveWorkbenchStatusMessage({ coreBridgeState: "ready", bridgeUnavailable: false, phase: "streaming" }, identity)
    ).toBe("正在生成结果");
    expect(
      deriveWorkbenchStatusMessage({ coreBridgeState: "ready", bridgeUnavailable: false, phase: "empty" }, identity)
    ).toBe("准备就绪");
  });

  it("derives status tones", () => {
    expect(deriveStatusTone({ bridgeUnavailable: true, phase: "empty" })).toBe("warning");
    expect(deriveStatusTone({ bridgeUnavailable: false, phase: "analyzing_scene" })).toBe("working");
    expect(deriveStatusTone({ bridgeUnavailable: false, phase: "completed" })).toBe("success");
    expect(deriveStatusTone({ bridgeUnavailable: false, phase: "error" })).toBe("error");
    expect(deriveStatusTone({ bridgeUnavailable: false, phase: "cancelled" })).toBe("warning");
    expect(deriveStatusTone({ bridgeUnavailable: false, phase: "empty" })).toBe("idle");
  });
});

describe("labels", () => {
  it("labels availability states", () => {
    expect(providerAvailabilityLabel(identity, "ready")).toBe("已配置");
    expect(providerAvailabilityLabel(identity, "missing")).toBe("未配置");
    expect(providerAvailabilityLabel(identity, "unavailable")).toBe("暂不可用");
    expect(providerAvailabilityLabel(identity, "checking")).toBe("检查中");
  });

  it("labels modes, styles, scenes and languages", () => {
    expect(modeLabel(identity, "prompt")).toBe("提示词生成");
    expect(styleLabel(identity, "precise")).toBe("精准");
    expect(styleLabel(identity, "balanced")).toBe("平衡");
    expect(sceneLabel(identity, null)).toBe("自动识别");
    expect(translationLanguageLabel(identity, "zh")).toBe("中文");
    expect(translationLanguageLabel(identity, "en")).toBe("English");
    expect(translationLanguageLabel(identity, null)).toBe("自动识别");
    expect(WORKBENCH_MODES).toHaveLength(2);
    expect(WORKBENCH_STYLES).toHaveLength(4);
  });

  it("labels save statuses", () => {
    expect(saveStatusLabel(identity, "saved")).toBe("已保存到本机");
    expect(saveStatusLabel(identity, "private")).toBe("隐私模式");
    expect(saveStatusLabel(identity, "saving")).toBe("正在保存");
    expect(saveStatusLabel(identity, "unsaved")).toBe("未保存");
  });
});

describe("view builders", () => {
  it("builds nav items with the settings shortcut", () => {
    const items = buildNavItems(identity);
    expect(items.map((item) => item.id)).toEqual(["workbench", "tools", "history", "settings"]);
  });

  it("builds config summary from the request draft", () => {
    const items = buildConfigSummaryItems(identity, {
      mode: "content",
      style: "balanced",
      scene: null
    } as never);
    expect(items.map((item) => item.id)).toEqual(["mode", "style", "scene"]);
  });

  it("builds result meta preferring the saved result over the draft", () => {
    const items = buildResultMetaItems(identity, {
      result: { mode: "prompt", style: "creative", provider: "minimax" } as never,
      draft: { mode: "content", style: "balanced" } as never,
      providerLabel: "MiniMax"
    });
    expect(items.map((item) => item.value)).toEqual(["提示词生成", "创意", "MiniMax"]);
  });
});
