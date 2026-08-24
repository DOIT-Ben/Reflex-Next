import type { ProviderAvailability } from "./providerCatalog";

export type ActivationRoute = "cloud" | "byok";

export type ActivationState = {
  version: 1;
  completed: boolean;
  route: ActivationRoute | null;
};

const allowedKeys = new Set(["version", "completed", "route"]);

export function createActivationState(): ActivationState {
  return { version: 1, completed: false, route: null };
}

export function normalizeActivationState(value: unknown): ActivationState {
  if (!isRecord(value) || Object.keys(value).some((key) => !allowedKeys.has(key))) {
    return createActivationState();
  }
  if (value.version !== 1 || typeof value.completed !== "boolean") {
    return createActivationState();
  }
  if (value.route !== null && value.route !== "cloud" && value.route !== "byok") {
    return createActivationState();
  }
  if (value.completed && value.route === null) {
    return createActivationState();
  }
  return { version: 1, completed: value.completed, route: value.route };
}

export function availableActivationRoutes(availability: ProviderAvailability): ActivationRoute[] {
  return availability === "ready" ? ["cloud", "byok"] : ["byok"];
}

export function activationRouteForProvider(providerId: string | null | undefined): ActivationRoute {
  return providerId?.trim().toLowerCase() === "reflex-cloud" ? "cloud" : "byok";
}

export function selectActivationRoute(
  current: ActivationState,
  route: ActivationRoute
): ActivationState {
  return { ...normalizeActivationState(current), route, completed: false };
}

export function completeActivation(current: ActivationState): ActivationState {
  const state = normalizeActivationState(current);
  return state.route === null ? state : { ...state, completed: true };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
