import { describe, expect, it, vi } from "vitest";

import type { TauriHostApi } from "./coreBridge";
import {
  createDiagnosticBundleBridge,
  DIAGNOSTIC_EXPORT_FAILED_MESSAGE
} from "./diagnosticBundleBridge";

function hostWithInvoke(invoke: TauriHostApi["invoke"]): TauriHostApi {
  return { invoke, listen: vi.fn() };
}

describe("DiagnosticBundleBridge", () => {
  it("uses fixed no-argument host commands without path or upload authority", async () => {
    const invoke = vi.fn().mockResolvedValueOnce("completed").mockResolvedValueOnce(undefined);
    const bridge = createDiagnosticBundleBridge(hostWithInvoke(invoke));

    await expect(bridge.exportBundle()).resolves.toBe("completed");
    await bridge.cancel();

    expect(invoke).toHaveBeenNthCalledWith(1, "diagnostic_bundle_export", {});
    expect(invoke).toHaveBeenNthCalledWith(2, "diagnostic_bundle_cancel", {});
    const serialized = JSON.stringify(invoke.mock.calls);
    for (const forbidden of ["path", "upload", "url", "handle", "confirmed", "scan"]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it("accepts only the two fixed terminal results", async () => {
    for (const result of ["completed", "cancelled"] as const) {
      const bridge = createDiagnosticBundleBridge(
        hostWithInvoke(vi.fn().mockResolvedValue(result))
      );
      await expect(bridge.exportBundle()).resolves.toBe(result);
    }
    const invalid = createDiagnosticBundleBridge(
      hostWithInvoke(vi.fn().mockResolvedValue({ path: "D:/private.zip" }))
    );
    await expect(invalid.exportBundle()).rejects.toThrow(DIAGNOSTIC_EXPORT_FAILED_MESSAGE);
  });

  it("preserves only allowlisted user-facing host errors", async () => {
    const empty = createDiagnosticBundleBridge(
      hostWithInvoke(vi.fn().mockRejectedValue("暂无可导出的诊断记录。请先启用本地诊断。"))
    );
    await expect(empty.exportBundle()).rejects.toThrow(
      "暂无可导出的诊断记录。请先启用本地诊断。"
    );

    const unsafe = createDiagnosticBundleBridge(
      hostWithInvoke(
        vi.fn().mockRejectedValue(new Error("D:/private Bearer fixture debug request-1"))
      )
    );
    await expect(unsafe.exportBundle()).rejects.toThrow(DIAGNOSTIC_EXPORT_FAILED_MESSAGE);
    await expect(unsafe.exportBundle()).rejects.not.toThrow("D:/private");
  });
});
