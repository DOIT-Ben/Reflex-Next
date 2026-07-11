import { describe, expect, it } from "vitest";

import { appendHistoryPage, createHistoryState, failHistoryQuery, finishHistoryOperation, removeHistoryItem, selectHistoryItem, setHistoryDetail, startHistoryOperation, startHistoryQuery, updateHistoryRating } from "./historyState";

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
});
