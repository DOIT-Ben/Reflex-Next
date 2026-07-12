import { describe, expect, it } from "vitest";
import { resultMarkdownContent, resultMarkdownFilename } from "./resultExport";

describe("result export", () => {
  it("creates a stable markdown filename", () => {
    expect(resultMarkdownFilename(new Date(2026, 6, 12, 9, 5, 3))).toBe(
      "reflex-result-20260712090503.md"
    );
  });

  it("keeps output content while normalizing line endings", () => {
    expect(resultMarkdownContent("# Title\r\n\rText")).toBe("# Title\n\nText");
  });
});
