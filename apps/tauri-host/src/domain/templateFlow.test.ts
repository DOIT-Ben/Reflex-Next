import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createTemplateFlow } from "./templateFlow";
import type { PromptTemplate, TemplateDraft } from "./templateLibrary";

function createTemplate(overrides: Partial<PromptTemplate> = {}): PromptTemplate {
  return {
    id: "tpl-1",
    name: "周报",
    category: "办公",
    content: "本周完成 {{task}}",
    description: "",
    tags: [],
    created_at: "2026-09-12",
    ...overrides
  };
}

type FlowDeps = Parameters<typeof createTemplateFlow>[0];

function createDeps(overrides: Partial<FlowDeps> = {}) {
  const deps: FlowDeps = {
    persistConfigPatch: vi.fn(async (build: (latest: { custom_templates: unknown[] }) => unknown) =>
      build({ custom_templates: [] })
    ) as unknown as FlowDeps["persistConfigPatch"],
    hasPersistedConfig: vi.fn(() => true),
    updateHostState: vi.fn(),
    closeManager: vi.fn(),
    showToast: vi.fn(),
    ...overrides
  };
  return deps;
}

describe("createTemplateFlow", () => {
  it("hydrates templates and derives categories and visibility", () => {
    const flow = createTemplateFlow(
      createDeps()
    );
    flow.hydrate([createTemplate(), createTemplate({ id: "tpl-2", name: "随笔", category: "写作" })]);

    expect(get(flow.categories)).toEqual(["办公", "写作"]);
    expect(get(flow.visible)).toHaveLength(2);

    flow.query.set("周报");
    expect(get(flow.visible)).toHaveLength(1);
  });

  it("selects a template and fills variable values", () => {
    const flow = createTemplateFlow(createDeps());

    flow.select(createTemplate({ content: "本周完成 {{task}}" }));

    expect(get(flow.selectedId)).toBe("tpl-1");
    expect(get(flow.values)).toEqual({ task: "" });
    expect(get(flow.notice)).toBeNull();
  });

  it("rejects saving an incomplete draft without touching persistence", async () => {
    const deps = createDeps();
    const flow = createTemplateFlow(deps);

    await flow.save();

    expect(deps.persistConfigPatch).not.toHaveBeenCalled();
    expect(get(flow.notice)).toBe("请填写名称、分类和模板内容。");
  });

  it("saves a valid draft through the config patch and reselects it", async () => {
    const persistConfigPatch = vi.fn(
      async (build: (latest: { custom_templates: unknown[] }) => unknown) =>
        build({
          custom_templates: [
            {
              id: "tpl-9",
              name: "日报",
              category: "办公",
              content: "今日 {{task}}",
              description: "",
              tags: [],
              created_at: ""
            }
          ]
        })
    ) as unknown as FlowDeps["persistConfigPatch"];
    const flow = createTemplateFlow(createDeps({ persistConfigPatch }));
    const draft: TemplateDraft = {
      name: "日报",
      category: "办公",
      content: "今日 {{task}}",
      description: "",
      tags: []
    };
    flow.draft.set(draft);

    await flow.save();

    expect(get(flow.notice)).toBe("模板已保存。");
    expect(get(flow.customTemplates)).toHaveLength(1);
    expect(get(flow.busy)).toBe(false);
  });

  it("applies a rendered template into the host input and closes", () => {
    const deps = createDeps();
    const flow = createTemplateFlow(deps);
    flow.draft.set({ name: "n", category: "c", content: "hello {{who}}", description: "", tags: [] });
    flow.values.set({ who: "world" });

    flow.apply();

    expect(deps.updateHostState).toHaveBeenCalledTimes(1);
    expect(deps.closeManager).toHaveBeenCalledTimes(1);
    expect(deps.showToast).toHaveBeenCalledWith("模板已应用到输入区");
  });

  it("blocks apply when variables are missing", () => {
    const deps = createDeps();
    const flow = createTemplateFlow(deps);
    flow.draft.set({ name: "n", category: "c", content: "hello {{who}}", description: "", tags: [] });

    flow.apply();

    expect(deps.updateHostState).not.toHaveBeenCalled();
    expect(get(flow.notice)).toBe("请填写全部变量后再应用。");
  });
});
