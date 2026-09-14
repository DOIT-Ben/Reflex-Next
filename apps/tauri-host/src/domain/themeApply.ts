/**
 * 把主题选择镜像到 <html>，让脱离 .app-shell 的节点也能拿到主题：
 * - bits-ui 弹层（对话框/下拉/提示）会 portal 到 body；
 * - Tailwind 的 dark: 变体基于 .dark 类（与 CC Switch 一致）。
 */
export type ThemeChoice = "light" | "dark" | "system";

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false
  );
}

export function applyDocumentTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark" || (theme === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
}

/**
 * system 档下跟随 OS 深浅实时切换（对齐 CC Switch 的 theme-provider）。
 * 返回解绑函数，便于测试与卸载时清理。
 */
export function watchSystemTheme(onChange: (dark: boolean) => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => {};
  }
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const handler = (event: MediaQueryListEvent): void => onChange(event.matches);
  media.addEventListener("change", handler);
  return () => media.removeEventListener("change", handler);
}
