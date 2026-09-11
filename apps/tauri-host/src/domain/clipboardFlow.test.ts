import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";
import { createClipboardFlow } from "./clipboardFlow";
import type { ClipboardWriter } from "./clipboardBridge";
import type { ClipboardPolicy, HostState } from "./hostState";

type FlowDeps = Parameters<typeof createClipboardFlow>[0];

function createDeps(overrides: Partial<FlowDeps> = {}) {
  const hostState: { state: HostState } = {
    state: { overlay: null, copied: false } as unknown as HostState
  };
  const deps: FlowDeps = {
    clipboardWriter: () =>
      ({
        writeText: vi.fn(async () => ({ ok: true as const }))
      }) as unknown as ClipboardWriter,
    clipboardPolicy: () => "manual" as ClipboardPolicy,
    clipboardReplaceConfirmed: () => false,
    hasPersistedConfig: () => true,
    persistReplaceConfirmation: vi.fn(async () => undefined),
    updateHostState: (updater) => {
      hostState.state = updater(hostState.state);
    },
    showToast: vi.fn(),
    ...overrides
  };
  return { deps, hostState };
}

describe("createClipboardFlow", () => {
  it("writes values through the writer and toasts success", async () => {
    const { deps } = createDeps();
    const flow = createClipboardFlow(deps);

    const copied = await flow.writeValue("hello", "✓ 已复制到剪贴板");

    expect(copied).toBe(true);
    expect(get(flow.notice)).toBeNull();
    expect(deps.showToast).toHaveBeenCalledWith("✓ 已复制到剪贴板");
  });

  it("surfaces the writer failure through notice and error toast", async () => {
    const { deps } = createDeps({
      clipboardWriter: () =>
        ({
          writeText: vi.fn(async () => {
            throw new Error("clipboard blocked");
          })
        }) as unknown as ClipboardWriter
    });
    const flow = createClipboardFlow(deps);

    const copied = await flow.writeValue("hello", "✓ 已复制到剪贴板");

    expect(copied).toBe(false);
    expect(get(flow.notice)).toBe("无法写入剪贴板，请重试。");
    expect(deps.showToast).toHaveBeenCalledWith("无法写入剪贴板，请重试。");
  });

  it("opens the confirm overlay for manual replace until confirmation is persisted", async () => {
    const persistReplaceConfirmation = vi.fn(async () => undefined);
    const { deps, hostState } = createDeps({ persistReplaceConfirmation });
    const flow = createClipboardFlow(deps);

    await flow.requestManualReplace("output text");
    expect((hostState.state as unknown as { overlay: string | null }).overlay).toBe("clipboard_confirm");

    await flow.confirmReplace("output text");
    expect(persistReplaceConfirmation).toHaveBeenCalledTimes(1);
    expect((hostState.state as unknown as { overlay: string | null }).overlay).toBeNull();
  });

  it("writes directly after completion when the policy allows it", async () => {
    const writeText = vi.fn(async () => undefined);
    const { deps } = createDeps({
      clipboardPolicy: () => "auto_replace" as ClipboardPolicy,
      clipboardReplaceConfirmed: () => true,
      clipboardWriter: () => ({ writeText }) as unknown as ClipboardWriter
    });
    const flow = createClipboardFlow(deps);

    await flow.afterCompletion("generated output");

    expect(writeText).toHaveBeenCalledWith("generated output");
  });
});
