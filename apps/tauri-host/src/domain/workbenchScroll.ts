import type { HostState } from "./hostState";

export type ScrollSurface = {
  scrollHeight: number;
  clientHeight: number;
  scrollTop: number;
  scrollTo: (options: { top: number; behavior?: "auto" | "smooth" }) => void;
  querySelector: (selector: string) => { getBoundingClientRect: () => { top: number } } | null;
  getBoundingClientRect: () => { top: number };
};

export type WorkbenchScrollDeps = {
  getSurface: () => ScrollSurface | null;
  prefersReducedMotion: () => boolean;
  schedule: (callback: () => void) => void;
};

const RESULT_PANE_SELECTOR = ".result-pane";
const REVEAL_THRESHOLD_PX = 4;

export function createWorkbenchScroll(deps: WorkbenchScrollDeps) {
  let lastPhase: HostState["phase"] | null = null;

  function scrollableSurface(): ScrollSurface | null {
    const surface = deps.getSurface();
    if (!surface || surface.scrollHeight <= surface.clientHeight) return null;
    return surface;
  }

  function revealResultPane() {
    const surface = scrollableSurface();
    const resultPane = deps.getSurface()?.querySelector(RESULT_PANE_SELECTOR) ?? null;
    if (!surface || !resultPane) return;
    const delta = resultPane.getBoundingClientRect().top - surface.getBoundingClientRect().top;
    if (Math.abs(delta) < REVEAL_THRESHOLD_PX) return;
    surface.scrollTo({
      top: surface.scrollTop + delta,
      behavior: deps.prefersReducedMotion() ? "auto" : "smooth"
    });
  }

  function revealRunControls() {
    const surface = scrollableSurface();
    if (!surface || surface.scrollTop <= 0) return;
    surface.scrollTo({ top: 0 });
  }

  function sync(phase: HostState["phase"], generating: boolean) {
    if (phase === lastPhase) return;
    lastPhase = phase;
    if (phase === "completed" || phase === "error") {
      deps.schedule(revealResultPane);
    } else if (generating) {
      revealRunControls();
    }
  }

  return { sync };
}
