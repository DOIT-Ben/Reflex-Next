import { describe, expect, it } from "vitest";
import { createHostState } from "./hostState";
import { resolveAppShortcut, type AppShortcutSnapshot } from "./appShortcuts";

function createSnapshot(overrides: Partial<AppShortcutSnapshot> = {}): AppShortcutSnapshot {
  return {
    feedbackPromptOpen: false,
    scenePromptOpen: false,
    commandPaletteOpen: false,
    overlay: null,
    batchPhase: "closed",
    translationPhase: "closed",
    markdownPreviewPhase: "closed",
    hostState: createHostState(),
    ...overrides
  };
}

const key = (overrides: Partial<Parameters<typeof resolveAppShortcut>[0]> = {}) => ({
  key: "Escape",
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...overrides
});

describe("resolveAppShortcut", () => {
  it("postpones the feedback prompt with Escape before anything else", () => {
    const action = resolveAppShortcut(key(), createSnapshot({ feedbackPromptOpen: true }));
    expect(action).toEqual({ kind: "postpone_feedback" });
  });

  it("swallows keys while the scene prompt is open except Escape", () => {
    const snapshot = createSnapshot({ scenePromptOpen: true });
    expect(resolveAppShortcut(key({ key: "a" }), snapshot)).toEqual({ kind: "none" });
    expect(resolveAppShortcut(key(), snapshot)).toEqual({ kind: "cancel_scene" });
  });

  it("toggles the palette with primary+k even on workbench", () => {
    expect(resolveAppShortcut(key({ key: "k", ctrlKey: true }), createSnapshot())).toEqual({
      kind: "toggle_palette"
    });
    expect(resolveAppShortcut(key({ key: "k", metaKey: true }), createSnapshot())).toEqual({
      kind: "toggle_palette"
    });
    expect(resolveAppShortcut(key({ key: "k", ctrlKey: true, shiftKey: true }), createSnapshot())).toEqual({
      kind: "none"
    });
  });

  it("opens settings with primary+comma", () => {
    expect(resolveAppShortcut(key({ key: ",", ctrlKey: true }), createSnapshot())).toEqual({
      kind: "open_settings"
    });
  });

  it("only closes the palette with Escape while it is open", () => {
    const snapshot = createSnapshot({ commandPaletteOpen: true });
    expect(resolveAppShortcut(key(), snapshot)).toEqual({ kind: "close_palette" });
    expect(resolveAppShortcut(key({ key: "g" }), snapshot)).toEqual({ kind: "none" });
  });

  it("maps zoom shortcuts in both directions including reset", () => {
    expect(resolveAppShortcut(key({ key: "=", ctrlKey: true }), createSnapshot())).toEqual({
      kind: "zoom",
      direction: "in"
    });
    expect(resolveAppShortcut(key({ key: "-", metaKey: true }), createSnapshot())).toEqual({
      kind: "zoom",
      direction: "out"
    });
    expect(resolveAppShortcut(key({ key: "0", ctrlKey: true }), createSnapshot())).toEqual({
      kind: "zoom",
      direction: "reset"
    });
  });

  it("closes whichever tool layer is on top with Escape", () => {
    expect(
      resolveAppShortcut(key(), createSnapshot({ overlay: "template_manager" }))
    ).toEqual({ kind: "close_template_manager" });
    expect(resolveAppShortcut(key(), createSnapshot({ batchPhase: "ready" }))).toEqual({
      kind: "close_batch"
    });
    expect(
      resolveAppShortcut(key(), createSnapshot({ markdownPreviewPhase: "completed" }))
    ).toEqual({ kind: "close_markdown" });
    expect(resolveAppShortcut(key(), createSnapshot({ translationPhase: "streaming" }))).toEqual({
      kind: "close_translation"
    });
  });

  it("delegates workbench actions to the host shortcut resolver", () => {
    const readyState = { ...createHostState(), canGenerate: true };
    const snapshot = createSnapshot({ hostState: readyState });
    expect(resolveAppShortcut(key({ key: "Enter", ctrlKey: true }), snapshot)).toEqual({
      kind: "host",
      action: "generate"
    });
    expect(resolveAppShortcut(key({ key: "Escape" }), createSnapshot())).toEqual({
      kind: "host",
      action: "hide_window"
    });
    expect(resolveAppShortcut(key({ key: "Enter", ctrlKey: true }), createSnapshot())).toEqual({
      kind: "none"
    });
  });

  it("returns none for unmatched keys on the workbench", () => {
    expect(resolveAppShortcut(key({ key: "x" }), createSnapshot())).toEqual({ kind: "none" });
  });
});
