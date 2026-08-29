import type { TauriEvent, TauriHostApi } from "./coreBridge";

export type TauriHostStubOptions = {
  invoke?: (command: string, args?: Record<string, unknown>) => unknown | Promise<unknown>;
  listen?: (
    eventName: string,
    handler: (event: TauriEvent<unknown>) => void
  ) => (() => void) | Promise<() => void>;
};

export function createTauriHostStub(
  options: TauriHostStubOptions = {}
): TauriHostApi {
  return {
    invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
      const result =
        args === undefined
          ? options.invoke?.(command)
          : options.invoke?.(command, args);
      return Promise.resolve(result) as Promise<T>;
    },
    listen<T>(
      eventName: string,
      handler: (event: TauriEvent<T>) => void
    ): Promise<() => void> {
      const result = options.listen?.(eventName, (event) => handler(event as TauriEvent<T>));
      return Promise.resolve(result ?? (() => {}));
    }
  };
}
