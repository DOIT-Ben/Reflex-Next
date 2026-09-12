import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createOptimizationFlow } from "./optimizationFlow";
import type { CoreBridge } from "./coreBridge";
import type { CoreEvent } from "./reflexSession";
import type { HostState } from "./hostState";
import { createHostState } from "./hostState";

type FlowDeps = Parameters<typeof createOptimizationFlow>[0];

function createCoreBridge(events: CoreEvent[]): CoreBridge {
  return {
    optimize: async function* () {
      for (const event of events) yield event;
    }
  };
}

function createDeps(
  events: CoreEvent[],
  overrides: Partial<FlowDeps> = {},
  options: { canGenerate?: boolean; scenePolicy?: string } = {}
) {
  const hostState: { state: HostState } = { state: createHostState() };
  hostState.state = {
    ...hostState.state,
    requestDraft: {
      ...hostState.state.requestDraft,
      scene_policy: (options.scenePolicy ?? "auto") as HostState["requestDraft"]["scene_policy"]
    },
    canGenerate: true
  } as HostState;
  const deps: FlowDeps = {
    coreBridge: () => createCoreBridge(events),
    updateHostState: (updater) => {
      hostState.state = updater(hostState.state);
    },
    hostState: () => hostState.state,
    canGenerate: () => options.canGenerate ?? true,
    language: () => "zh-CN",
    onSuccessfulCompletion: vi.fn(async () => undefined),
    ...overrides
  };
  return { deps, hostState };
}

const doneEvent: CoreEvent = {
  type: "done",
  data: { text: "优化结果", final_text: "优化结果" }
} as unknown as CoreEvent;

describe("createOptimizationFlow", () => {
  it("streams events into the host state and fires the completion hook once", async () => {
    const { deps, hostState } = createDeps(
      [
        { type: "chunk", data: { text: "优化" } } as unknown as CoreEvent,
        doneEvent
      ]
    );
    const flow = createOptimizationFlow(deps);

    await flow.request();

    expect(hostState.state.phase).toBe("completed");
    expect(hostState.state.output).toBe("优化结果");
    expect(deps.onSuccessfulCompletion).toHaveBeenCalledTimes(1);
    expect(flow.isRunning()).toBe(false);
  });

  it("opens the scene prompt first when the policy asks", async () => {
    const { deps, hostState } = createDeps([], {}, { scenePolicy: "ask" });
    hostState.state = {
      ...hostState.state,
      requestDraft: { ...hostState.state.requestDraft, scene_policy: "ask", scene: "email" }
    } as HostState;
    const flow = createOptimizationFlow(deps);

    await flow.request();

    expect(get(flow.scenePromptOpen)).toBe(true);
    expect(get(flow.scenePromptSelection)).toBe("email");
    expect(deps.onSuccessfulCompletion).not.toHaveBeenCalled();
  });

  it("runs with the chosen scene after confirmation", async () => {
    const { deps, hostState } = createDeps([doneEvent], {}, { scenePolicy: "ask" });
    const flow = createOptimizationFlow(deps);

    await flow.request();
    flow.scenePromptSelection.set("email");
    await flow.confirmScene();

    expect(hostState.state.phase).toBe("completed");
    expect(get(flow.scenePromptOpen)).toBe(false);
  });

  it("marks the stream as failed when the bridge throws mid-run", async () => {
    const { deps, hostState } = createDeps([], {
      coreBridge: () =>
        ({
          optimize: async function* () {
            yield { type: "chunk", data: { text: "x" } } as unknown as CoreEvent;
            throw new Error("connection lost");
          }
        }) as unknown as CoreBridge
    });
    const flow = createOptimizationFlow(deps);

    await flow.request();

    expect(hostState.state.phase).toBe("error");
    expect(hostState.state.errorCode).toBe("runtime_stream_failed");
    expect(hostState.state.errorRecoverable).toBe(true);
  });

  it("does nothing when generation is not allowed", async () => {
    const { deps, hostState } = createDeps([doneEvent], {}, { canGenerate: false });
    const flow = createOptimizationFlow(deps);

    await flow.request();

    expect(hostState.state.phase).toBe("empty");
    expect(deps.onSuccessfulCompletion).not.toHaveBeenCalled();
  });

  it("cancel aborts the run and returns to the pre-run phase", async () => {
    let release: (() => void) | undefined;
    const { deps, hostState } = createDeps([], {
      coreBridge: () =>
        ({
          optimize: async function* () {
            yield { type: "chunk", data: { text: "partial" } } as unknown as CoreEvent;
            await new Promise<void>((resolve) => {
              release = resolve;
            });
            yield { type: "done", data: { text: "partial" } } as unknown as CoreEvent;
          }
        }) as unknown as CoreBridge
    });
    hostState.state = { ...hostState.state, inputText: "some input" } as HostState;
    const flow = createOptimizationFlow(deps);

    const running = flow.request();
    await vi.waitFor(() => expect(hostState.state.phase).toBe("streaming"));
    flow.cancel();
    release?.();
    await running;

    expect(hostState.state.phase).toBe("ready");
    expect(flow.isRunning()).toBe(false);
  });
});
