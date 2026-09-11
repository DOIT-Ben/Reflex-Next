import { writable, type Writable } from "svelte/store";
import { normalizeViewScale, stepViewScale } from "./viewControls";

const STORAGE_KEY = "reflex-view-scale";

export type ViewScaleStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export type ViewScaleStore = Writable<number> & {
  step: (direction: "in" | "out") => void;
  reset: () => void;
};

export function createViewScaleStore(storage: ViewScaleStorage | null): ViewScaleStore {
  const scale = writable<number>(readStoredScale(storage));

  function set(next: number) {
    const normalized = normalizeViewScale(next);
    scale.set(normalized);
    if (!storage) return;
    try {
      storage.setItem(STORAGE_KEY, String(normalized));
    } catch {
      // The view remains usable when browser storage is unavailable.
    }
  }

  return {
    subscribe: scale.subscribe,
    set,
    update: scale.update,
    step: (direction) => set(stepViewScale(readCurrent(scale), direction)),
    reset: () => set(1)
  };
}

function readStoredScale(storage: ViewScaleStorage | null): number {
  if (!storage) return 1;
  try {
    return normalizeViewScale(Number(storage.getItem(STORAGE_KEY) ?? 1));
  } catch {
    return 1;
  }
}

function readCurrent(scale: Writable<number>): number {
  let value = 1;
  scale.subscribe((current) => (value = current))();
  return value;
}
