export type ProviderAvailability = "checking" | "ready" | "missing" | "unavailable";

export type WindowSizePreset = "compact" | "default" | "wide";

export type NavItemGroup = "primary" | "utility";

export interface NavRailItem {
  id: string;
  label: string;
  symbol: string;
  shortcut?: string;
  group?: NavItemGroup;
  disabled?: boolean;
}

export type StatusTone = "idle" | "working" | "success" | "warning" | "error";
