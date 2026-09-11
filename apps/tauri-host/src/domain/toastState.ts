import { writable, type Writable } from "svelte/store";
import type { TranslateFn } from "./i18nStore";

export type ToastTone = "success" | "error";

export type ToastState = {
  visible: boolean;
  message: string;
  tone: ToastTone;
};

export type ToastScheduler = {
  schedule: (callback: () => void, delayMs: number) => number;
  cancel: (handle: number) => void;
};

export const TOAST_DURATION_MS = 1400;

const ERROR_TONE_PATTERN = /失败|不可用|未保存|错误/;

export function inferToastTone(message: string): ToastTone {
  return ERROR_TONE_PATTERN.test(message) ? "error" : "success";
}

export type ToastController = {
  state: Writable<ToastState>;
  show: (message: string, tone?: ToastTone) => void;
};

export function createToastController(options: {
  translate?: TranslateFn;
  scheduler?: ToastScheduler;
} = {}): ToastController {
  const translate = options.translate ?? ((source: string) => source);
  const scheduler = options.scheduler ?? {
    schedule: (callback, delayMs) => window.setTimeout(callback, delayMs),
    cancel: (handle) => window.clearTimeout(handle)
  };

  const state = writable<ToastState>({ visible: false, message: "", tone: "success" });
  let timeoutHandle: number | null = null;

  function hide() {
    state.update((current) => ({ ...current, visible: false }));
    timeoutHandle = null;
  }

  function show(message: string, tone?: ToastTone) {
    if (timeoutHandle !== null) scheduler.cancel(timeoutHandle);
    state.set({
      visible: true,
      message: translate(message),
      tone: tone ?? inferToastTone(message)
    });
    timeoutHandle = scheduler.schedule(hide, TOAST_DURATION_MS);
  }

  return { state, show };
}
