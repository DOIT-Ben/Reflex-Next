import { describe, expect, it } from "vitest";
import { t } from "./i18n";

describe("ui messages", () => {
  it("keeps every primary user-flow label available in both languages", () => {
    expect(t("zh-CN", "optimize")).toBe("优化文本");
    expect(t("en-US", "optimize")).toBe("Optimize text");
    expect(t("en-US", "cancel")).toBe("Cancel");
  });
});
