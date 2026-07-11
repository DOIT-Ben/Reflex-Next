import { describe, expect, it } from "vitest";

import { appendHistoryPage, applyHistoryDetailFailure, applyHistoryDetailTerminal, applyHistoryRatingToDetail, createHistoryBackupsState, createHistoryState, failHistoryBackupsLoad, failHistoryQuery, finishHistoryBackupsLoad, finishHistoryOperation, historyElapsedLabel, historyExportFilters, historyScanMessage, normalizeHistoryBackups, removeHistoryItem, selectHistoryItem, setHistoryDetail, startHistoryBackupsLoad, startHistoryOperation, startHistoryQuery, updateHistoryRating } from "./historyState";

describe("history state", () => {
  it("resets the cursor and ignores an old response after filters change", () => {
    const initial = createHistoryState();
    const first = startHistoryQuery(initial, { search: "old" });
    const changed = startHistoryQuery(first.state, { search: "new" });
    const stale = appendHistoryPage(changed.state, first.request, {
      items: [{ id: "old", created_at: "2026-07-11", scene: "general", style: "balanced", provider: "minimax", rating: null }],
      next_cursor: "old-cursor"
    });

    expect(changed.state.cursor).toBeNull();
    expect(stale).toBe(changed.state);
  });

  it("deduplicates later pages by history id", () => {
    const started = startHistoryQuery(createHistoryState(), {});
    const first = appendHistoryPage(started.state, started.request, {
      items: [{ id: "one", created_at: "2026-07-11", scene: "general", style: "balanced", provider: "minimax", rating: 4 }],
      next_cursor: "next"
    });
    const next = appendHistoryPage({ ...first, phase: "loading-more" }, started.request, {
      items: [
        { id: "one", created_at: "2026-07-11", scene: "general", style: "balanced", provider: "minimax", rating: 4 },
        { id: "two", created_at: "2026-07-10", scene: "email", style: "concise", provider: "minimax", rating: null }
      ],
      next_cursor: null
    });

    expect(next.items.map((item) => item.id)).toEqual(["one", "two"]);
    expect(next.phase).toBe("ready");
  });

  it("represents loading, empty, ready and error list states", () => {
    const started = startHistoryQuery(createHistoryState(), {});
    expect(started.state.phase).toBe("loading");
    expect(appendHistoryPage(started.state, started.request, { items: [], next_cursor: null }).phase).toBe("empty");
    expect(failHistoryQuery(started.state, started.request, "固定错误").phase).toBe("error");
  });

  it("does not let a late detail replace a newer selection", () => {
    const base = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [
      { id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null },
      { id: "two", created_at: "b", scene: "email", style: "concise", provider: "minimax", rating: null }
    ], next_cursor: null });
    const one = selectHistoryItem(base, "one");
    const two = selectHistoryItem(one, "two");
    expect(setHistoryDetail(two, one.detailRequest, { id: "one" })).toBe(two);
  });

  it("updates a rating locally", () => {
    const state = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [{ id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null }], next_cursor: null });
    expect(updateHistoryRating(state, "one", 5).items[0].rating).toBe(5);
  });

  it("selects an adjacent item after deleting the selected one", () => {
    const state = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [
      { id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null },
      { id: "two", created_at: "b", scene: "general", style: "balanced", provider: "minimax", rating: null }
    ], next_cursor: null });
    expect(removeHistoryItem(selectHistoryItem(state, "one"), "one").selectedId).toBe("two");
  });

  it("tracks admin and export operation outcomes", () => {
    const running = startHistoryOperation(createHistoryState(), "export");
    expect(running.operation.phase).toBe("running");
    expect(finishHistoryOperation(running.state, "succeeded").operation.phase).toBe("succeeded");
    expect(finishHistoryOperation(running.state, "recovery").operation.phase).toBe("recovery");
    expect(finishHistoryOperation(running.state, "failed").operation.phase).toBe("failed");
  });

  it("clears selection when an unknown id is selected", () => {
    expect(selectHistoryItem(createHistoryState(), "missing").selectedId).toBeNull();
  });

  it("removing the last record enters empty state", () => {
    const state = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [{ id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null }], next_cursor: null });
    expect(removeHistoryItem(state, "one").phase).toBe("empty");
  });

  it("drops blank filter values when a query starts", () => {
    expect(startHistoryQuery(createHistoryState(), { search: "  ", scene: "general" }).state.query).toEqual({ scene: "general" });
  });

  it("keeps a stale failure from replacing the current query", () => {
    const first = startHistoryQuery(createHistoryState(), { search: "old" });
    const current = startHistoryQuery(first.state, { search: "new" });
    expect(failHistoryQuery(current.state, first.request, "固定错误")).toBe(current.state);
  });

  it("exports only supported metadata filters and rejects active text search", () => {
    expect(historyExportFilters({ scene: "email", style: "concise", provider: "minimax" })).toEqual({ scene: "email", style: "concise", provider: "minimax" });
    expect(historyExportFilters({ search: "private phrase", scene: "email" })).toBeNull();
  });

  it("accepts only safe backup summaries from the plugin result", () => {
    expect(normalizeHistoryBackups({ items: [
      { id: "backup-20260711-abc", created_at: "2026-07-11T12:00:00Z", record_count: 12 },
      { id: "../outside", created_at: "2026-07-11T12:00:00Z", record_count: 99 },
      { id: "backup-missing-date", record_count: 1 }
    ] })).toEqual([
      { id: "backup-20260711-abc", created_at: "2026-07-11T12:00:00Z", record_count: 12 }
    ]);
  });

  it("uses the encrypted history elapsed field for the visible duration", () => {
    expect(historyElapsedLabel({ elapsed_ms: 1250 })).toBe("1250 ms");
    expect(historyElapsedLabel({ duration_ms: 1250 })).toBe("-");
  });

  it("uses the plugin scan contract and never hides corrupted records", () => {
    expect(historyScanMessage({ corrupted_records: 2 })).toBe("发现 2 条需要修复的记录。");
    expect(historyScanMessage({ corrupted_records: 0 })).toBe("历史记录检查完成，未发现问题。");
    expect(historyScanMessage({ corrupted: 9 })).toBe("历史记录检查结果暂时不可用。");
  });

  it("does not apply a late rating response to a newly selected detail", () => {
    const listed = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [
      { id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null },
      { id: "two", created_at: "b", scene: "email", style: "concise", provider: "other", rating: null }
    ], next_cursor: null });
    const one = selectHistoryItem(listed, "one");
    const oneRequest = one.detailRequest;
    const two = selectHistoryItem(one, "two");
    const twoDetail = { id: "two", rating: null };

    expect(applyHistoryRatingToDetail(two, twoDetail, "one", oneRequest, 5)).toBe(twoDetail);
    expect(applyHistoryRatingToDetail(one, { id: "one", rating: null }, "one", oneRequest, 5)).toEqual({ id: "one", rating: 5 });
  });

  it("does not let an old detail failure replace a newer detail", () => {
    const listed = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [
      { id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null },
      { id: "two", created_at: "b", scene: "email", style: "concise", provider: "other", rating: null }
    ], next_cursor: null });
    const one = selectHistoryItem(listed, "one");
    const two = selectHistoryItem(one, "two");
    const twoDetail = { id: "two", output: "current" };

    expect(applyHistoryDetailFailure(two, twoDetail, "one", one.detailRequest)).toBe(twoDetail);
    expect(applyHistoryDetailFailure(one, null, "one", one.detailRequest)).toEqual({ error: "无法加载这条历史记录。" });
  });

  it("turns terminal detail errors into a visible failure state", () => {
    const listed = appendHistoryPage(startHistoryQuery(createHistoryState(), {}).state, 1, { items: [
      { id: "one", created_at: "a", scene: "general", style: "balanced", provider: "minimax", rating: null }
    ], next_cursor: null });
    const selected = selectHistoryItem(listed, "one");

    expect(applyHistoryDetailTerminal(selected, null, "one", selected.detailRequest, "error")).toEqual({ error: expect.any(String) });
    expect(applyHistoryDetailTerminal(selected, null, "one", selected.detailRequest, "cancelled")).toEqual({ error: expect.any(String) });
  });

  it("keeps an old backup response from replacing the current backup state", () => {
    const initial = { ...createHistoryBackupsState(), phase: "ready" as const, selectedId: "backup-old" };
    const first = startHistoryBackupsLoad(initial);
    const second = startHistoryBackupsLoad(first.state);
    const current = finishHistoryBackupsLoad(second.state, second.request, {
      items: [{ id: "backup-new", created_at: "2026-07-11T12:00:00Z", record_count: 2 }]
    });

    expect(first.state.selectedId).toBe("");
    expect(finishHistoryBackupsLoad(current, first.request, { items: [] })).toBe(current);
    expect(failHistoryBackupsLoad(current, first.request)).toBe(current);
  });

  it("represents a current backup load failure without a selectable backup", () => {
    const started = startHistoryBackupsLoad(createHistoryBackupsState());
    expect(failHistoryBackupsLoad(started.state, started.request)).toEqual({
      phase: "error", items: [], selectedId: "", request: started.request
    });
  });
});
