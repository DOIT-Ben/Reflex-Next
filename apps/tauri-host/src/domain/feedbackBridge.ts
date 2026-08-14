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
  source: "manual" | "prompt";
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

export function createPromptFeedbackPayload(input: {
  sentiment: FeedbackSentiment;
  context: FeedbackContext;
  consentVersion: string;
}): FeedbackPayload {
  return {
    source: "prompt",
    sentiment: input.sentiment,
    category: "quality",
    message: "",
    expected_output: "",
    contact: "",
    context: input.context,
    include_prompt: false,
    include_result: false,
    include_screenshot: false,
    prompt_text: null,
    result_text: null,
    screenshot: null,
    consent_version: input.consentVersion
  };
}

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

export type CloudQualityRelease = {
  id: string;
  release_version: string;
  template_pack_version: string;
  title: string;
  summary: string;
  source_feedback_count: number;
  published_at: string;
};

export type FeedbackBridge = {
  captureWindow(): Promise<FeedbackScreenshot>;
  submit(payload: FeedbackPayload): Promise<FeedbackSubmitted>;
  getConsent(): Promise<CloudConsent>;
  updateConsent(consent: CloudConsent): Promise<CloudConsent>;
  getQuota(): Promise<CloudQuota>;
  getQualityRelease(): Promise<CloudQualityRelease | null>;
  deleteCloudData(): Promise<boolean>;
};

const SAFE_FEEDBACK_SUBMIT_MESSAGES = new Set([
  "反馈发送失败，请稍后重试。",
  "反馈服务暂不可用，请稍后重试。",
  "反馈服务返回了无效结果。",
  "请先在设置中开启对应的隐私授权。",
  "隐私授权已更新，请刷新设置后重新提交。",
  "反馈提交过于频繁，请稍后再试。",
  "反馈内容不完整，请检查后重试。",
  "反馈附件暂时无法保存，请稍后再试。",
  "云端服务暂不可用，请稍后重试。",
  "云端隐私设置暂不可用。"
]);

export function createFeedbackBridge(host: TauriHostApi): FeedbackBridge {
  return {
    async captureWindow() {
      return normalizeScreenshot(await host.invoke("capture_feedback_screenshot"));
    },
    async submit(payload) {
      try {
        return normalizeSubmitted(await host.invoke("submit_feedback", { payload }));
      } catch (error) {
        throw new Error(feedbackSubmitErrorMessage(error));
      }
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
    async getQualityRelease() {
      return normalizeQualityRelease(await host.invoke("cloud_get_quality_release"));
    },
    async deleteCloudData() {
      return (await host.invoke("cloud_delete_data")) === true;
    }
  };
}

export function feedbackSubmitErrorMessage(error: unknown): string {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : isRecord(error) && typeof error.message === "string"
          ? error.message
          : "";
  return SAFE_FEEDBACK_SUBMIT_MESSAGES.has(message)
    ? message
    : "反馈发送失败，请稍后重试。";
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

function normalizeQualityRelease(value: unknown): CloudQualityRelease | null {
  if (value === null) return null;
  const raw = isRecord(value) ? value : {};
  if (
    typeof raw.id !== "string" ||
    !raw.id ||
    typeof raw.release_version !== "string" ||
    !raw.release_version ||
    typeof raw.template_pack_version !== "string" ||
    !raw.template_pack_version ||
    typeof raw.title !== "string" ||
    !raw.title ||
    typeof raw.summary !== "string" ||
    typeof raw.published_at !== "string" ||
    !raw.published_at ||
    !Number.isSafeInteger(raw.source_feedback_count) ||
    (raw.source_feedback_count as number) < 0
  ) {
    throw new Error("质量发布信息暂不可用。");
  }
  return {
    id: raw.id,
    release_version: raw.release_version,
    template_pack_version: raw.template_pack_version,
    title: raw.title,
    summary: raw.summary,
    source_feedback_count: raw.source_feedback_count as number,
    published_at: raw.published_at
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
