import { describe, expect, it } from "vitest";
import type { TauriEvent } from "./coreBridge";
import { createTauriHostApiFromModules } from "./tauriHostApi";

describe("tauri host api adapter", () => {
  it("maps Tauri invoke and listen modules into the bridge host shape", async () => {
    const calls: unknown[] = [];
    const unlisten = () => undefined;
    const api = createTauriHostApiFromModules({
      core: {
        invoke: async <T>(command: string, args?: Record<string, unknown>) => {
          calls.push({ command, args });
          return "ok" as T;
        }
      },
      event: {
        listen: async <T>(eventName: string, handler: (event: TauriEvent<T>) => void) => {
          calls.push({ eventName, handler });
          return unlisten;
        }
      }
    });

    await expect(api.invoke("runtime_ping", { command: { type: "ping" } })).resolves.toBe("ok");
    await expect(api.listen("reflex://core-event", () => undefined)).resolves.toBe(unlisten);
    expect(calls[0]).toEqual({
      command: "runtime_ping",
      args: { command: { type: "ping" } }
    });
    expect(calls[1]).toMatchObject({ eventName: "reflex://core-event" });
  });
});
