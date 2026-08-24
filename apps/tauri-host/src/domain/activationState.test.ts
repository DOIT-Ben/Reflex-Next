import { describe, expect, it } from "vitest";

import {
  availableActivationRoutes,
  completeActivation,
  createActivationState,
  normalizeActivationState,
  activationRouteForProvider,
  selectActivationRoute
} from "./activationState";

describe("first-run activation state", () => {
  it("only offers the Cloud trial after a real ready probe", () => {
    expect(availableActivationRoutes("checking")).toEqual(["byok"]);
    expect(availableActivationRoutes("unavailable")).toEqual(["byok"]);
    expect(availableActivationRoutes("ready")).toEqual(["cloud", "byok"]);
  });

  it("persists only a bounded route choice and completion marker", () => {
    const selected = selectActivationRoute(createActivationState(), "byok");
    const completed = completeActivation(selected);

    expect(completed).toEqual({ version: 1, completed: true, route: "byok" });
    expect(JSON.stringify(completed)).not.toMatch(/key|token|secret|endpoint/i);
  });

  it("rejects malformed or credential-bearing persisted values", () => {
    expect(
      normalizeActivationState({
        version: 1,
        completed: true,
        route: "cloud",
        api_key: "must-not-survive"
      })
    ).toEqual(createActivationState());

    expect(normalizeActivationState({ version: 2, completed: "yes", route: "other" })).toEqual(
      createActivationState()
    );
  });

  it("derives the completed access route from the provider actually used", () => {
    expect(activationRouteForProvider("reflex-cloud")).toBe("cloud");
    expect(activationRouteForProvider("minimax")).toBe("byok");
  });
});
