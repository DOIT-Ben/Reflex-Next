import { describe, expect, it, vi } from "vitest";

import type { TauriHostApi } from "./coreBridge";
import {
  createPromptFeedbackPayload,
  createFeedbackBridge,
  feedbackSubmitErrorMessage,
  type FeedbackPayload
} from "./feedbackBridge";

function hostWithInvoke(invoke: TauriHostApi["invoke"]): TauriHostApi {
  return { invoke, listen: vi.fn() };
}

const payload: FeedbackPayload = {
  source: "manual",
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
  consent_version: "2026-07-15"
};

describe("feedback bridge", () => {
  it("builds a one-click prompt response without attaching user content", () => {
    expect(
      createPromptFeedbackPayload({
        sentiment: "positive",
        context: payload.context,
        consentVersion: "2026-07-15"
      })
    ).toEqual({
      ...payload,
      source: "prompt",
      sentiment: "positive",
      message: "",
      expected_output: "",
      contact: "",
      context: payload.context
    });
  });

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

  it("keeps actionable feedback errors and redacts unknown host failures", async () => {
    expect(feedbackSubmitErrorMessage("请先在设置中开启对应的隐私授权。"))
      .toBe("请先在设置中开启对应的隐私授权。");
    expect(feedbackSubmitErrorMessage(new Error("api_key=private-value")))
      .toBe("反馈发送失败，请稍后重试。");
    expect(feedbackSubmitErrorMessage("反馈附件暂时无法保存，请稍后再试。"))
      .toBe("反馈附件暂时无法保存，请稍后再试。");

    const invoke = vi.fn().mockRejectedValue("请先在设置中开启对应的隐私授权。");
    const bridge = createFeedbackBridge(hostWithInvoke(invoke));
    await expect(bridge.submit(payload)).rejects.toThrow("请先在设置中开启对应的隐私授权");
  });

  it("reads and updates cloud privacy and quota without exposing the installation token", async () => {
    const consent = {
      usage_metrics: false,
      improvement_data: true,
      feedback_attachments: false,
      policy_version: "2026-07-14",
      updated_at: null
    };
    const quota = {
      usage_date: "2026-07-14",
      requests_used: 1,
      requests_limit: 20,
      input_chars_used: 10,
      input_chars_limit: 200000,
      output_chars_used: 8,
      output_chars_limit: 200000
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "cloud_get_quota") return quota;
      if (command === "cloud_delete_data") return true;
      return consent;
    });
    const bridge = createFeedbackBridge(hostWithInvoke(invoke));

    await expect(bridge.getConsent()).resolves.toEqual(consent);
    await expect(bridge.updateConsent(consent)).resolves.toEqual(consent);
    await expect(bridge.getQuota()).resolves.toEqual(quota);
    await expect(bridge.deleteCloudData()).resolves.toBe(true);
    expect(JSON.stringify(invoke.mock.calls)).not.toContain("installation");
  });

  it("accepts only public quality release metadata", async () => {
    const release = {
      id: "release-1",
      release_version: "1.0.1",
      template_pack_version: "1.0.0",
      title: "约束保留改进",
      summary: "提高明确限制的保留率。",
      source_feedback_count: 2,
      published_at: "2026-07-15T13:00:00Z"
    };
    const invoke = vi.fn().mockResolvedValue(release);
    const bridge = createFeedbackBridge(hostWithInvoke(invoke));

    await expect(bridge.getQualityRelease()).resolves.toEqual(release);
    expect(invoke).toHaveBeenCalledWith("cloud_get_quality_release");
    expect(JSON.stringify(await bridge.getQualityRelease())).not.toContain("guidance");

    const absent = createFeedbackBridge(hostWithInvoke(vi.fn().mockResolvedValue(null)));
    await expect(absent.getQualityRelease()).resolves.toBeNull();
    const malformed = createFeedbackBridge(
      hostWithInvoke(vi.fn().mockResolvedValue({ release_version: "1.0.1" }))
    );
    await expect(malformed.getQualityRelease()).rejects.toThrow("质量发布信息暂不可用");
  });
});
