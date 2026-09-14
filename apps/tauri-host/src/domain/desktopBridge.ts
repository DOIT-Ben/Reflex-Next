import type { TauriHostApi } from "./coreBridge";
import type { WindowSizePreset } from "./viewControls";

const HOST_ACTION_EVENT = "reflex://host-action";
const HOTKEY_UNAVAILABLE_MESSAGE = "快捷键不可用，请更换组合后重试。";

export type HostAction = "open" | "recent" | "plugins" | "settings" | "history" | "quit";

export type DesktopStatus = {
  hotkey: string;
  hotkeyActive: boolean;
  message: string | null;
  panelHotkey: string;
  panelHotkeyActive: boolean;
  panelMessage: string | null;
};

export type DesktopBridge = {
  status(): Promise<DesktopStatus>;
  listen(handler: (action: HostAction) => void): Promise<() => void>;
  minimizeWindow(): Promise<void>;
  toggleMaximizeWindow(): Promise<void>;
  setWindowSize(preset: WindowSizePreset): Promise<void>;
};

export function createDesktopBridge(host: TauriHostApi): DesktopBridge {
  return {
    async status() {
      return normalizeDesktopStatus(await host.invoke("desktop_status"));
    },
    async listen(handler) {
      return host.listen<unknown>(HOST_ACTION_EVENT, ({ payload }) => {
        const action = hostActionFrom(payload);
        if (action) handler(action);
      });
    },
    async minimizeWindow() {
      await host.invoke("minimize_window");
    },
    async toggleMaximizeWindow() {
      await host.invoke("toggle_maximize_window");
    },
    async setWindowSize(preset) {
      await host.invoke("set_window_size", { preset });
    }
  };
}

export function safeDesktopSettingsError(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return message === HOTKEY_UNAVAILABLE_MESSAGE
    ? HOTKEY_UNAVAILABLE_MESSAGE
    : "设置保存失败，请重试。";
}

function normalizeDesktopStatus(value: unknown): DesktopStatus {
  const raw = isRecord(value) ? value : {};
  return {
    hotkey: typeof raw.hotkey === "string" && raw.hotkey.trim() ? raw.hotkey.trim() : "Ctrl+Alt+R",
    hotkeyActive: raw.hotkey_active === true,
    message: typeof raw.message === "string" && raw.message.trim() ? raw.message.trim() : null,
    panelHotkey:
      typeof raw.panel_hotkey === "string" && raw.panel_hotkey.trim()
        ? raw.panel_hotkey.trim()
        : "Alt+Q",
    panelHotkeyActive: raw.panel_hotkey_active === true,
    panelMessage:
      typeof raw.panel_message === "string" && raw.panel_message.trim() ? raw.panel_message.trim() : null
  };
}

function hostActionFrom(value: unknown): HostAction | null {
  if (!isRecord(value)) return null;
  return value.action === "open" ||
    value.action === "recent" ||
    value.action === "plugins" ||
    value.action === "settings" ||
    value.action === "history" ||
    value.action === "quit"
    ? value.action
    : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
