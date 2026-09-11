import { get, writable, type Writable } from "svelte/store";
import type { AppConfig } from "./settingsApi";
import {
  completeActivation,
  createActivationState,
  normalizeActivationState,
  selectActivationRoute,
  type ActivationRoute,
  type ActivationState
} from "./activationState";

export type FirstRunFlowDeps = {
  persistConfigPatch: (build: (latest: AppConfig) => AppConfig) => Promise<AppConfig>;
  hasPersistedConfig: () => boolean;
  routeForProvider: (providerId: string) => ActivationRoute;
  currentProviderId: () => string;
};

export type FirstRunFlow = {
  state: Writable<ActivationState>;
  open: Writable<boolean>;
  notice: Writable<string>;
  hydrate: (config: AppConfig) => void;
  persist: (next: ActivationState) => Promise<boolean>;
  chooseRoute: (route: ActivationRoute, available: ActivationRoute[]) => Promise<boolean>;
  postpone: () => void;
  complete: () => Promise<boolean>;
  isCompleted: () => boolean;
};

const PERSIST_FAILURE_NOTICE = "首次使用状态暂未保存，本次仍可继续使用。";

export function createFirstRunFlow(deps: FirstRunFlowDeps): FirstRunFlow {
  const state = writable<ActivationState>(createActivationState());
  const open = writable(false);
  const notice = writable("");

  function hydrate(config: AppConfig) {
    const normalized = normalizeActivationState(config.first_run_activation);
    state.set(normalized);
    open.set(!normalized.completed);
  }

  async function persist(next: ActivationState): Promise<boolean> {
    const previous = get(state);
    state.set(next);
    if (!deps.hasPersistedConfig()) {
      state.set(previous);
      notice.set(PERSIST_FAILURE_NOTICE);
      return false;
    }
    try {
      const saved = await deps.persistConfigPatch((latest) => ({
        ...latest,
        first_run_activation: next
      }));
      state.set(normalizeActivationState(saved.first_run_activation));
      return true;
    } catch {
      state.set(previous);
      notice.set(PERSIST_FAILURE_NOTICE);
      return false;
    }
  }

  async function chooseRoute(route: ActivationRoute, available: ActivationRoute[]): Promise<boolean> {
    if (!available.includes(route)) return false;
    const next = selectActivationRoute(get(state), route);
    return persist(next);
  }

  function postpone() {
    open.set(false);
    notice.set("");
  }

  async function complete(): Promise<boolean> {
    if (get(state).completed) return false;
    const route = get(state).route ?? deps.routeForProvider(deps.currentProviderId());
    const completedState = completeActivation(selectActivationRoute(get(state), route));
    const persisted = await persist(completedState);
    if (persisted) {
      open.set(false);
      notice.set("");
    }
    return persisted;
  }

  function isCompleted(): boolean {
    return get(state).completed;
  }

  return { state, open, notice, hydrate, persist, chooseRoute, postpone, complete, isCompleted };
}
