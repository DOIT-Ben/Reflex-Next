import { writable, type Writable } from "svelte/store";
import type { DesktopBridge } from "./desktopBridge";
import type { WindowSizePreset } from "./viewControls";

export type WindowControlsDeps = {
  desktopBridge: () => DesktopBridge | null;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type WindowControls = {
  sizePreset: Writable<WindowSizePreset>;
  minimize: () => Promise<void>;
  toggleMaximize: () => Promise<void>;
  setSize: (preset: WindowSizePreset) => Promise<void>;
};

export function createWindowControls(deps: WindowControlsDeps): WindowControls {
  const sizePreset = writable<WindowSizePreset>("default");

  async function minimize() {
    try {
      await deps.desktopBridge()?.minimizeWindow();
    } catch {
      deps.showToast("窗口操作暂不可用。");
    }
  }

  async function toggleMaximize() {
    try {
      await deps.desktopBridge()?.toggleMaximizeWindow();
    } catch {
      deps.showToast("窗口操作暂不可用。");
    }
  }

  async function setSize(preset: WindowSizePreset) {
    try {
      await deps.desktopBridge()?.setWindowSize(preset);
      sizePreset.set(preset);
    } catch {
      deps.showToast("窗口尺寸暂不可用。");
    }
  }

  return { sizePreset, minimize, toggleMaximize, setSize };
}
