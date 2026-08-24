import { describe, expect, it } from "vitest";

import {
  createFeedbackPromptState,
  disableFeedbackPrompt,
  normalizeFeedbackPromptState,
  recordSuccessfulGeneration,
  snoozeFeedbackPrompt
} from "./feedbackPrompt";

const DAY_MS = 24 * 60 * 60 * 1000;

describe("feedback prompt scheduler", () => {
  it("asks only after a randomized first-use threshold", () => {
    let state = createFeedbackPromptState(() => 0);
    expect(state.nextPromptAt).toBe(3);

    for (let count = 1; count <= 2; count += 1) {
      const recorded = recordSuccessfulGeneration(state, count * 1_000, () => 0);
      state = recorded.state;
      expect(recorded.shouldPrompt).toBe(false);
    }

    const due = recordSuccessfulGeneration(state, 3_000, () => 0);
    expect(due.shouldPrompt).toBe(true);
    expect(due.state.completedRuns).toBe(3);
    expect(due.state.nextPromptAt).toBe(11);
    expect(due.state.lastPromptedAtMs).toBe(3_000);
  });

  it("enforces a hard cooldown even when the run threshold is reached", () => {
    let state = {
      ...createFeedbackPromptState(() => 0),
      completedRuns: 10,
      nextPromptAt: 11,
      lastPromptedAtMs: DAY_MS
    };

    const tooSoon = recordSuccessfulGeneration(state, 2 * DAY_MS, () => 0);
    expect(tooSoon.shouldPrompt).toBe(false);
    expect(tooSoon.state.completedRuns).toBe(11);

    state = tooSoon.state;
    const cooledDown = recordSuccessfulGeneration(state, 4 * DAY_MS, () => 0);
    expect(cooledDown.shouldPrompt).toBe(true);
    expect(cooledDown.state.nextPromptAt).toBe(20);
  });

  it("counts a completed run without consuming a due prompt when another overlay is active", () => {
    const due = {
      ...createFeedbackPromptState(() => 0),
      completedRuns: 2,
      nextPromptAt: 3
    };

    const blocked = recordSuccessfulGeneration(due, 3_000, () => 0, false);
    expect(blocked.shouldPrompt).toBe(false);
    expect(blocked.state).toMatchObject({
      completedRuns: 3,
      nextPromptAt: 3,
      lastPromptedAtMs: null
    });

    const available = recordSuccessfulGeneration(blocked.state, 4_000, () => 0, true);
    expect(available.shouldPrompt).toBe(true);
    expect(available.state).toMatchObject({
      completedRuns: 4,
      nextPromptAt: 12,
      lastPromptedAtMs: 4_000
    });
  });

  it("snoozes for a shorter random interval and can be permanently disabled", () => {
    const due = {
      ...createFeedbackPromptState(() => 0),
      completedRuns: 5,
      nextPromptAt: 13,
      lastPromptedAtMs: 10_000
    };

    const snoozed = snoozeFeedbackPrompt(due, () => 0.999999);
    expect(snoozed.nextPromptAt).toBe(10);

    const disabled = disableFeedbackPrompt(snoozed);
    expect(disabled.enabled).toBe(false);
    const recorded = recordSuccessfulGeneration(disabled, 20_000, () => 0);
    expect(recorded.shouldPrompt).toBe(false);
    expect(recorded.state.enabled).toBe(false);
  });

  it("normalizes persisted state without accepting unbounded or malformed values", () => {
    expect(
      normalizeFeedbackPromptState(
        {
          version: 1,
          enabled: false,
          completedRuns: 42,
          nextPromptAt: 50,
          lastPromptedAtMs: 123_456
        },
        () => 0
      )
    ).toEqual({
      version: 1,
      enabled: false,
      completedRuns: 42,
      nextPromptAt: 50,
      lastPromptedAtMs: 123_456
    });

    expect(
      normalizeFeedbackPromptState(
        {
          version: 999,
          enabled: "yes",
          completedRuns: Number.MAX_SAFE_INTEGER,
          nextPromptAt: -1,
          lastPromptedAtMs: "yesterday"
        },
        () => 0
      )
    ).toEqual(createFeedbackPromptState(() => 0));
  });
});
