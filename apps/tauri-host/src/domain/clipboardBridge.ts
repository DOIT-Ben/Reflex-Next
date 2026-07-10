import type { TauriHostApi } from "./coreBridge";

export type BrowserClipboard = {
  readText?: () => Promise<string>;
};

export type ClipboardReader = {
  readText: () => Promise<string>;
};

export type ClipboardReadResult =
  | { ok: true; text: string }
  | { ok: false; message: string };

export function createClipboardReader(
  host: TauriHostApi | null = null,
  browserClipboard: BrowserClipboard | null = globalThis.navigator?.clipboard ?? null
): ClipboardReader {
  return {
    readText: async () => {
      if (host) {
        return host.invoke<string>("read_clipboard_text");
      }
      if (browserClipboard?.readText) {
        return browserClipboard.readText();
      }
      throw new Error("clipboard API unavailable");
    }
  };
}

export async function readClipboardText(
  reader: ClipboardReader
): Promise<ClipboardReadResult> {
  try {
    const text = await reader.readText();
    if (!text.trim()) {
      return {
        ok: false,
        message: "剪贴板里没有可读取的文本。"
      };
    }
    return { ok: true, text };
  } catch {
    return {
      ok: false,
      message: "无法读取剪贴板，请确认权限后重试。"
    };
  }
}
