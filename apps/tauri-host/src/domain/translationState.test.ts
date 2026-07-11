import { describe, expect, it } from "vitest";

import {
  appendTranslationChunk,
  buildTranslationInput,
  cancelTranslation,
  closeTranslation,
  completeTranslation,
  createTranslationState,
  failTranslation,
  openTranslation,
  selectTranslationTarget,
  startTranslation,
  translationErrorMessage
} from "./translationState";

describe("translation state", () => {
  it("opens with the current result and starts an isolated request", () => {
    const opened = openTranslation(createTranslationState(), "  source result  ");
    const started = startTranslation(opened);

    expect(opened).toMatchObject({
      phase: "idle",
      sourceText: "source result",
      translatedText: "",
      target: "auto"
    });
    expect(started.request).toBe(1);
    expect(started.state).toMatchObject({ phase: "streaming", request: 1 });
  });

  it("keeps only supported segmented targets and clears an old translation", () => {
    const completed = {
      ...openTranslation(createTranslationState(), "source"),
      phase: "completed" as const,
      translatedText: "old"
    };

    expect(selectTranslationTarget(completed, "zh")).toMatchObject({
      phase: "idle",
      target: "zh",
      translatedText: ""
    });
    expect(selectTranslationTarget(completed, "fr")).toBe(completed);
  });

  it("appends sanitized chunks and ignores late request events", () => {
    const first = startTranslation(openTranslation(createTranslationState(), "source"));
    const second = startTranslation(first.state);
    const current = appendTranslationChunk(second.state, second.request, "A\x00\r\nB");

    expect(current.translatedText).toBe("A\nB");
    expect(appendTranslationChunk(current, first.request, "late")).toBe(current);
  });

  it("accepts only a complete translation result for the current request", () => {
    const started = startTranslation(openTranslation(createTranslationState(), "source"));
    const completed = completeTranslation(started.state, started.request, {
      text: " translated ",
      source_language: "en",
      target_language: "zh"
    });

    expect(completed).toMatchObject({
      phase: "completed",
      translatedText: "translated",
      sourceLanguage: "en",
      targetLanguage: "zh",
      error: null
    });
    expect(
      completeTranslation(completed, started.request, {
        text: "",
        source_language: "en",
        target_language: "zh"
      }).phase
    ).toBe("error");
  });

  it("represents current cancellation and failure without accepting stale terminals", () => {
    const started = startTranslation(openTranslation(createTranslationState(), "source"));

    expect(cancelTranslation(started.state, started.request).phase).toBe("cancelled");
    expect(failTranslation(started.state, started.request, "fixed")).toMatchObject({
      phase: "error",
      error: "fixed"
    });
    expect(failTranslation(started.state, started.request - 1, "late")).toBe(started.state);
  });

  it("closing invalidates the active sequence and clears result bodies", () => {
    const started = startTranslation(openTranslation(createTranslationState(), "source"));
    const closed = closeTranslation(
      appendTranslationChunk(started.state, started.request, "partial")
    );

    expect(closed).toMatchObject({
      phase: "closed",
      request: 2,
      sourceText: "",
      translatedText: ""
    });
  });

  it("builds a provider-routed public input without secrets", () => {
    const opened = selectTranslationTarget(
      openTranslation(createTranslationState(), "source"),
      "en"
    );

    expect(
      buildTranslationInput(
        opened,
        { provider: "minimax", model: "model-a" },
        { provider: "fallback", model: "model-b" }
      )
    ).toEqual({
      text: "source",
      target: "en",
      provider: "minimax",
      model: "model-a"
    });
    expect(Object.keys(buildTranslationInput(opened, {}, {}) ?? {})).not.toContain("secret");
  });

  it("maps provider and plugin failures to fixed user-facing messages", () => {
    expect(translationErrorMessage("provider_unconfigured")).toContain("设置");
    expect(translationErrorMessage("provider_auth_failed")).toContain("API Key");
    expect(translationErrorMessage("plugin_disabled")).toContain("启用");
    expect(translationErrorMessage("unknown_private_detail")).toBe("翻译暂时不可用，请重试。");
  });
});
