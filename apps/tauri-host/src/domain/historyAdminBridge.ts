import type { TauriHostApi } from "./coreBridge";

export const HISTORY_OPERATION_FAILED_MESSAGE = "历史操作失败，请稍后重试。";

export type HistoryExportFormat = "json" | "csv" | "markdown";
export type HistoryAdminOperation = "delete" | "clear" | "repair" | "restore" | "rotate";
export type HistoryOperationResult = "completed" | "cancelled";
export type HistoryOperationPhase = "idle" | "running" | "succeeded" | "failed" | "recovery";

export type HistoryOperationState = {
  phase: HistoryOperationPhase;
  message: string;
};

export type HistoryAdminBridge = {
  exportHistory(
    format: HistoryExportFormat,
    filters: Record<string, unknown>
  ): Promise<HistoryOperationResult>;
  run(
    operation: HistoryAdminOperation,
    input: Record<string, unknown>
  ): Promise<HistoryOperationResult>;
  cancel(): Promise<void>;
};

export function createHistoryAdminBridge(host: TauriHostApi): HistoryAdminBridge {
  return {
    async exportHistory(format, filters) {
      return invokeSafe(host, "history_export", {
        request: { format, filters: { ...filters } }
      });
    },
    async run(operation, input) {
      return invokeSafe(host, "history_admin_operation", {
        operation,
        input: { ...input }
      });
    },
    async cancel() {
      try {
        await host.invoke("history_operation_cancel", {});
      } catch {
        throw new Error(HISTORY_OPERATION_FAILED_MESSAGE);
      }
    }
  };
}

export function createHistoryOperationState(): HistoryOperationState {
  return { phase: "idle", message: "" };
}

export function startHistoryOperation(
  _state: HistoryOperationState,
  message: string
): HistoryOperationState {
  return { phase: "running", message };
}

export function finishHistoryOperation(
  _state: HistoryOperationState,
  result: HistoryOperationResult | "failed" | "recovery"
): HistoryOperationState {
  if (result === "completed") {
    return { phase: "succeeded", message: "历史操作已完成" };
  }
  if (result === "cancelled") {
    return createHistoryOperationState();
  }
  if (result === "recovery") {
    return { phase: "recovery", message: "历史记录需要恢复，请从备份中恢复" };
  }
  return { phase: "failed", message: HISTORY_OPERATION_FAILED_MESSAGE };
}

async function invokeSafe(
  host: TauriHostApi,
  command: string,
  payload: Record<string, unknown>
): Promise<HistoryOperationResult> {
  try {
    const result = await host.invoke<unknown>(command, payload);
    if (result === "completed" || result === "cancelled") return result;
  } catch {
    // Host diagnostics are intentionally replaced with one user-facing message.
  }
  throw new Error(HISTORY_OPERATION_FAILED_MESSAGE);
}
