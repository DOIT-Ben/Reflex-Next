import { describe, expect, it, vi } from "vitest";
import { plainTextMime, triggerDownload, TEXT_MARKDOWN_MIME, type DownloadAnchor } from "./downloads";

function createFakeDocument() {
  const anchors: DownloadAnchor[] = [];
  return {
    anchors,
    createElement: (tag: string) => {
      expect(tag).toBe("a");
      const anchor: DownloadAnchor = {
        href: "",
        download: "",
        style: { display: "" },
        click: vi.fn(),
        remove: vi.fn()
      };
      anchors.push(anchor);
      return anchor;
    },
    body: { append: vi.fn() }
  };
}

describe("triggerDownload", () => {
  it("creates, clicks and removes a hidden anchor with the blob url", () => {
    const document = createFakeDocument();
    const revokeObjectURL = vi.fn();
    const createObjectURL = vi.fn(() => "blob:test-1");
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const setTimeout = vi.fn((callback: () => void) => {
      callback();
      return 0;
    });

    triggerDownload(document as never, "# hello", "result.md", TEXT_MARKDOWN_MIME, { setTimeout });

    expect(createObjectURL).toHaveBeenCalledWith(new Blob(["# hello"], { type: TEXT_MARKDOWN_MIME }));
    expect(document.anchors).toHaveLength(1);
    const anchor = document.anchors[0];
    expect(anchor.href).toBe("blob:test-1");
    expect(anchor.download).toBe("result.md");
    expect(anchor.style.display).toBe("none");
    expect(anchor.click).toHaveBeenCalledTimes(1);
    expect(anchor.remove).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:test-1");
    vi.unstubAllGlobals();
  });

  it("maps batch formats to csv and plain text mimes", () => {
    expect(plainTextMime("csv")).toBe("text/csv;charset=utf-8");
    expect(plainTextMime("txt")).toBe("text/plain;charset=utf-8");
  });
});
