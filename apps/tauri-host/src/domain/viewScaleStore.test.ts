import { get } from "svelte/store";
import { describe, expect, it } from "vitest";
import { createViewScaleStore, type ViewScaleStorage } from "./viewScaleStore";

function createMemoryStorage(initial: Record<string, string> = {}): ViewScaleStorage {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, value)
  };
}

describe("createViewScaleStore", () => {
  it("starts at 1 when storage is unavailable", () => {
    const viewScale = createViewScaleStore(null);
    expect(get(viewScale)).toBe(1);
  });

  it("restores the persisted scale on creation", () => {
    const viewScale = createViewScaleStore(createMemoryStorage({ "reflex-view-scale": "1.15" }));
    expect(get(viewScale)).toBe(1.15);
  });

  it("falls back to 1 when the stored value is invalid", () => {
    const viewScale = createViewScaleStore(createMemoryStorage({ "reflex-view-scale": "NaN" }));
    expect(get(viewScale)).toBe(1);
  });

  it("persists normalized values on set", () => {
    const storage = createMemoryStorage();
    const viewScale = createViewScaleStore(storage);

    viewScale.set(0.9);
    expect(get(viewScale)).toBe(0.9);
    expect(storage.getItem("reflex-view-scale")).toBe("0.9");
  });

  it("keeps the view usable when storage writes throw", () => {
    const storage: ViewScaleStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("storage blocked");
      }
    };
    const viewScale = createViewScaleStore(storage);

    viewScale.set(1.1);
    expect(get(viewScale)).toBe(1.1);
  });

  it("steps and resets within the allowed scale range", () => {
    const viewScale = createViewScaleStore(null);

    viewScale.step("in");
    expect(get(viewScale)).toBeGreaterThan(1);

    viewScale.reset();
    expect(get(viewScale)).toBe(1);

    viewScale.step("out");
    expect(get(viewScale)).toBeLessThan(1);
  });
});
