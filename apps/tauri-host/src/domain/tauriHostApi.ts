import type { TauriEvent, TauriHostApi } from "./coreBridge";

type InvokeFunction = <T = unknown>(
  command: string,
  args?: Record<string, unknown>
) => Promise<T>;

type ListenFunction = <T>(
  eventName: string,
  handler: (event: TauriEvent<T>) => void
) => Promise<() => void>;

export type TauriApiModules = {
  core: {
    invoke: InvokeFunction;
  };
  event: {
    listen: ListenFunction;
  };
};

export function createTauriHostApiFromModules(modules: TauriApiModules): TauriHostApi {
  return {
    invoke: modules.core.invoke,
    listen: modules.event.listen
  };
}

export async function createTauriHostApi(): Promise<TauriHostApi | null> {
  try {
    const [core, event] = await Promise.all([
      import("@tauri-apps/api/core"),
      import("@tauri-apps/api/event")
    ]);
    if (!core.isTauri()) {
      return null;
    }
    return createTauriHostApiFromModules({
      core: { invoke: core.invoke },
      event: { listen: event.listen }
    });
  } catch {
    return null;
  }
}
