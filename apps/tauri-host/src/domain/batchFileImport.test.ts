import { describe, expect, it } from "vitest";

import {
  batchFormatFromFilename,
  batchTemplateContent,
  MAX_BATCH_IMPORT_CHARS,
  readBatchImportFile
} from "./batchFileImport";

describe("batch file import", () => {
  it("accepts CSV and TXT files with normalized content", async () => {
    expect(batchFormatFromFilename("PROMPTS.CSV")).toBe("csv");
    expect(batchFormatFromFilename("prompts.txt")).toBe("txt");
    expect(batchFormatFromFilename("prompts.md")).toBeNull();

    await expect(readBatchImportFile({
      name: "prompts.csv",
      size: 32,
      text: async () => "\uFEFFprompt\r\nWrite an email\u0000\r\n"
    })).resolves.toEqual({ ok: true, format: "csv", content: "prompt\nWrite an email" });
  });

  it("rejects unsupported, empty, oversized, and unreadable files", async () => {
    await expect(readBatchImportFile({ name: "prompts.md", size: 3, text: async () => "abc" }))
      .resolves.toEqual({ ok: false, reason: "unsupported_file" });
    await expect(readBatchImportFile({ name: "prompts.txt", size: 0, text: async () => "" }))
      .resolves.toEqual({ ok: false, reason: "empty_file" });
    await expect(readBatchImportFile({ name: "prompts.txt", size: 3, text: async () => " \n " }))
      .resolves.toEqual({ ok: false, reason: "empty_file" });
    await expect(readBatchImportFile({
      name: "prompts.txt",
      size: MAX_BATCH_IMPORT_CHARS + 1,
      text: async () => "ignored"
    })).resolves.toEqual({ ok: false, reason: "file_too_large" });
    await expect(readBatchImportFile({
      name: "prompts.txt",
      size: 3,
      text: async () => { throw new Error("unavailable"); }
    })).resolves.toEqual({ ok: false, reason: "read_failed" });
  });

  it("provides parser-compatible sample templates", () => {
    expect(batchTemplateContent("csv")).toMatch(/^prompt\n/);
    expect(batchTemplateContent("txt")).toContain("\n");
  });
});
