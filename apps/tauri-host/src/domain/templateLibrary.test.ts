import { describe, expect, it } from "vitest";

import {
  createTemplateDraft,
  filterTemplates,
  readCustomTemplates,
  renderTemplate,
  saveCustomTemplate,
  templateVariables
} from "./templateLibrary";

describe("template library", () => {
  const source = {
    id: "custom_abcdefgh",
    name: "邮件草稿",
    category: "办公",
    content: "请为{收件人}起草一封{类型}邮件。",
    description: "快速起草",
    tags: ["邮件", "办公"],
    created_at: "2026-07-12T00:00:00.000Z"
  };

  it("loads only bounded, well-formed custom templates", () => {
    expect(readCustomTemplates([source, { ...source }, { ...source, id: "unsafe" }])).toEqual([source]);
  });

  it("creates, edits, searches, and keeps user content local", () => {
    const created = saveCustomTemplate([], createTemplateDraft(source), undefined, source.created_at)!;
    const edited = saveCustomTemplate(created, { ...createTemplateDraft(source), name: "商务邮件" }, created[0].id, source.created_at)!;
    expect(edited).toHaveLength(1);
    expect(filterTemplates(edited, "商务", "办公")[0].name).toBe("商务邮件");
    expect(JSON.stringify(edited)).not.toContain("secret");
  });

  it("renders required variables and rejects missing values", () => {
    expect(templateVariables(source.content)).toEqual(["收件人", "类型"]);
    expect(renderTemplate(source.content, { 收件人: "陈经理", 类型: "商务" })).toBe("请为陈经理起草一封商务邮件。");
    expect(renderTemplate(source.content, { 收件人: "陈经理" })).toBeNull();
  });
});
