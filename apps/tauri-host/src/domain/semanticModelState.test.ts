import { describe, expect, it } from "vitest";
import {
  applySemanticModelEvent,
  beginSemanticModelOperation,
  createSemanticModelState,
  failSemanticModelOperation,
  semanticModelSizeLabel
} from "./semanticModelState";

function event(status: "progress" | "result" | "error", data: Record<string, unknown>, code?: string) {
  return {
    version: 1 as const,
    request_id: "semantic-1",
    type: "plugin_event" as const,
    plugin_id: "semantic-detector",
    operation: "status",
    status,
    data,
    ...(code ? { code } : {})
  };
}

describe("semantic model state", () => {
  it("tracks bounded download progress and a ready model", () => {
    let state = beginSemanticModelOperation(createSemanticModelState(), "download");
    state = applySemanticModelEvent(state, event("progress", { percent: 140 }));
    expect(state.percent).toBe(100);

    state = applySemanticModelEvent(
      state,
      event("result", {
        model_id: "sentence-transformers/example",
        model_state: "ready",
        runtime_state: "ready",
        size_bytes: 1572864
      })
    );

    expect(state.phase).toBe("ready");
    expect(state.runtimeReady).toBe(true);
    expect(semanticModelSizeLabel(state.sizeBytes)).toBe("1.5 MB");
  });

  it("represents missing runtime and rejects malformed results", () => {
    const missing = applySemanticModelEvent(
      createSemanticModelState(),
      event("result", {
        model_id: "sentence-transformers/example",
        model_state: "missing",
        runtime_state: "missing",
        size_bytes: 0
      })
    );
    expect(missing.phase).toBe("missing");
    expect(missing.runtimeReady).toBe(false);

    const malformed = applySemanticModelEvent(
      missing,
      event("result", { model_state: "ready" })
    );
    expect(malformed.errorCode).toBe("plugin_invalid_result");
  });

  it("keeps only safe error state for bridge and plugin failures", () => {
    const pluginError = applySemanticModelEvent(
      createSemanticModelState(),
      event("error", {}, "model_download_failed")
    );
    expect(pluginError.errorCode).toBe("model_download_failed");
    expect(failSemanticModelOperation(pluginError).errorCode).toBe("plugin_unavailable");
  });
});
