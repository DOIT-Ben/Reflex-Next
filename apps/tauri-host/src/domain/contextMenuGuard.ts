/**
 * WebView2/WebKit 在右键时会弹出内核自带的浏览器菜单（刷新/全选/检查元素…），
 * 这在桌面应用里显得像网页而不是产品。这里统一拦截：非可编辑区域一律禁用
 * 默认菜单，输入框与可编辑区域内保留（复制、粘贴、全选仍然可用）。
 */
const EDITABLE_SELECTOR = "input, textarea, [contenteditable='true'], [contenteditable='']";

type ClosestCapable = { closest?: (selector: string) => unknown };
type GuardTarget = {
  addEventListener(
    type: string,
    listener: (event: { target?: unknown; preventDefault: () => void }) => void,
    capture?: boolean
  ): void;
  removeEventListener(
    type: string,
    listener: (event: { target?: unknown; preventDefault: () => void }) => void,
    capture?: boolean
  ): void;
};

function isEditableTarget(target: unknown): boolean {
  const candidate = target as ClosestCapable | null | undefined;
  if (!candidate || typeof candidate.closest !== "function") {
    return false;
  }
  return Boolean(candidate.closest(EDITABLE_SELECTOR));
}

export function installContextMenuGuard(
  target: GuardTarget = window
): () => void {
  const handler = (event: { target?: unknown; preventDefault: () => void }) => {
    if (isEditableTarget(event.target)) {
      return;
    }
    event.preventDefault();
  };
  target.addEventListener("contextmenu", handler, true);
  return () => target.removeEventListener("contextmenu", handler, true);
}
