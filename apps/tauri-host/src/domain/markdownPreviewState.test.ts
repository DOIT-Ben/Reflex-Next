import { describe, expect, it } from "vitest";
import {
  closeMarkdownPreview,
  completeMarkdownPreview,
  createMarkdownPreviewState,
  failMarkdownPreview,
  openMarkdownPreview,
  selectMarkdownPreviewMode
} from "./markdownPreviewState";

describe("markdown preview state", () => {
  it("opens, completes, and preserves the selected view across close", () => {
    let state = openMarkdownPreview(createMarkdownPreviewState(), "# Title");
    state = selectMarkdownPreviewMode(state, "preview");
    state = completeMarkdownPreview(state, state.request, { html: "<h1>Title</h1>" });
    expect(state.phase).toBe("completed");
    expect(closeMarkdownPreview(state).mode).toBe("preview");
  });

  it("drops late events after a newer request or close", () => {
    const first = openMarkdownPreview(createMarkdownPreviewState(), "one");
    const second = openMarkdownPreview(first, "two");
    expect(completeMarkdownPreview(second, first.request, { html: "<p>old</p>" })).toBe(second);
    const closed = closeMarkdownPreview(second);
    expect(failMarkdownPreview(closed, second.request)).toBe(closed);
  });

  it.each([
    "<script>alert(1)</script>",
    '<a href="javascript:alert(1)">x</a>',
    '<p onclick="alert(1)">x</p>',
    '<img src="https://example.test/x.png">',
    '<svg><a href="https://example.test">x</a></svg>'
  ])("rejects unsafe html from the capability boundary", (html) => {
    const state = openMarkdownPreview(createMarkdownPreviewState(), "source");
    expect(completeMarkdownPreview(state, state.request, { html }).phase).toBe("error");
  });

  it("rejects empty source without changing state", () => {
    const state = createMarkdownPreviewState();
    expect(openMarkdownPreview(state, "   ")).toBe(state);
  });
});
