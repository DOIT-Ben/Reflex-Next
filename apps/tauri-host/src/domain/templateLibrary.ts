export type PromptTemplate = {
  id: string;
  name: string;
  category: string;
  content: string;
  description: string;
  tags: string[];
  created_at: string;
};

export type TemplateDraft = Omit<PromptTemplate, "id" | "created_at">;

const MAX_TEMPLATES = 100;
const MAX_TEXT_LENGTH = 20_000;
const MAX_FIELD_LENGTH = 120;

export function readCustomTemplates(value: unknown): PromptTemplate[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const templates: PromptTemplate[] = [];
  for (const item of value) {
    const template = normalizeTemplate(item);
    if (!template || seen.has(template.id) || templates.length >= MAX_TEMPLATES) continue;
    seen.add(template.id);
    templates.push(template);
  }
  return templates.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
}

export function createTemplateDraft(template?: PromptTemplate): TemplateDraft {
  return template
    ? {
        name: template.name,
        category: template.category,
        content: template.content,
        description: template.description,
        tags: [...template.tags]
      }
    : { name: "", category: "通用", content: "", description: "", tags: [] };
}

export function saveCustomTemplate(
  templates: PromptTemplate[],
  draft: TemplateDraft,
  existingId?: string,
  now = new Date().toISOString()
): PromptTemplate[] | null {
  const normalized = normalizeDraft(draft);
  if (!normalized) return null;
  const existing = existingId ? templates.find((template) => template.id === existingId) : undefined;
  if (!existing && templates.length >= MAX_TEMPLATES) return null;
  const template: PromptTemplate = {
    id: existing?.id ?? createTemplateId(now),
    created_at: existing?.created_at ?? now,
    ...normalized
  };
  const next = existing
    ? templates.map((item) => (item.id === existing.id ? template : item))
    : [...templates, template];
  return readCustomTemplates(next);
}

export function removeCustomTemplate(templates: PromptTemplate[], id: string): PromptTemplate[] {
  return templates.filter((template) => template.id !== id);
}

export function filterTemplates(
  templates: PromptTemplate[],
  query: string,
  category: string | null
): PromptTemplate[] {
  const needle = query.trim().toLocaleLowerCase();
  return templates.filter((template) => {
    const matchCategory = !category || template.category === category;
    const searchable = [template.name, template.category, template.description, ...template.tags]
      .join("\n")
      .toLocaleLowerCase();
    return matchCategory && (!needle || searchable.includes(needle));
  });
}

export function templateVariables(content: string): string[] {
  const names = new Set<string>();
  for (const match of content.matchAll(/\{([^{}]{1,64})\}/g)) {
    const name = match[1].trim();
    if (name && /^[\p{L}\p{N}_ -]+$/u.test(name)) names.add(name);
  }
  return [...names];
}

export function renderTemplate(content: string, values: Record<string, string>): string | null {
  const names = templateVariables(content);
  if (names.some((name) => !values[name]?.trim())) return null;
  return content.replace(/\{([^{}]{1,64})\}/g, (whole, rawName: string) => {
    const name = rawName.trim();
    return names.includes(name) ? values[name].trim() : whole;
  });
}

function normalizeTemplate(value: unknown): PromptTemplate | null {
  if (!isRecord(value) || typeof value.id !== "string" || !/^[a-z][a-z0-9_-]{7,63}$/.test(value.id)) return null;
  const draft = normalizeDraft(value);
  if (!draft || typeof value.created_at !== "string" || !Number.isFinite(Date.parse(value.created_at))) return null;
  return { id: value.id, created_at: value.created_at, ...draft };
}

function normalizeDraft(value: unknown): TemplateDraft | null {
  if (!isRecord(value)) return null;
  const name = trimField(value.name);
  const category = trimField(value.category);
  const content = typeof value.content === "string" ? value.content.replace(/\u0000/g, "").trim() : "";
  const description = typeof value.description === "string" ? value.description.replace(/\u0000/g, "").trim().slice(0, 500) : "";
  if (!name || !category || !content || content.length > MAX_TEXT_LENGTH) return null;
  const tags = Array.isArray(value.tags)
    ? [...new Set(value.tags.map(trimField).filter((tag): tag is string => Boolean(tag)))].slice(0, 12)
    : [];
  return { name, category, content, description, tags };
}

function trimField(value: unknown): string {
  return typeof value === "string" ? value.replace(/\u0000/g, "").trim().slice(0, MAX_FIELD_LENGTH) : "";
}

function createTemplateId(now: string): string {
  const suffix = globalThis.crypto?.randomUUID?.().replaceAll("-", "").slice(0, 12) ?? Math.random().toString(36).slice(2, 14);
  const time = Math.max(0, Date.parse(now)).toString(36).slice(-8);
  return `custom_${time}${suffix}`.slice(0, 64);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
