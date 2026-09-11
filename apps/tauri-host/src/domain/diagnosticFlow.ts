import { writable, type Writable } from "svelte/store";
import type { DiagnosticBundleBridge } from "./diagnosticBundleBridge";

export type DiagnosticFlowDeps = {
  diagnosticBundleBridge: () => DiagnosticBundleBridge | null;
};

export type DiagnosticFlow = {
  busy: Writable<boolean>;
  notice: Writable<string | null>;
  exportBundle: () => Promise<void>;
  cancelExport: () => Promise<void>;
};

export function createDiagnosticFlow(deps: DiagnosticFlowDeps): DiagnosticFlow {
  const busy = writable(false);
  const notice = writable<string | null>(null);

  async function exportBundle() {
    const bridge = deps.diagnosticBundleBridge();
    if (get(busy)) return;
    if (!bridge) {
      notice.set("当前环境无法导出诊断包。");
      return;
    }
    busy.set(true);
    notice.set("正在导出诊断包...");
    try {
      const result = await bridge.exportBundle();
      notice.set(result === "completed" ? "诊断包已导出。" : "诊断包导出已取消。");
    } catch (error) {
      notice.set(error instanceof Error ? error.message : "诊断包导出失败，请重试。");
    } finally {
      busy.set(false);
    }
  }

  async function cancelExport() {
    const bridge = deps.diagnosticBundleBridge();
    if (!get(busy) || !bridge) return;
    try {
      await bridge.cancel();
      notice.set("正在取消诊断包导出...");
    } catch (error) {
      notice.set(error instanceof Error ? error.message : "诊断包导出失败，请重试。");
    }
  }

  return { busy, notice, exportBundle, cancelExport };
}
