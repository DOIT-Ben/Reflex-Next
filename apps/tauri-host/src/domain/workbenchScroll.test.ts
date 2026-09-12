import { describe, expect, it, vi } from "vitest";
import { createWorkbenchScroll, type ScrollSurface } from "./workbenchScroll";

function createSurface(overrides: Partial<ScrollSurface> = {}): ScrollSurface {
  return {
    scrollHeight: 800,
    clientHeight: 400,
    scrollTop: 0,
    scrollTo: vi.fn(),
    querySelector: vi.fn(() => ({
      getBoundingClientRect: () => ({ top: 300 })
    })),
    getBoundingClientRect: () => ({ top: 100 }),
    ...overrides
  };
}

function createDeps(surface: ScrollSurface | null, overrides: Partial<Parameters<typeof createWorkbenchScroll>[0]> = {}) {
  const scheduled: Array<() => void> = [];
  const deps = {
    getSurface: () => surface,
    prefersReducedMotion: () => false,
    schedule: (callback: () => void) => scheduled.push(callback),
    ...overrides
  };
  return { deps, scheduled };
}

describe("createWorkbenchScroll", () => {
  it("reveals the result pane after completion when it is out of view", () => {
    const surface = createSurface();
    const { deps, scheduled } = createDeps(surface);
    const scroll = createWorkbenchScroll(deps);

    scroll.sync("completed", false);
    expect(scheduled).toHaveLength(1);

    scheduled[0]();
    expect(surface.scrollTo).toHaveBeenCalledWith({ top: 200, behavior: "smooth" });
  });

  it("keeps run controls visible when a generation starts", () => {
    const surface = createSurface({ scrollTop: 120 });
    const { deps } = createDeps(surface);
    const scroll = createWorkbenchScroll(deps);

    scroll.sync("streaming", true);

    expect(surface.scrollTo).toHaveBeenCalledWith({ top: 0 });
  });

  it("ignores same-phase repetitions and non-scrollable surfaces", () => {
    const surface = createSurface({ scrollHeight: 300, clientHeight: 400 });
    const { deps, scheduled } = createDeps(surface);
    const scroll = createWorkbenchScroll(deps);

    scroll.sync("streaming", true);
    scroll.sync("streaming", true);
    expect(surface.scrollTo).not.toHaveBeenCalled();

    scroll.sync("completed", false);
    expect(scheduled).toHaveLength(1);
    scheduled[0]();
    expect(surface.scrollTo).not.toHaveBeenCalled();
  });

  it("respects reduced motion preference", () => {
    const surface = createSurface();
    const { deps, scheduled } = createDeps(surface, { prefersReducedMotion: () => true });
    const scroll = createWorkbenchScroll(deps);

    scroll.sync("error", false);
    scheduled[0]();

    expect(surface.scrollTo).toHaveBeenCalledWith({ top: 200, behavior: "auto" });
  });

  it("does nothing without a surface", () => {
    const { deps, scheduled } = createDeps(null);
    const scroll = createWorkbenchScroll(deps);

    scroll.sync("streaming", true);

    expect(scheduled).toHaveLength(0);
  });
});
