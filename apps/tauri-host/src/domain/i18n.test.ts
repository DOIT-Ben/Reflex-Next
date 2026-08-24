import { describe, expect, it } from "vitest";
import { t, translate } from "./i18n";
import { listSceneCategories, listSceneOptions } from "./reflexSession";

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

  it("localizes every scene category and hint used by searchable scene pickers", () => {
    for (const category of listSceneCategories()) {
      expect(translate("en-US", category.label)).not.toBe(category.label);
    }
    for (const scene of listSceneOptions()) {
      expect(translate("en-US", scene.label)).not.toBe(scene.label);
      expect(translate("en-US", scene.hint)).not.toBe(scene.hint);
    }
  });

  it("localizes the random feedback and scene-selection workflows", () => {
    for (const source of [
      "选择本次场景",
      "搜索场景",
      "场景分类",
      "由本地场景路由选择",
      "没有匹配的场景",
      "已显示 {count} 个场景",
      "当前场景：{scene}",
      "开始生成",
      "主动反馈询问",
      "在若干次成功生成后偶尔询问结果是否有帮助",
      "这次结果有帮助吗？",
      "你的选择会帮助我们改进场景和模型效果，不会附带输入或结果。",
      "有帮助",
      "需要改进",
      "稍后再问",
      "不再主动询问",
      "反馈类型",
      "具体问题",
      "应用截图预览",
      "发送反馈",
      "（实验）",
      "此 Provider 仍在实验支持阶段，协议或模型可用性可能变化。"
    ]) {
      expect(translate("en-US", source)).not.toBe(source);
    }
  });

  it("localizes the core workbench controls used by the main panes", () => {
    const expected: Record<string, string> = {
      "读取剪贴板": "Read clipboard",
      "清空": "Clear",
      "结果": "Result",
      "结果操作": "Result actions",
      "翻译": "Translate",
      "预览": "Preview",
      "对比": "Compare",
      "还没有结果": "No result yet",
      "输入文本并开始优化，结果会在这里流式显示。": "Enter text and start optimizing; the result will stream here.",
      "正在与模型服务通信，请稍候。": "Communicating with the model service. Please wait.",
      "生成失败": "Generation failed",
      "取消生成": "Cancel generation",
      "重新生成": "Regenerate",
      "复制结果": "Copy result",
      "调整方案": "Adjust",
      "本次生成配置": "Generation settings"
    };
    for (const [source, value] of Object.entries(expected)) {
      expect(translate("en-US", source)).toBe(value);
    }
  });
});
