import type { BatchFormat } from "./batchState";

export const MAX_BATCH_IMPORT_CHARS = 2_000_000;

export type BatchImportFile = {
  name: string;
  size: number;
  text: () => Promise<string>;
};

export type BatchImportFailure = "unsupported_file" | "file_too_large" | "empty_file" | "read_failed";

export type BatchImportResult =
  | { ok: true; format: BatchFormat; content: string }
  | { ok: false; reason: BatchImportFailure };

export function batchFormatFromFilename(name: string): BatchFormat | null {
  const normalized = typeof name === "string" ? name.trim().toLowerCase() : "";
  if (normalized.endsWith(".csv")) return "csv";
  if (normalized.endsWith(".txt")) return "txt";
  return null;
}

export async function readBatchImportFile(file: BatchImportFile): Promise<BatchImportResult> {
  const format = batchFormatFromFilename(file.name);
  if (!format) return { ok: false, reason: "unsupported_file" };
  if (!Number.isFinite(file.size) || file.size < 0 || file.size > MAX_BATCH_IMPORT_CHARS) {
    return { ok: false, reason: "file_too_large" };
  }
  if (file.size === 0) return { ok: false, reason: "empty_file" };
  try {
    const content = normalizeBatchContent(await file.text());
    if (!content) return { ok: false, reason: "empty_file" };
    if (content.length > MAX_BATCH_IMPORT_CHARS) return { ok: false, reason: "file_too_large" };
    return { ok: true, format, content };
  } catch {
    return { ok: false, reason: "read_failed" };
  }
}

export function batchTemplateContent(format: BatchFormat): string {
  return format === "csv"
    ? "prompt\nWrite a business email\nExplain machine learning in simple terms\n"
    : "Write a business email\nExplain machine learning in simple terms\n";
}

function normalizeBatchContent(value: unknown): string {
  return typeof value === "string"
    ? value.replace(/^\uFEFF/, "").replace(/\u0000/g, "").replace(/\r\n?/g, "\n").trim()
    : "";
}
