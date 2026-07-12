import { describe, expect, it } from "vitest";

import {
  batchCanExport,
  beginBatchParse,
  beginBatchRun,
  cancelBatch,
  completeBatchItem,
  completeBatchParse,
  createBatchState,
  finalizeBatchRun,
  runBatchWorkerPool,
  setBatchConcurrency,
  setBatchFormat,
  setBatchSourceText,
  startBatchItem
} from "./batchState";

describe("batch state", () => {
  it("accepts only a bounded, well-formed parser result and drops late events", () => {
    const opened = { ...createBatchState(), phase: "idle" as const };
    const started = beginBatchParse(setBatchSourceText(opened, "first\nsecond"));
    expect(started).not.toBeNull();
    const parsed = completeBatchParse(started!.state, started!.request, {
      items: [
        { id: 1, prompt: " first ", status: "pending" },
        { id: 2, prompt: "second", status: "pending" }
      ]
    });
    expect(parsed).toMatchObject({ phase: "ready", items: [{ prompt: "first" }, { prompt: "second" }] });
    expect(completeBatchParse(parsed, started!.request, { items: [{ id: 1, prompt: "late" }] })).toBe(parsed);
  });

  it("isolates item lifecycle, cancellation, and export readiness", () => {
    const parsed = completeBatchParse(
      beginBatchParse({ ...createBatchState(), phase: "idle", sourceText: "x" })!.state,
      1,
      { items: [{ id: 1, prompt: "x" }, { id: 2, prompt: "y" }] }
    );
    const started = beginBatchRun(parsed)!;
    let state = startBatchItem(started.state, started.request, 1);
    state = completeBatchItem(state, started.request, 1, " result \r\ntext ");
    expect(state.items[0]).toMatchObject({ status: "completed", result: "result\ntext" });
    expect(batchCanExport(state)).toBe(true);
    expect(completeBatchItem(state, started.request - 1, 2, "late")).toBe(state);
    expect(cancelBatch(state).items.map((item) => item.status)).toEqual(["completed", "cancelled"]);
  });

  it("clears parsed items before accepting a different source or format", () => {
    const ready = completeBatchParse(
      beginBatchParse({ ...createBatchState(), phase: "idle", sourceText: "first" })!.state,
      1,
      { items: [{ id: 1, prompt: "first" }] }
    );

    const changedSource = setBatchSourceText(ready, "second");
    expect(changedSource).toMatchObject({ phase: "idle", sourceText: "second", items: [] });

    const changedFormat = setBatchFormat(ready, "csv");
    expect(changedFormat).toMatchObject({ phase: "idle", format: "csv", items: [] });
  });

  it("runs no more than four workers and does not launch work after cancellation", async () => {
    let active = 0;
    let peak = 0;
    const controller = new AbortController();
    await runBatchWorkerPool([1, 2, 3, 4, 5, 6], setBatchConcurrency(createBatchState(), 99).concurrency, controller.signal, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await Promise.resolve();
      active -= 1;
    });
    expect(peak).toBeLessThanOrEqual(4);

    const started: number[] = [];
    controller.abort();
    await runBatchWorkerPool([1, 2], 2, controller.signal, async (item) => {
      started.push(item);
    });
    expect(started).toEqual([]);
  });

  it("finishes only the active batch run", () => {
    const state = { ...createBatchState(), phase: "running" as const, request: 4 };
    expect(finalizeBatchRun(state, 3)).toBe(state);
    expect(finalizeBatchRun(state, 4).phase).toBe("completed");
  });
});
