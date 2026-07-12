export type UiLanguage = "zh-CN" | "en-US";

const messages = {
  "zh-CN": {
    input: "输入内容", paste: "粘贴文本、需求或提示词…", readClipboard: "读取剪贴板", template: "模板", batch: "批量处理", adjust: "调整", optimize: "优化文本", generating: "正在生成", completed: "优化完成", failed: "生成失败", copy: "复制结果", retry: "重试", settings: "设置", current: "当前方案", analyzing: "正在分析场景", connecting: "正在连接模型", streaming: "正在生成内容", cancel: "取消生成", noProvider: "模型服务暂时不可用", openSettings: "打开设置", copied: "已复制到剪贴板"
  },
  "en-US": {
    input: "Input", paste: "Paste text, requirements, or a prompt...", readClipboard: "Read clipboard", template: "Templates", batch: "Batch", adjust: "Adjust", optimize: "Optimize text", generating: "Generating", completed: "Complete", failed: "Generation failed", copy: "Copy result", retry: "Retry", settings: "Settings", current: "Current setup", analyzing: "Analyzing scene", connecting: "Connecting model", streaming: "Generating content", cancel: "Cancel", noProvider: "The model service is unavailable", openSettings: "Open settings", copied: "Copied to clipboard"
  }
} as const;

export type MessageKey = keyof (typeof messages)["zh-CN"];

export function t(language: UiLanguage, key: MessageKey): string {
  return messages[language][key];
}
