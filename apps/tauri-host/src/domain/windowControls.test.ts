import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createWindowControls } from "./windowControls";
import type { DesktopBridge } from "./desktopBridge";

type FlowDeps = Parameters<typeof createWindowControls>[0];

function createDeps(overrides: Partial<FlowDeps> = {}) {
  return {
    desktopBridge: () =>
      ({
        minimizeWindow: vi.fn(async () => undefined),
        toggleMaximizeWindow: vi.fn(async () => undefined),
        setWindowSize: vi.fn(async () => undefined)
      }) as unknown as DesktopBridge,
    showToast: vi.fn(),
    ...overrides
  } as FlowDeps;
}

describe("createWindowControls", () => {
  it("updates the preset after a successful size change", async () => {
    const flow = createWindowControls(createDeps());

    await flow.setSize("compact");

    expect(get(flow.sizePreset)).toBe("compact");
  });

  it("keeps the preset and toasts when the bridge rejects", async () => {
    const showToast = vi.fn();
    const flow = createWindowControls(
      createDeps({
        desktopBridge: () =>
          ({
            setWindowSize: vi.fn(async () => {
              throw new Error("bridge down");
            })
          }) as unknown as DesktopBridge,
        showToast
      })
    );

    await flow.setSize("wide");

    expect(get(flow.sizePreset)).toBe("default");
    expect(showToast).toHaveBeenCalledWith("窗口尺寸暂不可用。");
  });

  it("toasts window operation failures for minimize and maximize", async () => {
    const showToast = vi.fn();
    const flow = createWindowControls(
      createDeps({
        desktopBridge: () =>
          ({
            minimizeWindow: vi.fn(async () => {
              throw new Error("x");
            }),
            toggleMaximizeWindow: vi.fn(async () => {
              throw new Error("x");
            })
          }) as unknown as DesktopBridge,
        showToast
      })
    );

    await flow.minimize();
    await flow.toggleMaximize();

    expect(showToast).toHaveBeenCalledTimes(2);
    expect(showToast).toHaveBeenCalledWith("窗口操作暂不可用。");
  });

  it("tolerates a missing bridge without toasting", async () => {
    const showToast = vi.fn();
    const flow = createWindowControls(createDeps({ desktopBridge: () => null, showToast }));

    await flow.minimize();
    await flow.setSize("compact");

    expect(showToast).not.toHaveBeenCalled();
    expect(get(flow.sizePreset)).toBe("compact");
  });
});
