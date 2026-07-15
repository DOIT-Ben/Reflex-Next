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
  consent_version: string;
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

export type CloudConsent = {
  usage_metrics: boolean;
  improvement_data: boolean;
  feedback_attachments: boolean;
  policy_version: string;
  updated_at: string | null;
};

export type CloudQuota = {
  usage_date: string;
  requests_used: number;
  requests_limit: number;
  input_chars_used: number;
  input_chars_limit: number;
  output_chars_used: number;
  output_chars_limit: number;
};

export type FeedbackBridge = {
  captureWindow(): Promise<FeedbackScreenshot>;
  submit(payload: FeedbackPayload): Promise<FeedbackSubmitted>;
  getConsent(): Promise<CloudConsent>;
  updateConsent(consent: CloudConsent): Promise<CloudConsent>;
  getQuota(): Promise<CloudQuota>;
  deleteCloudData(): Promise<boolean>;
};

export function createFeedbackBridge(host: TauriHostApi): FeedbackBridge {
  return {
    async captureWindow() {
      return normalizeScreenshot(await host.invoke("capture_feedback_screenshot"));
    },
    async submit(payload) {
      return normalizeSubmitted(await host.invoke("submit_feedback", { payload }));
    },
    async getConsent() {
      return normalizeConsent(await host.invoke("cloud_get_consent"));
    },
    async updateConsent(consent) {
      return normalizeConsent(await host.invoke("cloud_update_consent", { consent }));
    },
    async getQuota() {
      return normalizeQuota(await host.invoke("cloud_get_quota"));
    },
    async deleteCloudData() {
      return (await host.invoke("cloud_delete_data")) === true;
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

function normalizeConsent(value: unknown): CloudConsent {
  const raw = isRecord(value) ? value : {};
  if (
    typeof raw.usage_metrics !== "boolean" ||
    typeof raw.improvement_data !== "boolean" ||
    typeof raw.feedback_attachments !== "boolean" ||
    typeof raw.policy_version !== "string" ||
    !raw.policy_version
  ) {
    throw new Error("云端隐私设置暂不可用。");
  }
  return {
    usage_metrics: raw.usage_metrics,
    improvement_data: raw.improvement_data,
    feedback_attachments: raw.feedback_attachments,
    policy_version: raw.policy_version,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null
  };
}

function normalizeQuota(value: unknown): CloudQuota {
  const raw = isRecord(value) ? value : {};
  const fields = [
    "requests_used",
    "requests_limit",
    "input_chars_used",
    "input_chars_limit",
    "output_chars_used",
    "output_chars_limit"
  ] as const;
  if (
    typeof raw.usage_date !== "string" ||
    fields.some((field) => !Number.isSafeInteger(raw[field]) || (raw[field] as number) < 0)
  ) {
    throw new Error("云端额度暂不可用。");
  }
  return {
    usage_date: raw.usage_date,
    requests_used: raw.requests_used as number,
    requests_limit: raw.requests_limit as number,
    input_chars_used: raw.input_chars_used as number,
    input_chars_limit: raw.input_chars_limit as number,
    output_chars_used: raw.output_chars_used as number,
    output_chars_limit: raw.output_chars_limit as number
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
