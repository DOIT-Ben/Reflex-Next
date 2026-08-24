import { describe, expect, it } from "vitest";

import {
  applyQuickAction,
  generationTrustSummary,
  preferredByokProvider,
  primaryNavigationIds,
  quickActions
} from "./productExperience";

const request = {
  mode: "prompt" as const,
  style: "creative" as const,
  scene: "article_writing",
  scene_policy: "manual" as const,
  provider: "minimax",
  model: "MiniMax-M2.7-highspeed"
};

describe("product experience shortcuts", () => {
  it("maps the three promoted actions to the existing request contract", () => {
    expect(quickActions.map((item) => item.id)).toEqual([
      "polish",
      "summarize",
      "meeting_notes"
    ]);
    expect(applyQuickAction(request, "polish")).toMatchObject({
      mode: "content",
      style: "balanced",
      scene: null,
      scene_policy: "auto"
    });
    expect(applyQuickAction(request, "summarize")).toMatchObject({
      mode: "content",
      style: "concise",
      scene: null,
      scene_policy: "auto"
    });
    expect(applyQuickAction(request, "meeting_notes")).toMatchObject({
      mode: "content",
      style: "balanced",
      scene: "meeting_summary",
      scene_policy: "manual"
    });
  });

  it("keeps unknown quick actions from mutating the active request", () => {
    expect(applyQuickAction(request, "unknown")).toEqual(request);
  });

  it("keeps only the focused navigation entries on the primary rail", () => {
    expect(primaryNavigationIds()).toEqual(["workbench", "tools", "history", "settings"]);
  });

  it("never sends the self-managed-key route back to Reflex Cloud settings", () => {
    expect(preferredByokProvider("reflex-cloud", ["reflex-cloud", "minimax", "qwen"])).toBe("minimax");
    expect(preferredByokProvider("qwen", ["reflex-cloud", "minimax", "qwen"])).toBe("qwen");
  });
});

describe("generation trust summary", () => {
  it("explains the Cloud route and remaining request quota without private fields", () => {
    const summary = generationTrustSummary({
      route: "cloud",
      providerLabel: "Reflex Cloud",
      historyEnabled: false,
      privacyMode: false,
      quota: { requestsUsed: 2, requestsLimit: 10 }
    });

    expect(summary).toContain("Reflex Cloud");
    expect(summary).toContain("8 次");
    expect(summary).toContain("不保存历史");
    expect(summary).not.toMatch(/key|token|secret|https?:\/\//i);
  });

  it("explains the bring-your-own-provider route and local encrypted history", () => {
    expect(
      generationTrustSummary({
        route: "byok",
        providerLabel: "MiniMax",
        historyEnabled: true,
        privacyMode: false,
        quota: null
      })
    ).toBe("本次文本将发送至 MiniMax，不上传至 Reflex Cloud；结果会保存到本地加密历史。");
  });

  it("keeps the same privacy meaning for the English interface", () => {
    expect(
      generationTrustSummary(
        {
          route: "cloud",
          providerLabel: "Reflex Cloud",
          historyEnabled: true,
          privacyMode: false,
          quota: { requestsUsed: 2, requestsLimit: 10 }
        },
        "en-US"
      )
    ).toBe("This request is processed through Reflex Cloud with 8 free requests remaining; results are saved to encrypted local history.");
  });
});
