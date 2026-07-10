import { describe, expect, it } from "vitest";
import {
  createClipboardReader,
  readClipboardText,
  type BrowserClipboard
} from "./clipboardBridge";
import type { TauriHostApi } from "./coreBridge";

describe("clipboard bridge", () => {
  it("reads clipboard text through the Tauri host when available", async () => {
    const calls: unknown[] = [];
    const host: TauriHostApi = {
      invoke: async (command, args) => {
        calls.push({ command, args });
        return "来自宿主剪贴板";
      },
      listen: async () => () => undefined
    };

    const reader = createClipboardReader(host);

    await expect(reader.readText()).resolves.toBe("来自宿主剪贴板");
    expect(calls).toEqual([{ command: "read_clipboard_text", args: undefined }]);
  });

  it("falls back to the browser clipboard API outside Tauri", async () => {
    const browserClipboard: BrowserClipboard = {
      readText: async () => "来自浏览器剪贴板"
    };

    const reader = createClipboardReader(null, browserClipboard);

    await expect(reader.readText()).resolves.toBe("来自浏览器剪贴板");
  });

  it("returns a safe message when clipboard permission or API is unavailable", async () => {
    const browserClipboard: BrowserClipboard = {
      readText: async () => {
        throw new Error("NotAllowedError: raw permission failure");
      }
    };

    const result = await readClipboardText(createClipboardReader(null, browserClipboard));

    expect(result).toEqual({
      ok: false,
      message: "无法读取剪贴板，请确认权限后重试。"
    });
  });

  it("treats empty clipboard text as a user-visible empty state", async () => {
    const browserClipboard: BrowserClipboard = {
      readText: async () => "   "
    };

    const result = await readClipboardText(createClipboardReader(null, browserClipboard));

    expect(result).toEqual({
      ok: false,
      message: "剪贴板里没有可读取的文本。"
    });
  });
});
