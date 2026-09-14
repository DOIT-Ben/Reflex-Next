export type ProviderAvailability = "checking" | "ready" | "missing" | "unavailable";

export type WindowSizePreset = "compact" | "default" | "wide";

export interface ToolbarItem {
  id: string;
  label: string;
  symbol: string;
  shortcut?: string;
  disabled?: boolean;
}

export type StatusTone = "idle" | "working" | "success" | "warning" | "error";
