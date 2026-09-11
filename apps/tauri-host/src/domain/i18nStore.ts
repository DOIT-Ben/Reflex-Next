import { writable } from "svelte/store";
import { translate, type UiLanguage } from "./i18n";

export type TranslateFn = (source: string, values?: Record<string, string | number>) => string;

const identity: TranslateFn = (source) => source;

export const translator = writable<TranslateFn>(identity);

export function setTranslator(fn: TranslateFn): void {
  translator.set(fn);
}

export function setUiLanguage(language: UiLanguage): void {
  translator.set((source, values = {}) => translate(language, source, values));
}
