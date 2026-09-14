import { describe, expect, it } from "vitest";
import { installContextMenuGuard } from "./contextMenuGuard";

type FakeListener = (event: { target?: unknown; preventDefault: () => void }) => void;

class FakeWindow {
  listeners: Array<{ type: string; listener: FakeListener }> = [];

  addEventListener(type: string, listener: FakeListener): void {
    this.listeners.push({ type, listener });
  }

  removeEventListener(type: string, listener: FakeListener): void {
    this.listeners = this.listeners.filter(
      (entry) => entry.type !== type || entry.listener !== listener
    );
  }

  dispatch(target: unknown): boolean {
    let prevented = false;
    const event = {
      target,
      preventDefault: () => {
        prevented = true;
      }
    };
    for (const entry of this.listeners) {
      if (entry.type === "contextmenu") entry.listener(event);
    }
    return prevented;
  }
}

const plainTarget = { closest: () => null };
const editableTarget = { closest: () => ({ tagName: "TEXTAREA" }) };

describe("context menu guard", () => {
  it("blocks the native browser menu outside editable fields", () => {
    const window = new FakeWindow();
    const dispose = installContextMenuGuard(window);

    expect(window.dispatch(plainTarget)).toBe(true);
    expect(window.dispatch(null)).toBe(true);

    dispose();
  });

  it("keeps the native menu inside inputs and textareas", () => {
    const window = new FakeWindow();
    installContextMenuGuard(window);

    expect(window.dispatch(editableTarget)).toBe(false);
  });

  it("stops blocking after dispose", () => {
    const window = new FakeWindow();
    const dispose = installContextMenuGuard(window);
    dispose();

    expect(window.dispatch(plainTarget)).toBe(false);
  });
});
