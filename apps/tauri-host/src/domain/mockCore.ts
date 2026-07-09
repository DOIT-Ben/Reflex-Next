import type { CoreEvent, OptimizeRequestDraft } from "./reflexSession";

export async function* streamMockOptimization(
  request: OptimizeRequestDraft
): AsyncGenerator<CoreEvent> {
  yield { type: "status", data: { message: "正在分析场景" } };
  await delay(180);

  yield {
    type: "scene",
    data: {
      scene: request.scene ?? inferDemoScene(request.text),
      confidence: request.scene ? 1 : 0.78,
      method: request.scene ? "manual" : "rule"
    }
  };
  await delay(180);

  yield { type: "status", data: { message: "正在连接模型服务" } };
  await delay(220);

  const text = buildDemoResult(request);
  for (const chunk of chunkText(text, 22)) {
    yield { type: "chunk", data: { text: chunk } };
    await delay(70);
  }

  yield {
    type: "done",
    data: {
      final_text: text,
      elapsed_seconds: 1.4
    }
  };
}

function buildDemoResult(request: OptimizeRequestDraft): string {
  const styleName = {
    concise: "简洁",
    balanced: "平衡",
    detailed: "详细",
    creative: "创意"
  }[request.style];

  if (request.mode === "prompt") {
    return `任务：优化以下内容的表达质量。\n\n背景：${request.text}\n\n要求：\n1. 保留原意，不添加未经确认的事实。\n2. 使用${styleName}风格输出。\n3. 给出可以直接复制使用的最终版本。`;
  }

  return `这是一个${styleName}版本的优化结果：\n\n${request.text}\n\n建议表达为：请先明确目标读者和使用场景，再用更直接的结构呈现重点、依据和下一步行动。`;
}

function inferDemoScene(text: string): string {
  if (/邮件|收件|发给|您好/.test(text)) return "email";
  if (/代码|函数|接口|bug|review/i.test(text)) return "code_review";
  if (/翻译|translate/i.test(text)) return "doc_translation";
  if (/报告|总结|汇报/.test(text)) return "report_writing";
  return "general";
}

function chunkText(text: string, size: number): string[] {
  const chunks: string[] = [];
  for (let index = 0; index < text.length; index += size) {
    chunks.push(text.slice(index, index + size));
  }
  return chunks;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
