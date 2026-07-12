import { describe, expect, it } from "vitest";
import { t, translate } from "./i18n";

describe("ui messages", () => {
  it("keeps every primary user-flow label available in both languages", () => {
    expect(t("zh-CN", "optimize")).toBe("优化文本");
    expect(t("en-US", "optimize")).toBe("Optimize text");
    expect(t("en-US", "cancel")).toBe("Cancel");
  });

  it("localizes dynamic and secondary feature text without leaking Chinese in English mode", () => {
    expect(translate("en-US", "正在处理 {processed}/{total}，已完成 {completed} 条", {
      processed: 2,
      total: 4,
      completed: 1
    })).toBe("Processing 2/4, 1 complete");
    expect(translate("en-US", "历史记录")).toBe("History");
    expect(translate("en-US", "对比原文")).toBe("Compare original");
    expect(translate("en-US", "当前结果没有可用原文")).toBe("This result has no original text available");
  });
});
