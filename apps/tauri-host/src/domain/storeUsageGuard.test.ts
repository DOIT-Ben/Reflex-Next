import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(__dirname, "..");

/**
 * 前端拆解重构后，各 flow 以 store 形式暴露状态。把 store 当作普通值使用
 * （例如 `{#if scenePromptOpen}`、`disabled={secretBusy}`、`enabled: draft`）
 * 不会抛类型错误（svelte-check 接受 {#if} 的任意 truthy 值），却会在运行时
 * 恒真 / 恒假 / 崩溃。本测试守护这一类缺陷：store 别名必须以 `$` 订阅后使用。
 */
function collectStoreAliases(source: string): Map<string, number> {
  const aliases = new Map<string, number>();
  const patterns = [
    /^\s*(?:const|let)\s+([A-Za-z][A-Za-z0-9]*)\s*=\s*[A-Za-z][A-Za-z0-9]*Flow\.[A-Za-z0-9]+;/gm,
    /^\s*(?:const|let)\s+([A-Za-z][A-Za-z0-9]*)\s*=\s*[A-Za-z][A-Za-z0-9]*\.state;/gm,
    /^\s*(?:const|let)\s+([A-Za-z][A-Za-z0-9]*)\s*=\s*writable\b/gm
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      aliases.set(match[1], (source.slice(0, match.index).match(/\n/g)?.length ?? 0) + 1);
    }
  }
  return aliases;
}

const DANGEROUS_CONTEXTS: Array<{ label: string; pattern: RegExp }> = [
  { label: "条件渲染", pattern: /(?:#if|:else if)\s+!?\s*([A-Za-z][A-Za-z0-9]*)\b/g },
  { label: "逻辑与/或", pattern: /(?<![\w$.[])([A-Za-z][A-Za-z0-9]*)\s*(?:&&|\|\|)/g },
  { label: "属性传值", pattern: /=\{\s*!?\s*([A-Za-z][A-Za-z0-9]*)\s*\}/g },
  { label: "对象属性", pattern: /[A-Za-z][A-Za-z0-9]*\s*:\s*([A-Za-z][A-Za-z0-9]*)\s*(?:[,}]|$)/g },
  { label: "展开", pattern: /\.\.\.\s*([A-Za-z][A-Za-z0-9]*)\s*(?:[,}]|$)/g }
];

function findBareStoreUsages(source: string): string[] {
  const aliases = collectStoreAliases(source);
  const violations: string[] = [];
  const lines = source.split("\n");
  lines.forEach((line, index) => {
    const lineNumber = index + 1;
    const trimmed = line.trim();
    if (
      trimmed.startsWith("//") ||
      trimmed.startsWith("*") ||
      trimmed.startsWith("import") ||
      /^\s*(?:const|let)\s/.test(line)
    ) {
      return;
    }
    for (const { label, pattern } of DANGEROUS_CONTEXTS) {
      for (const match of line.matchAll(pattern)) {
        const name = match[1];
        const aliasLine = aliases.get(name);
        if (aliasLine === undefined) continue;
        if (name.includes("$")) continue;
        const tail = line.slice(match.index + name.length);
        if (/^\.(set|update|subscribe)\b/.test(tail.replace(/^\s*/, ""))) continue;
        violations.push(`L${lineNumber} ${label}: ${name} -> ${trimmed.slice(0, 100)}`);
      }
    }
  });
  return violations;
}

describe("store usage guard", () => {
  const shells = ["App.svelte", "PanelApp.svelte"];

  it("detects bare store usage in each dangerous context", () => {
    const sample = [
      "const scenePromptOpen = optimizationFlow.scenePromptOpen;",
      "const feedbackBusy = feedbackFlow.submitBusy;",
      "  {#if scenePromptOpen}",
      "  {#if !$feedbackBusy && dirty}",
      "<X disabled={feedbackBusy} />",
      "  const next = {",
      "    enabled: feedbackBusy",
      "  };",
      "  const spread = {",
      "    ...feedbackBusy",
      "  };",
      "  scenePromptOpen.set(false);"
    ].join("\n");
    const violations = findBareStoreUsages(sample);
    expect(violations.some((item) => item.includes("条件渲染: scenePromptOpen"))).toBe(true);
    expect(violations.some((item) => item.includes("属性传值: feedbackBusy"))).toBe(true);
    expect(violations.some((item) => item.includes("对象属性: feedbackBusy"))).toBe(true);
    expect(violations.some((item) => item.includes("展开: feedbackBusy"))).toBe(true);
    expect(violations.some((item) => item.includes("scenePromptOpen.set"))).toBe(false);
    expect(violations.some((item) => item.includes("$feedbackBusy"))).toBe(false);
  });

  it("keeps every shell free of bare store usage", () => {
    for (const entry of shells) {
      const source = readFileSync(join(sourceRoot, entry), "utf8");
      expect(findBareStoreUsages(source), `${entry} 存在 store 裸用`).toEqual([]);
    }
  });
});
