export const VIEW_SCALE_STEPS = [0.85, 0.9, 0.95, 1, 1.05, 1.1, 1.15] as const;

export type ViewScaleDirection = "in" | "out";
export type WindowSizePreset = "compact" | "default" | "wide";

export function stepViewScale(current: number, direction: ViewScaleDirection): number {
  const normalized = normalizeViewScale(current);
  const index = VIEW_SCALE_STEPS.indexOf(normalized as (typeof VIEW_SCALE_STEPS)[number]);
  const offset = direction === "in" ? 1 : -1;
  return VIEW_SCALE_STEPS[Math.min(VIEW_SCALE_STEPS.length - 1, Math.max(0, index + offset))];
}

export function normalizeViewScale(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return VIEW_SCALE_STEPS.reduce((closest, candidate) =>
    Math.abs(candidate - value) < Math.abs(closest - value) ? candidate : closest
  );
}

export function viewScaleLabel(value: number): string {
  return `${Math.round(normalizeViewScale(value) * 100)}%`;
}
