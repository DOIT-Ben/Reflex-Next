import { describe, expect, it, vi } from "vitest";

import {
  createHistoryAdminBridge,
  createHistoryOperationState,
  finishHistoryOperation,
  HISTORY_OPERATION_FAILED_MESSAGE,
  startHistoryOperation
} from "./historyAdminBridge";
import type { TauriHostApi } from "./coreBridge";


function hostWithInvoke(invoke: TauriHostApi["invoke"]): TauriHostApi {
  return { invoke, listen: vi.fn() };
}


describe("HistoryAdminBridge", () => {
  it("submits only export format and filters to the native host", async () => {
    const invoke = vi.fn().mockResolvedValue("completed");
    const bridge = createHistoryAdminBridge(hostWithInvoke(invoke));

    const result = await bridge.exportHistory("json", { provider: "minimax" });

    expect(result).toBe("completed");
    expect(invoke).toHaveBeenCalledWith("history_export", {
      request: { format: "json", filters: { provider: "minimax" } }
    });
    const serialized = JSON.stringify(invoke.mock.calls);
    for (const forbidden of ["path", "handle", "confirmed", "admin", "request_id"]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it("uses the dedicated native admin command without building runtime authority", async () => {
    const invoke = vi.fn().mockResolvedValue("completed");
    const bridge = createHistoryAdminBridge(hostWithInvoke(invoke));

    await bridge.run("restore", { backup_id: "backup-1" });

    expect(invoke).toHaveBeenCalledWith("history_admin_operation", {
      operation: "restore",
      input: { backup_id: "backup-1" }
    });
    await bridge.cancel();
    expect(invoke).toHaveBeenLastCalledWith("history_operation_cancel", {});
  });

  it("returns fixed safe failure text without echoing host errors", async () => {
    const invoke = vi.fn().mockRejectedValue(
      new Error("D:/private/history.sqlite3 Bearer fixture-private debug request-1")
    );
    const bridge = createHistoryAdminBridge(hostWithInvoke(invoke));

    await expect(bridge.run("repair", {})).rejects.toThrow(
      HISTORY_OPERATION_FAILED_MESSAGE
    );
    await expect(bridge.run("repair", {})).rejects.not.toThrow("fixture-private");
  });
});


describe("history operation state", () => {
  it("shows only user-facing loading, success, cancellation and recovery states", () => {
    const initial = createHistoryOperationState();
    const running = startHistoryOperation(initial, "正在修复历史记录");
    const completed = finishHistoryOperation(running, "completed");
    const cancelled = finishHistoryOperation(running, "cancelled");
    const recovery = finishHistoryOperation(running, "recovery");

    expect(running).toEqual({ phase: "running", message: "正在修复历史记录" });
    expect(completed).toEqual({ phase: "succeeded", message: "历史操作已完成" });
    expect(cancelled).toEqual({ phase: "idle", message: "" });
    expect(recovery).toEqual({ phase: "recovery", message: "历史记录需要恢复，请从备份中恢复" });
    const visible = JSON.stringify([running, completed, cancelled, recovery]);
    for (const internal of ["debug", "plugin", "request", "phase", "D:/", "验收", "工具"]) {
      if (internal === "phase") continue;
      expect(visible.toLowerCase()).not.toContain(internal.toLowerCase());
    }
  });
});
