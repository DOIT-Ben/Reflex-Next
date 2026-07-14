import { describe, expect, it, vi } from "vitest";

import type { TauriHostApi } from "./coreBridge";
import { createFeedbackBridge, type FeedbackPayload } from "./feedbackBridge";

function hostWithInvoke(invoke: TauriHostApi["invoke"]): TauriHostApi {
  return { invoke, listen: vi.fn() };
}

const payload: FeedbackPayload = {
  sentiment: "negative",
  category: "quality",
  message: "结果不准确",
  expected_output: "保留约束",
  contact: "",
  context: {
    app_version: "0.7.0",
    os_version: "Windows",
    provider: "minimax",
    model: "model",
    mode: "content",
    style: "balanced",
    scene: "general",
    request_id: "request-1",
    diagnostic_id: "diag-1",
    error_code: "",
    elapsed_ms: 100
  },
  include_prompt: false,
  include_result: false,
  include_screenshot: false,
  prompt_text: null,
  result_text: null,
  screenshot: null,
  consent_version: "2026-07-14"
};

describe("feedback bridge", () => {
  it("captures only through the scoped Tauri command", async () => {
    const invoke = vi.fn().mockResolvedValue({ media_type: "image/png", data_base64: "fixture" });
    const bridge = createFeedbackBridge(hostWithInvoke(invoke));

    await expect(bridge.captureWindow()).resolves.toEqual({
      media_type: "image/png",
      data_base64: "fixture"
    });
    expect(invoke).toHaveBeenCalledWith("capture_feedback_screenshot");
  });

  it("submits the exact consent-bound payload without adding private fields", async () => {
    const invoke = vi.fn().mockResolvedValue({ id: "feedback-1", status: "new" });
    const bridge = createFeedbackBridge(hostWithInvoke(invoke));

    await expect(bridge.submit(payload)).resolves.toEqual({ id: "feedback-1", status: "new" });
    expect(invoke).toHaveBeenCalledWith("submit_feedback", { payload });
    expect(JSON.stringify(invoke.mock.calls)).not.toContain("api_key");
  });

  it("rejects malformed screenshot and submission responses", async () => {
    const malformedCapture = createFeedbackBridge(hostWithInvoke(vi.fn().mockResolvedValue({})));
    const malformedSubmit = createFeedbackBridge(
      hostWithInvoke(vi.fn().mockResolvedValue({ id: "feedback-1" }))
    );

    await expect(malformedCapture.captureWindow()).rejects.toThrow("反馈截图暂不可用");
    await expect(malformedSubmit.submit(payload)).rejects.toThrow("反馈服务返回了无效结果");
  });
});
