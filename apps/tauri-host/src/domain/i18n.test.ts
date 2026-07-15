import { describe, expect, it } from "vitest";
import { t, translate } from "./i18n";

describe("ui messages", () => {
  it("keeps every primary user-flow label available in both languages", () => {
    expect(t("zh-CN", "optimize")).toBe("优化文本");
    expect(t("en-US", "optimize")).toBe("Optimize text");
    expect(t("en-US", "cancel")).toBe("Cancel");
    expect(t("en-US", "cancelGeneration")).toBe("Cancel generation");
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
    expect(translate("en-US", "导入文件")).toBe("Import file");
    expect(translate("en-US", "已从 {name} 导入 {count} 条提示词", { name: "prompts.csv", count: 2 }))
      .toBe("Imported 2 prompts from prompts.csv");
    expect(translate("en-US", "请先在隐私设置中开启对应的数据改进授权。"))
      .toBe("Enable the corresponding data-improvement consent in Privacy settings first.");
    expect(translate("en-US", "今日云端请求额度已用完，请明天再试或切换到自备 Provider。"))
      .toBe("Today's cloud request budget is exhausted. Try again tomorrow or switch to your own provider.");
    expect(translate("en-US", "模型服务网络连接失败，请重试。"))
      .toBe("The model service could not be reached. Try again.");
  });
});
