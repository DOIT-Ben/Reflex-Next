import type { TauriHostApi } from "./coreBridge";

export const DIAGNOSTIC_EXPORT_FAILED_MESSAGE = "诊断包导出失败，请重试。";

const SAFE_HOST_MESSAGES = new Set([
  DIAGNOSTIC_EXPORT_FAILED_MESSAGE,
  "暂无可导出的诊断记录。请先启用本地诊断。",
  "诊断记录包含无法安全导出的内容，已停止导出。",
  "诊断包正在导出，请稍候。"
]);

export type DiagnosticExportResult = "completed" | "cancelled";

export type DiagnosticBundleBridge = {
  exportBundle(): Promise<DiagnosticExportResult>;
  cancel(): Promise<void>;
};

export function createDiagnosticBundleBridge(host: TauriHostApi): DiagnosticBundleBridge {
  return {
    async exportBundle() {
      try {
        const result = await host.invoke<unknown>("diagnostic_bundle_export", {});
        if (result === "completed" || result === "cancelled") return result;
      } catch (error) {
        throw new Error(safeHostMessage(error));
      }
      throw new Error(DIAGNOSTIC_EXPORT_FAILED_MESSAGE);
    },
    async cancel() {
      try {
        await host.invoke("diagnostic_bundle_cancel", {});
      } catch (error) {
        throw new Error(safeHostMessage(error));
      }
    }
  };
}

function safeHostMessage(error: unknown): string {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : "";
  return SAFE_HOST_MESSAGES.has(message) ? message : DIAGNOSTIC_EXPORT_FAILED_MESSAGE;
}
