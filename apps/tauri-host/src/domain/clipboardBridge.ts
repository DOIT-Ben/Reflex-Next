import type { TauriHostApi } from "./coreBridge";
import type { ClipboardPolicy } from "./hostState";

export type BrowserClipboard = {
  readText?: () => Promise<string>;
  writeText?: (text: string) => Promise<void>;
};

export type ClipboardReader = {
  readText: () => Promise<string>;
};

export type ClipboardWriter = {
  writeText: (text: string) => Promise<void>;
};

export type ClipboardReadResult =
  | { ok: true; text: string }
  | { ok: false; message: string };

export type ClipboardWriteResult =
  | { ok: true }
  | { ok: false; message: string };

export type ClipboardAction = "none" | "confirm" | "write";

export function shouldReadClipboardOnStartup(
  policy: ClipboardPolicy,
  hasReadOnStartup: boolean
): boolean {
  return policy === "startup" && !hasReadOnStartup;
}

export function clipboardActionForManualReplace(
  replaceConfirmed: boolean
): ClipboardAction {
  return replaceConfirmed ? "write" : "confirm";
}

export function clipboardActionAfterCompletion(
  policy: ClipboardPolicy,
  replaceConfirmed: boolean
): ClipboardAction {
  if (policy !== "auto_replace") return "none";
  return replaceConfirmed ? "write" : "confirm";
}

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

export function createClipboardWriter(
  host: TauriHostApi | null = null,
  browserClipboard: BrowserClipboard | null = globalThis.navigator?.clipboard ?? null
): ClipboardWriter {
  return {
    writeText: async (text) => {
      if (host) {
        await host.invoke("write_clipboard_text", { text });
        return;
      }
      if (browserClipboard?.writeText) {
        await browserClipboard.writeText(text);
        return;
      }
      throw new Error("clipboard API unavailable");
    }
  };
}

export async function writeClipboardText(
  writer: ClipboardWriter,
  text: string
): Promise<ClipboardWriteResult> {
  if (!text.trim()) {
    return { ok: false, message: "无法写入剪贴板，请重试。" };
  }
  try {
    await writer.writeText(text);
    return { ok: true };
  } catch {
    return { ok: false, message: "无法写入剪贴板，请重试。" };
  }
}
