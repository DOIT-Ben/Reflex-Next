/**
 * 把主题选择镜像到 <html>，让脱离 .app-shell 的节点也能拿到主题：
 * - bits-ui 弹层（对话框/下拉/提示）会 portal 到 body；
 * - Tailwind 的 dark: 变体基于 [data-theme="dark"] 选择器。
 */
export type ThemeChoice = "light" | "dark" | "system";

export function applyDocumentTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  // Tailwind 的 dark: 变体与 shadcn 深色 token 走 .dark 类（与 CC Switch 一致）
  const prefersDark =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
}
