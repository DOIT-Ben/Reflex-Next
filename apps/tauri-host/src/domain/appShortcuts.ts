import type { HostState } from "./hostState";
import { resolveHostShortcut } from "./hostState";
import type { BatchPhase } from "./batchState";
import type { MarkdownPreviewPhase } from "./markdownPreviewState";
import type { TranslationPhase } from "./translationState";

export type ShortcutKeyEvent = {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
};

export type AppShortcutSnapshot = {
  feedbackPromptOpen: boolean;
  scenePromptOpen: boolean;
  commandPaletteOpen: boolean;
  overlay: HostState["overlay"];
  batchPhase: BatchPhase;
  translationPhase: TranslationPhase;
  markdownPreviewPhase: MarkdownPreviewPhase;
  hostState: HostState;
};

export type AppShortcutAction =
  | { kind: "none" }
  | { kind: "postpone_feedback" }
  | { kind: "cancel_scene" }
  | { kind: "toggle_palette" }
  | { kind: "open_settings" }
  | { kind: "close_palette" }
  | { kind: "zoom"; direction: "in" | "out" | "reset" }
  | { kind: "close_template_manager" }
  | { kind: "close_batch" }
  | { kind: "close_markdown" }
  | { kind: "close_translation" }
  | { kind: "host"; action: Exclude<ReturnType<typeof resolveHostShortcut>, "none"> };

export function isPrimaryShortcut(event: ShortcutKeyEvent): boolean {
  return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey;
}

export function resolveAppShortcut(
  event: ShortcutKeyEvent,
  snapshot: AppShortcutSnapshot
): AppShortcutAction {
  const { feedbackPromptOpen, scenePromptOpen, commandPaletteOpen, overlay, hostState } = snapshot;

  if (feedbackPromptOpen && event.key === "Escape") {
    return { kind: "postpone_feedback" };
  }
  if (scenePromptOpen) {
    return event.key === "Escape" ? { kind: "cancel_scene" } : { kind: "none" };
  }
  if (isPrimaryShortcut(event) && event.key.toLowerCase() === "k") {
    return { kind: "toggle_palette" };
  }
  if (isPrimaryShortcut(event) && event.key === ",") {
    return { kind: "open_settings" };
  }
  if (commandPaletteOpen) {
    return event.key === "Escape" ? { kind: "close_palette" } : { kind: "none" };
  }
  if (isPrimaryShortcut(event)) {
    if (event.key === "+" || event.key === "=") return { kind: "zoom", direction: "in" };
    if (event.key === "-") return { kind: "zoom", direction: "out" };
    if (event.key === "0") return { kind: "zoom", direction: "reset" };
  }
  if (overlay === "template_manager") {
    return event.key === "Escape" ? { kind: "close_template_manager" } : { kind: "none" };
  }
  if (snapshot.batchPhase !== "closed") {
    return event.key === "Escape" ? { kind: "close_batch" } : { kind: "none" };
  }
  if (snapshot.markdownPreviewPhase !== "closed") {
    return event.key === "Escape" ? { kind: "close_markdown" } : { kind: "none" };
  }
  if (snapshot.translationPhase !== "closed") {
    return event.key === "Escape" ? { kind: "close_translation" } : { kind: "none" };
  }

  const action = resolveHostShortcut(hostState, {
    key: event.key,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey
  });
  if (action === "none") return { kind: "none" };
  return { kind: "host", action };
}
