import { get, writable, type Writable } from "svelte/store";
import type { CoreBridge } from "./coreBridge";
import { isSuccessfulCompletionEvent } from "./coreBridge";
import type { CoreEvent } from "./reflexSession";
import type { HostState } from "./hostState";
import {
  applyCoreEnvelope,
  cancelGeneration,
  createRequestDraft,
  createRequestDraftWithSceneChoice,
  startGeneration
} from "./hostState";
import type { OptimizeRequestDraft } from "./reflexSession";

export type OptimizationFlowDeps = {
  coreBridge: () => CoreBridge;
  updateHostState: (updater: (state: HostState) => HostState) => void;
  hostState: () => HostState;
  canGenerate: () => boolean;
  language: () => "zh-CN" | "en-US";
  onSuccessfulCompletion: () => Promise<void>;
};

export type OptimizationFlow = {
  scenePromptOpen: Writable<boolean>;
  scenePromptSelection: Writable<string>;
  isRunning: () => boolean;
  request: () => Promise<void>;
  confirmScene: () => Promise<void>;
  cancelScene: () => void;
  cancel: () => void;
  dispose: () => void;
};

const STREAM_FAILED_EVENT = {
  type: "error" as const,
  data: {
    code: "runtime_stream_failed",
    message: "生成服务连接中断，请重试。",
    recoverable: true,
    action: "retry"
  }
};

export function createOptimizationFlow(deps: OptimizationFlowDeps): OptimizationFlow {
  const scenePromptOpen = writable(false);
  const scenePromptSelection = writable("");
  let activeRun: AbortController | null = null;

  function isRunning(): boolean {
    return activeRun !== null;
  }

  function request(): Promise<void> {
    const state = deps.hostState();
    if (!deps.canGenerate()) return Promise.resolve();
    if (state.requestDraft.scene_policy === "ask") {
      scenePromptSelection.set(state.requestDraft.scene ?? "");
      scenePromptOpen.set(true);
      return Promise.resolve();
    }
    return execute(createRequestDraft(state, deps.language()));
  }

  function cancelScene() {
    scenePromptOpen.set(false);
  }

  async function confirmScene() {
    if (!deps.canGenerate()) {
      scenePromptOpen.set(false);
      return;
    }
    const request = createRequestDraftWithSceneChoice(
      deps.hostState(),
      get(scenePromptSelection),
      deps.language()
    );
    scenePromptOpen.set(false);
    await execute(request);
  }

  async function execute(request: OptimizeRequestDraft = createRequestDraft(deps.hostState(), deps.language())) {
    if (activeRun !== null || !deps.canGenerate()) return;
    const requestId = `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const controller = new AbortController();
    activeRun = controller;
    deps.updateHostState((state) => startGeneration(state, requestId));
    let completionHandled = false;

    try {
      for await (const event of deps.coreBridge().optimize(request, {
        signal: controller.signal
      })) {
        if (controller.signal.aborted) break;
        applyEvent(requestId, event);
        if (
          !completionHandled &&
          isSuccessfulCompletionEvent(event) &&
          deps.hostState().phase === "completed" &&
          Boolean(deps.hostState().currentResult?.output.trim())
        ) {
          completionHandled = true;
          await deps.onSuccessfulCompletion();
        }
      }
    } catch {
      if (!controller.signal.aborted && deps.hostState().phase !== "completed") {
        applyEvent(requestId, STREAM_FAILED_EVENT as CoreEvent);
      }
    } finally {
      if (activeRun === controller) {
        activeRun = null;
      }
    }
  }

  function applyEvent(requestId: string, event: CoreEvent) {
    deps.updateHostState((state) =>
      applyCoreEnvelope(state, {
        version: 1,
        request_id: requestId,
        event
      })
    );
  }

  function cancel() {
    activeRun?.abort();
    activeRun = null;
    deps.updateHostState((state) => cancelGeneration(state));
  }

  function dispose() {
    activeRun?.abort();
    activeRun = null;
  }

  return {
    scenePromptOpen,
    scenePromptSelection,
    isRunning,
    request,
    confirmScene,
    cancelScene,
    cancel,
    dispose
  };
}
