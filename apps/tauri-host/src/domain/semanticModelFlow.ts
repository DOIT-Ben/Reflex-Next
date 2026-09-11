import { get, writable, type Writable } from "svelte/store";
import type { CapabilityInvokeBridge } from "./translationFlow";
import {
  applySemanticModelEvent,
  beginSemanticModelOperation,
  createSemanticModelState,
  failSemanticModelOperation,
  type SemanticModelState
} from "./semanticModelState";

export type SemanticModelOperation = "status" | "download" | "delete";

export type SemanticModelFlowDeps = {
  capabilityBridge: () => CapabilityInvokeBridge | null;
  isEnabled: () => boolean;
};

export type SemanticModelFlow = {
  state: Writable<SemanticModelState>;
  run: (operation: SemanticModelOperation) => Promise<void>;
  cancel: () => void;
  reset: () => void;
};

export function createSemanticModelFlow(deps: SemanticModelFlowDeps): SemanticModelFlow {
  const state = writable<SemanticModelState>(createSemanticModelState());
  let runController: AbortController | null = null;

  async function run(operation: SemanticModelOperation) {
    const bridge = deps.capabilityBridge();
    if (!bridge || !deps.isEnabled()) return;
    runController?.abort();
    const controller = new AbortController();
    runController = controller;
    state.set(beginSemanticModelOperation(get(state), operation));
    try {
      for await (const event of bridge.invoke("semantic-detector", operation, {}, {
        signal: controller.signal,
        timeoutMs: operation === "download" ? 1_800_000 : 30_000
      })) {
        if (runController !== controller || controller.signal.aborted) return;
        state.set(applySemanticModelEvent(get(state), event));
      }
    } catch {
      if (runController !== controller) return;
      state.set(
        controller.signal.aborted
          ? {
              ...get(state),
              phase: get(state).sizeBytes > 0 ? "ready" : "missing",
              percent: 0,
              errorCode: null
            }
          : failSemanticModelOperation(get(state))
      );
    } finally {
      if (runController === controller) runController = null;
    }
  }

  function cancel() {
    runController?.abort();
  }

  function reset() {
    runController?.abort();
    runController = null;
    state.set(createSemanticModelState());
  }

  return { state, run, cancel, reset };
}
