import { get, derived, writable, type Readable, type Writable } from "svelte/store";
import type { AppConfig } from "./settingsApi";
import type { HostState } from "./hostState";
import { updateInput } from "./hostState";
import {
  createTemplateDraft,
  filterTemplates,
  readCustomTemplates,
  removeCustomTemplate,
  renderTemplate,
  saveCustomTemplate,
  templateVariables,
  type PromptTemplate,
  type TemplateDraft
} from "./templateLibrary";

export type TemplateFlowDeps = {
  persistConfigPatch: (build: (latest: AppConfig) => AppConfig) => Promise<AppConfig>;
  hasPersistedConfig: () => boolean;
  updateHostState: (updater: (state: HostState) => HostState) => void;
  closeManager: () => void;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type TemplateFlow = {
  customTemplates: Writable<PromptTemplate[]>;
  draft: Writable<TemplateDraft>;
  selectedId: Writable<string | null>;
  query: Writable<string>;
  category: Writable<string | null>;
  values: Writable<Record<string, string>>;
  notice: Writable<string | null>;
  busy: Writable<boolean>;
  categories: Readable<string[]>;
  visible: Readable<PromptTemplate[]>;
  hydrate: (templates: PromptTemplate[]) => void;
  select: (template: PromptTemplate) => void;
  newDraft: () => void;
  save: () => Promise<void>;
  beginDelete: () => boolean;
  performDelete: () => Promise<void>;
  apply: () => void;
};

const SAVE_FAILURE_MESSAGE = "模板暂时无法保存，请重试。";
const DELETE_FAILURE_MESSAGE = "模板暂时无法删除，请重试。";

export function createTemplateFlow(deps: TemplateFlowDeps): TemplateFlow {
  const customTemplates = writable<PromptTemplate[]>([]);
  const draft = writable<TemplateDraft>(createTemplateDraft());
  const selectedId = writable<string | null>(null);
  const query = writable("");
  const category = writable<string | null>(null);
  const values = writable<Record<string, string>>({});
  const notice = writable<string | null>(null);
  const busy = writable(false);

  const categories = derived(customTemplates, (templates) =>
    [...new Set(templates.map((template) => template.category))].sort((left, right) =>
      left.localeCompare(right, "zh-CN")
    )
  );
  const visible = derived(
    [customTemplates, query, category],
    ([templates, currentQuery, currentCategory]) =>
      filterTemplates(templates, currentQuery, currentCategory)
  );

  function select(template: PromptTemplate) {
    selectedId.set(template.id);
    draft.set(createTemplateDraft(template));
    values.set(Object.fromEntries(templateVariables(template.content).map((name) => [name, ""])));
    notice.set(null);
  }

  function newDraft() {
    selectedId.set(null);
    draft.set(createTemplateDraft());
    values.set({});
    notice.set(null);
  }

  function hydrate(templates: PromptTemplate[]) {
    customTemplates.set(templates);
  }

  async function save() {
    if (get(busy) || !deps.hasPersistedConfig()) {
      notice.set(SAVE_FAILURE_MESSAGE);
      return;
    }
    const next = saveCustomTemplate(get(customTemplates), get(draft), get(selectedId) ?? undefined);
    if (!next) {
      notice.set("请填写名称、分类和模板内容。");
      return;
    }
    busy.set(true);
    try {
      const saved = await deps.persistConfigPatch((latest) => ({
        ...latest,
        custom_templates: next
      }));
      const templates = readCustomTemplates(saved.custom_templates);
      customTemplates.set(templates);
      const selectedTemplate = templates.find(
        (template) => template.id === (get(selectedId) ?? next.at(-1)?.id)
      );
      if (selectedTemplate) select(selectedTemplate);
      notice.set("模板已保存。");
    } catch {
      notice.set(SAVE_FAILURE_MESSAGE);
    } finally {
      busy.set(false);
    }
  }

  function beginDelete(): boolean {
    return Boolean(get(selectedId)) && !get(busy) && deps.hasPersistedConfig();
  }

  async function performDelete() {
    const id = get(selectedId);
    if (!id || get(busy) || !deps.hasPersistedConfig()) return;
    busy.set(true);
    try {
      const next = removeCustomTemplate(get(customTemplates), id);
      const saved = await deps.persistConfigPatch((latest) => ({
        ...latest,
        custom_templates: next
      }));
      customTemplates.set(readCustomTemplates(saved.custom_templates));
      selectedId.set(null);
      draft.set(createTemplateDraft());
      values.set({});
      notice.set("模板已删除。");
    } catch {
      notice.set(DELETE_FAILURE_MESSAGE);
    } finally {
      busy.set(false);
    }
  }

  function apply() {
    const rendered = renderTemplate(get(draft).content, get(values));
    if (!rendered) {
      notice.set("请填写全部变量后再应用。");
      return;
    }
    deps.updateHostState((state) => updateInput(state, rendered));
    deps.closeManager();
    deps.showToast("模板已应用到输入区");
  }

  return {
    customTemplates,
    draft,
    selectedId,
    query,
    category,
    values,
    notice,
    busy,
    categories,
    visible,
    hydrate,
    select,
    newDraft,
    save,
    beginDelete,
    performDelete,
    apply
  };
}
