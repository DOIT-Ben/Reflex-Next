export type FeedbackPromptState = {
  version: 1;
  enabled: boolean;
  completedRuns: number;
  nextPromptAt: number;
  lastPromptedAtMs: number | null;
};

export type FeedbackPromptDecision = {
  state: FeedbackPromptState;
  shouldPrompt: boolean;
};

const FIRST_PROMPT_MIN = 3;
const FIRST_PROMPT_MAX = 5;
const REPEAT_PROMPT_MIN = 8;
const REPEAT_PROMPT_MAX = 12;
const SNOOZE_PROMPT_MIN = 3;
const SNOOZE_PROMPT_MAX = 5;
const PROMPT_COOLDOWN_MS = 3 * 24 * 60 * 60 * 1000;
const MAX_COUNTER = 1_000_000_000;

export function createFeedbackPromptState(
  random: () => number = Math.random
): FeedbackPromptState {
  return {
    version: 1,
    enabled: true,
    completedRuns: 0,
    nextPromptAt: randomInteger(FIRST_PROMPT_MIN, FIRST_PROMPT_MAX, random),
    lastPromptedAtMs: null
  };
}

export function normalizeFeedbackPromptState(
  value: unknown,
  random: () => number = Math.random
): FeedbackPromptState {
  if (!isRecord(value) || value.version !== 1 || typeof value.enabled !== "boolean") {
    return createFeedbackPromptState(random);
  }
  const completedRuns = boundedInteger(value.completedRuns);
  const nextPromptAt = boundedInteger(value.nextPromptAt);
  const lastPromptedAtMs = nullableTimestamp(value.lastPromptedAtMs);
  if (
    completedRuns === null ||
    nextPromptAt === null ||
    nextPromptAt < completedRuns ||
    lastPromptedAtMs === undefined
  ) {
    return createFeedbackPromptState(random);
  }
  return {
    version: 1,
    enabled: value.enabled,
    completedRuns,
    nextPromptAt,
    lastPromptedAtMs
  };
}

export function recordSuccessfulGeneration(
  current: FeedbackPromptState,
  nowMs: number = Date.now(),
  random: () => number = Math.random,
  promptAvailable = true
): FeedbackPromptDecision {
  const state = normalizeFeedbackPromptState(current, random);
  const completedRuns = Math.min(MAX_COUNTER, state.completedRuns + 1);
  const cooledDown =
    state.lastPromptedAtMs === null || nowMs - state.lastPromptedAtMs >= PROMPT_COOLDOWN_MS;
  const shouldPrompt =
    state.enabled && promptAvailable && completedRuns >= state.nextPromptAt && cooledDown;
  return {
    shouldPrompt,
    state: {
      ...state,
      completedRuns,
      nextPromptAt: shouldPrompt
        ? Math.min(
            MAX_COUNTER,
            completedRuns + randomInteger(REPEAT_PROMPT_MIN, REPEAT_PROMPT_MAX, random)
          )
        : state.nextPromptAt,
      lastPromptedAtMs: shouldPrompt ? Math.max(0, Math.floor(nowMs)) : state.lastPromptedAtMs
    }
  };
}

export function snoozeFeedbackPrompt(
  current: FeedbackPromptState,
  random: () => number = Math.random
): FeedbackPromptState {
  const state = normalizeFeedbackPromptState(current, random);
  return {
    ...state,
    nextPromptAt: Math.min(
      MAX_COUNTER,
      state.completedRuns + randomInteger(SNOOZE_PROMPT_MIN, SNOOZE_PROMPT_MAX, random)
    )
  };
}

export function disableFeedbackPrompt(current: FeedbackPromptState): FeedbackPromptState {
  return { ...current, enabled: false };
}

function randomInteger(minimum: number, maximum: number, random: () => number): number {
  const value = random();
  const normalized = Number.isFinite(value) ? Math.min(0.999999999, Math.max(0, value)) : 0;
  return minimum + Math.floor(normalized * (maximum - minimum + 1));
}

function boundedInteger(value: unknown): number | null {
  return Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= MAX_COUNTER
    ? (value as number)
    : null;
}

function nullableTimestamp(value: unknown): number | null | undefined {
  if (value === null) return null;
  return Number.isSafeInteger(value) && (value as number) >= 0 ? (value as number) : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
