import { writable, type Writable } from "svelte/store";
import {
  clipboardActionAfterCompletion,
  clipboardActionForManualReplace,
  writeClipboardText,
  type ClipboardAction,
  type ClipboardPolicy,
  type ClipboardWriter
} from "./clipboardBridge";
import type { HostState } from "./hostState";

export type ClipboardFlowDeps = {
  clipboardWriter: () => ClipboardWriter;
  clipboardPolicy: () => ClipboardPolicy | null;
  clipboardReplaceConfirmed: () => boolean;
  hasPersistedConfig: () => boolean;
  persistReplaceConfirmation: () => Promise<void>;
  updateHostState: (updater: (state: HostState) => HostState) => void;
  showToast: (message: string, tone?: "success" | "error") => void;
  scheduler?: (callback: () => void, delayMs: number) => unknown;
};

export type ClipboardFlow = {
  notice: Writable<string | null>;
  writeValue: (text: string, successMessage: string) => Promise<boolean>;
  copyResult: (output: string | null) => Promise<void>;
  requestManualReplace: (output: string | null) => Promise<void>;
  afterCompletion: (output: string | null) => Promise<void>;
  confirmReplace: (output: string | null) => Promise<void>;
};

const COPIED_FLAG_MS = 1400;
const REPLACE_SUCCESS_MESSAGE = "✓ 已替换剪贴板";

export function createClipboardFlow(deps: ClipboardFlowDeps): ClipboardFlow {
  const notice = writable<string | null>(null);
  const schedule = deps.scheduler ?? ((callback, delayMs) => window.setTimeout(callback, delayMs));

  async function writeValue(text: string, successMessage: string): Promise<boolean> {
    const result = await writeClipboardText(deps.clipboardWriter(), text);
    if (!result.ok) {
      notice.set(result.message);
      deps.showToast(result.message);
      return false;
    }
    notice.set(null);
    deps.showToast(successMessage);
    return true;
  }

  async function copyResult(output: string | null) {
    if (!output) return;
    const copied = await writeValue(output, "✓ 已复制到剪贴板");
    if (!copied) return;
    deps.updateHostState((state) => ({ ...state, copied: true }));
    schedule(() => {
      deps.updateHostState((state) => ({ ...state, copied: false }));
    }, COPIED_FLAG_MS);
  }

  async function executeAction(action: ClipboardAction, output: string | null) {
    if (action === "none") return;
    if (action === "confirm") {
      notice.set(null);
      deps.updateHostState((state) => ({ ...state, overlay: "clipboard_confirm" }));
      return;
    }
    await writeValue(output ?? "", REPLACE_SUCCESS_MESSAGE);
  }

  async function requestManualReplace(output: string | null) {
    if (!output) return;
    await executeAction(
      clipboardActionForManualReplace(deps.clipboardReplaceConfirmed()),
      output
    );
  }

  async function afterCompletion(output: string | null) {
    const policy = deps.clipboardPolicy() ?? "manual";
    await executeAction(
      clipboardActionAfterCompletion(policy, deps.clipboardReplaceConfirmed()),
      output
    );
  }

  async function confirmReplace(output: string | null) {
    const replaced = await writeValue(output ?? "", REPLACE_SUCCESS_MESSAGE);
    if (!replaced) return;
    await deps.persistReplaceConfirmation();
    deps.updateHostState((state) => ({ ...state, overlay: null }));
    notice.set(null);
  }

  return {
    notice,
    writeValue,
    copyResult,
    requestManualReplace,
    afterCompletion,
    confirmReplace
  };
}
