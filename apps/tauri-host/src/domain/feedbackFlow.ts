import { get, writable, type Writable } from "svelte/store";
import type { AppConfig } from "./settingsApi";
import {
  createPromptFeedbackPayload,
  feedbackSubmitErrorMessage,
  type FeedbackBridge,
  type FeedbackContext,
  type FeedbackFormValue,
  type FeedbackScreenshot,
  type FeedbackSentiment
} from "./feedbackBridge";
import {
  createFeedbackPromptState,
  disableFeedbackPrompt,
  normalizeFeedbackPromptState,
  recordSuccessfulGeneration,
  snoozeFeedbackPrompt,
  type FeedbackPromptState
} from "./feedbackPrompt";

export type FeedbackFlowDeps = {
  feedbackBridge: () => FeedbackBridge | null;
  persistConfigPatch: (build: (latest: AppConfig) => AppConfig) => Promise<AppConfig>;
  hasPersistedConfig: () => boolean;
  settle: () => Promise<void>;
  appVersion: () => string;
  buildContext: () => FeedbackContext;
  promptText: () => string | null;
  resultText: () => string | null;
  consentVersion: () => string | null;
  updateConsent: (consent: Awaited<ReturnType<FeedbackBridge["getConsent"]>>) => void;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type FeedbackFlow = {
  open: Writable<boolean>;
  promptOpen: Writable<boolean>;
  promptBusy: Writable<boolean>;
  promptNotice: Writable<string | null>;
  promptState: Writable<FeedbackPromptState>;
  promptEnabledDraft: Writable<boolean>;
  source: Writable<"manual" | "prompt">;
  sentiment: Writable<FeedbackSentiment>;
  screenshot: Writable<FeedbackScreenshot | null>;
  captureNotice: Writable<string | null>;
  submitBusy: Writable<boolean>;
  submitNotice: Writable<string | null>;
  startDialog: (sentiment: FeedbackSentiment, source: "manual" | "prompt", capture: boolean) => Promise<void>;
  closeDialog: () => void;
  removeScreenshot: () => void;
  submit: (form: FeedbackFormValue) => Promise<void>;
  answerPrompt: (sentiment: FeedbackSentiment) => Promise<void>;
  postponePrompt: () => void;
  disablePrompt: () => void;
  hydratePromptState: (state: FeedbackPromptState) => void;
  recordCompletion: (promptAvailable: boolean) => Promise<void>;
};

const FEEDBACK_UNAVAILABLE_MESSAGE = "反馈服务暂不可用，请稍后重试。";

export function createFeedbackFlow(deps: FeedbackFlowDeps): FeedbackFlow {
  const open = writable(false);
  const promptOpen = writable(false);
  const promptBusy = writable(false);
  const promptNotice = writable<string | null>(null);
  const promptState = writable<FeedbackPromptState>(createFeedbackPromptState());
  const promptEnabledDraft = writable(createFeedbackPromptState().enabled);
  const source = writable<"manual" | "prompt">("manual");
  const sentiment = writable<FeedbackSentiment>("negative");
  const screenshot = writable<FeedbackScreenshot | null>(null);
  const captureNotice = writable<string | null>(null);
  const submitBusy = writable(false);
  const submitNotice = writable<string | null>(null);

  async function persistPrompt(next: FeedbackPromptState): Promise<boolean> {
    promptState.set(next);
    promptEnabledDraft.set(next.enabled);
    if (!deps.hasPersistedConfig()) return false;
    try {
      const saved = await deps.persistConfigPatch((latest) => ({
        ...latest,
        feedback_prompt: next
      }));
      promptState.set(normalizeFeedbackPromptState(saved.feedback_prompt));
      promptEnabledDraft.set(next.enabled);
      return true;
    } catch {
      // Keep the in-memory schedule for this session; a later settings save retries persistence.
      return false;
    }
  }

  async function startDialog(
    nextSentiment: FeedbackSentiment,
    nextSource: "manual" | "prompt",
    capture: boolean
  ) {
    sentiment.set(nextSentiment);
    source.set(nextSource);
    screenshot.set(null);
    captureNotice.set(null);
    submitNotice.set(null);
    await deps.settle();
    const bridge = deps.feedbackBridge();
    if (capture && bridge) {
      try {
        screenshot.set(await bridge.captureWindow());
      } catch {
        captureNotice.set("窗口截图失败，可以不附加截图继续反馈。");
      }
    } else if (capture) {
      captureNotice.set("当前环境无法截取应用窗口。");
    }
    open.set(true);
  }

  function closeDialog() {
    if (get(submitBusy)) return;
    open.set(false);
    screenshot.set(null);
    captureNotice.set(null);
    submitNotice.set(null);
    source.set("manual");
  }

  function removeScreenshot() {
    screenshot.set(null);
  }

  async function answerPrompt(nextSentiment: FeedbackSentiment) {
    const bridge = deps.feedbackBridge();
    if (get(promptBusy)) return;
    if (!bridge) {
      promptNotice.set(FEEDBACK_UNAVAILABLE_MESSAGE);
      return;
    }

    promptBusy.set(true);
    promptNotice.set(null);
    try {
      const latestConsent = await bridge.getConsent();
      deps.updateConsent(latestConsent);
      await bridge.submit(
        createPromptFeedbackPayload({
          sentiment: nextSentiment,
          context: deps.buildContext(),
          consentVersion: latestConsent.policy_version
        })
      );
      promptOpen.set(false);
      deps.showToast("反馈已记录，谢谢。", "success");
    } catch (error) {
      promptNotice.set(feedbackSubmitErrorMessage(error));
    } finally {
      promptBusy.set(false);
    }
  }

  function postponePrompt() {
    if (get(promptBusy)) return;
    promptOpen.set(false);
    promptNotice.set(null);
    void persistPrompt(snoozeFeedbackPrompt(get(promptState)));
  }

  function disablePrompt() {
    if (get(promptBusy)) return;
    promptOpen.set(false);
    promptNotice.set(null);
    void persistPrompt(disableFeedbackPrompt(get(promptState)));
    deps.showToast("已关闭主动反馈询问");
  }

  async function submit(form: FeedbackFormValue) {
    const bridge = deps.feedbackBridge();
    if (get(submitBusy) || !bridge) {
      submitNotice.set(FEEDBACK_UNAVAILABLE_MESSAGE);
      return;
    }
    submitBusy.set(true);
    submitNotice.set(null);
    try {
      const latestConsent = await bridge.getConsent();
      deps.updateConsent(latestConsent);
      await bridge.submit({
        source: get(source),
        sentiment: get(sentiment),
        category: form.category,
        message: form.message,
        expected_output: form.expectedOutput,
        contact: form.contact,
        context: deps.buildContext(),
        include_prompt: form.includePrompt,
        include_result: form.includeResult,
        include_screenshot: form.includeScreenshot && get(screenshot) !== null,
        prompt_text: form.includePrompt ? deps.promptText() : null,
        result_text: form.includeResult ? deps.resultText() : null,
        screenshot: form.includeScreenshot ? get(screenshot) : null,
        consent_version: latestConsent.policy_version
      });
      open.set(false);
      screenshot.set(null);
      source.set("manual");
      deps.showToast("反馈已发送，谢谢。", "success");
    } catch (error) {
      submitNotice.set(feedbackSubmitErrorMessage(error));
    } finally {
      submitBusy.set(false);
    }
  }

  async function recordCompletion(promptAvailable: boolean) {
    const decision = recordSuccessfulGeneration(
      get(promptState),
      Date.now(),
      Math.random,
      promptAvailable
    );
    const promptPersisted = await persistPrompt(decision.state);
    if (decision.shouldPrompt && promptPersisted) {
      promptNotice.set(null);
      promptOpen.set(true);
    }
  }

  function hydratePromptState(next: FeedbackPromptState) {
    promptState.set(next);
    promptEnabledDraft.set(next.enabled);
  }

  return {
    open,
    promptOpen,
    promptBusy,
    promptNotice,
    promptState,
    promptEnabledDraft,
    source,
    sentiment,
    screenshot,
    captureNotice,
    submitBusy,
    submitNotice,
    startDialog,
    closeDialog,
    removeScreenshot,
    submit,
    answerPrompt,
    postponePrompt,
    disablePrompt,
    hydratePromptState,
    recordCompletion
  };
}
