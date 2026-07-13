import { describe, expect, it } from "vitest";
import { normalizeViewScale, stepViewScale, viewScaleLabel } from "./viewControls";

describe("view controls", () => {
  it("keeps scale inside the supported range", () => {
    expect(stepViewScale(0.85, "out")).toBe(0.85);
    expect(stepViewScale(1.15, "in")).toBe(1.15);
  });

  it("moves between stable scale steps", () => {
    expect(stepViewScale(1, "in")).toBe(1.05);
    expect(stepViewScale(1, "out")).toBe(0.95);
    expect(normalizeViewScale(1.08)).toBe(1.1);
    expect(viewScaleLabel(1.1)).toBe("110%");
  });
});
