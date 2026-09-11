import { get, writable, type Writable } from "svelte/store";
import type { CapabilityInvokeBridge } from "./translationFlow";
import {
  closeMarkdownPreview,
  completeMarkdownPreview,
  createMarkdownPreviewState,
  failMarkdownPreview,
  openMarkdownPreview,
  selectMarkdownPreviewMode,
  type MarkdownPreviewMode,
  type MarkdownPreviewState
} from "./markdownPreviewState";

export type MarkdownPreviewFlowDeps = {
  capabilityBridge: () => CapabilityInvokeBridge | null;
};

export type MarkdownPreviewFlow = {
  state: Writable<MarkdownPreviewState>;
  open: (source: string, enabled: boolean) => void;
  run: () => Promise<void>;
  setMode: (mode: MarkdownPreviewMode) => void;
  close: () => void;
};

const PLUGIN_TIMEOUT_MS = 20_000;

export function createMarkdownPreviewFlow(deps: MarkdownPreviewFlowDeps): MarkdownPreviewFlow {
  const state = writable<MarkdownPreviewState>(createMarkdownPreviewState());
  let runController: AbortController | null = null;

  function open(source: string, enabled: boolean) {
    if (!source.trim() || !enabled) return;
    state.set(openMarkdownPreview(get(state), source));
    if (get(state).phase !== "closed") {
      void run();
    }
  }

  async function run() {
    if (get(state).phase === "closed") return;
    runController?.abort();
    const request = get(state).request;
    const controller = new AbortController();
    runController = controller;
    const bridge = deps.capabilityBridge();
    if (!bridge) {
      state.set(failMarkdownPreview(get(state), request));
      runController = null;
      return;
    }
    try {
      for await (const event of bridge.invoke(
        "markdown-preview",
        "preview",
        { text: get(state).sourceText },
        { signal: controller.signal, timeoutMs: PLUGIN_TIMEOUT_MS }
      )) {
        if (controller.signal.aborted || runController !== controller) return;
        if (event.status === "result") {
          state.set(completeMarkdownPreview(get(state), request, event.data));
        } else if (event.status === "error" || event.status === "cancelled") {
          state.set(failMarkdownPreview(get(state), request));
        }
      }
    } catch {
      if (runController === controller && !controller.signal.aborted) {
        state.set(failMarkdownPreview(get(state), request));
      }
    } finally {
      if (runController === controller) runController = null;
    }
  }

  function setMode(mode: MarkdownPreviewMode) {
    state.set(selectMarkdownPreviewMode(get(state), mode));
  }

  function close() {
    runController?.abort();
    runController = null;
    state.set(closeMarkdownPreview(get(state)));
  }

  return { state, open, run, setMode, close };
}
