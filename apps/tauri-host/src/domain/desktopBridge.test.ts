import { describe, expect, it } from "vitest";
import type { TauriHostApi } from "./coreBridge";
import {
  createDesktopBridge,
  safeDesktopSettingsError
} from "./desktopBridge";
import { createTauriHostStub } from "./testHost";

describe("desktop bridge", () => {
  it("normalizes desktop status and subscribes to known host actions", async () => {
    const actions: string[] = [];
    const calls: string[] = [];
    const unlisten = () => undefined;
    const host: TauriHostApi = createTauriHostStub({
      invoke: async (command) => {
        calls.push(command);
        return {
          hotkey: "Ctrl+Alt+R",
          hotkey_active: true,
          message: null
        };
      },
      listen: async (eventName, handler) => {
        calls.push(eventName);
        handler({ payload: { action: "settings" } });
        handler({ payload: { action: "unknown" } });
        return unlisten;
      }
    });

    const bridge = createDesktopBridge(host);

    await expect(bridge.status()).resolves.toEqual({
      hotkey: "Ctrl+Alt+R",
      hotkeyActive: true,
      message: null
    });
    await expect(bridge.listen((action) => actions.push(action))).resolves.toBe(unlisten);
    await bridge.minimizeWindow();
    await bridge.toggleMaximizeWindow();
    await bridge.setWindowSize("wide");
    expect(actions).toEqual(["settings"]);
    expect(calls).toEqual([
      "desktop_status",
      "reflex://host-action",
      "minimize_window",
      "toggle_maximize_window",
      "set_window_size"
    ]);
  });

  it("maps only fixed hotkey failures to the specific settings message", () => {
    expect(safeDesktopSettingsError(new Error("快捷键不可用，请更换组合后重试。"))).toBe(
      "快捷键不可用，请更换组合后重试。"
    );
    expect(safeDesktopSettingsError(new Error("RegisterHotKey raw failure"))).toBe(
      "设置保存失败，请重试。"
    );
  });
});
