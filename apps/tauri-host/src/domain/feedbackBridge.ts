import type { TauriHostApi } from "./coreBridge";

export type FeedbackSentiment = "positive" | "negative";
export type FeedbackCategory = "quality" | "bug" | "performance" | "feature" | "other";

export type FeedbackScreenshot = {
  media_type: "image/png";
  data_base64: string;
};

export type FeedbackContext = {
  app_version: string;
  os_version: string;
  provider: string;
  model: string;
  mode: string;
  style: string;
  scene: string;
  request_id: string;
  diagnostic_id: string;
  error_code: string;
  elapsed_ms: number | null;
};

export type FeedbackPayload = {
  sentiment: FeedbackSentiment;
  category: FeedbackCategory;
  message: string;
  expected_output: string;
  contact: string;
  context: FeedbackContext;
  include_prompt: boolean;
  include_result: boolean;
  include_screenshot: boolean;
  prompt_text: string | null;
  result_text: string | null;
  screenshot: FeedbackScreenshot | null;
  consent_version: "2026-07-14";
};

export type FeedbackSubmitted = {
  id: string;
  status: string;
};

export type FeedbackFormValue = {
  category: FeedbackCategory;
  message: string;
  expectedOutput: string;
  contact: string;
  includePrompt: boolean;
  includeResult: boolean;
  includeScreenshot: boolean;
};

export type FeedbackBridge = {
  captureWindow(): Promise<FeedbackScreenshot>;
  submit(payload: FeedbackPayload): Promise<FeedbackSubmitted>;
};

export function createFeedbackBridge(host: TauriHostApi): FeedbackBridge {
  return {
    async captureWindow() {
      return normalizeScreenshot(await host.invoke("capture_feedback_screenshot"));
    },
    async submit(payload) {
      return normalizeSubmitted(await host.invoke("submit_feedback", { payload }));
    }
  };
}

function normalizeScreenshot(value: unknown): FeedbackScreenshot {
  const raw = isRecord(value) ? value : {};
  if (raw.media_type !== "image/png" || typeof raw.data_base64 !== "string" || !raw.data_base64) {
    throw new Error("反馈截图暂不可用。");
  }
  return { media_type: "image/png", data_base64: raw.data_base64 };
}

function normalizeSubmitted(value: unknown): FeedbackSubmitted {
  const raw = isRecord(value) ? value : {};
  if (typeof raw.id !== "string" || !raw.id || typeof raw.status !== "string") {
    throw new Error("反馈服务返回了无效结果。");
  }
  return { id: raw.id, status: raw.status };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
