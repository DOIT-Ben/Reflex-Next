export const settingsSections = [
  { id: "provider", label: "模型与 Provider" },
  { id: "defaults", label: "默认行为" },
  { id: "clipboard", label: "剪贴板" },
  { id: "privacy", label: "安全与隐私" },
  { id: "plugins", label: "插件" }
] as const;

export type SettingsSection = (typeof settingsSections)[number]["id"];
