import { describe, expect, it } from "vitest";
import {
  clipboardActionAfterCompletion,
  clipboardActionForManualReplace,
  createClipboardReader,
  createClipboardWriter,
  readClipboardText,
  shouldReadClipboardOnStartup,
  writeClipboardText,
  type BrowserClipboard
} from "./clipboardBridge";
import type { TauriHostApi } from "./coreBridge";
import { createTauriHostStub } from "./testHost";

describe("clipboard bridge", () => {
  it("reads clipboard text through the Tauri host when available", async () => {
    const calls: unknown[] = [];
    const host: TauriHostApi = createTauriHostStub({
      invoke: async (command, args) => {
        calls.push({ command, args });
        return "来自宿主剪贴板";
      },
      listen: async () => () => undefined
    });

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

  it("writes clipboard text through the Tauri host when available", async () => {
    const calls: unknown[] = [];
    const host: TauriHostApi = createTauriHostStub({
      invoke: async (command, args) => {
        calls.push({ command, args });
        return undefined;
      },
      listen: async () => () => undefined
    });

    const result = await writeClipboardText(createClipboardWriter(host), "优化结果");

    expect(result).toEqual({ ok: true });
    expect(calls).toEqual([
      { command: "write_clipboard_text", args: { text: "优化结果" } }
    ]);
  });

  it("falls back to browser clipboard writes outside Tauri", async () => {
    const written: string[] = [];
    const browserClipboard: BrowserClipboard = {
      writeText: async (text) => {
        written.push(text);
      }
    };

    const result = await writeClipboardText(
      createClipboardWriter(null, browserClipboard),
      "浏览器结果"
    );

    expect(result).toEqual({ ok: true });
    expect(written).toEqual(["浏览器结果"]);
  });

  it("returns one safe message for blank or failed writes", async () => {
    const browserClipboard: BrowserClipboard = {
      writeText: async () => {
        throw new Error("raw clipboard backend failure");
      }
    };
    const writer = createClipboardWriter(null, browserClipboard);

    await expect(writeClipboardText(writer, "   ")).resolves.toEqual({
      ok: false,
      message: "无法写入剪贴板，请重试。"
    });
    await expect(writeClipboardText(writer, "private result")).resolves.toEqual({
      ok: false,
      message: "无法写入剪贴板，请重试。"
    });
  });

  it("resolves startup, manual replacement and automatic replacement policies", () => {
    expect(shouldReadClipboardOnStartup("startup", false)).toBe(true);
    expect(shouldReadClipboardOnStartup("startup", true)).toBe(false);
    expect(shouldReadClipboardOnStartup("manual", false)).toBe(false);

    expect(clipboardActionForManualReplace(false)).toBe("confirm");
    expect(clipboardActionForManualReplace(true)).toBe("write");

    expect(clipboardActionAfterCompletion("manual", false)).toBe("none");
    expect(clipboardActionAfterCompletion("auto_replace", false)).toBe("confirm");
    expect(clipboardActionAfterCompletion("auto_replace", true)).toBe("write");
  });
});
