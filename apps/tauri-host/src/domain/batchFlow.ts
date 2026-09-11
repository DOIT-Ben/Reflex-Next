import { get, writable, type Writable } from "svelte/store";
import type { CapabilityInvokeBridge } from "./translationFlow";
import type { CoreBridge } from "./coreBridge";
import type { OptimizeMode } from "./reflexSession";
import type { TranslateFn } from "./i18nStore";
import {
  batchCanExport,
  beginBatchParse,
  beginBatchRun,
  cancelBatch,
  closeBatch,
  completeBatchItem,
  completeBatchParse,
  createBatchState,
  failBatchItem,
  failBatchParse,
  finalizeBatchRun,
  openBatch,
  runBatchWorkerPool,
  setBatchFormat,
  setBatchSourceText,
  startBatchItem,
  type BatchState
} from "./batchState";
import {
  batchTemplateContent,
  readBatchImportFile,
  type BatchImportFailure
} from "./batchFileImport";
import { plainTextMime, triggerDownload } from "./downloads";

export type BatchFlowDeps = {
  coreBridge: () => CoreBridge | null;
  capabilityBridge: () => CapabilityInvokeBridge | null;
  requestContext: () => { mode: OptimizeMode; provider: string | null; model: string | null };
  language: () => "zh-CN" | "en-US";
  translate: TranslateFn;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type BatchFlow = {
  state: Writable<BatchState>;
  fileNotice: Writable<string | null>;
  open: () => void;
  close: () => void;
  parse: () => Promise<void>;
  importFile: (file: File) => Promise<void>;
  downloadTemplate: () => void;
  run: () => Promise<void>;
  cancel: () => void;
  export: () => Promise<void>;
};

const PLUGIN_TIMEOUT_MS = 20_000;
const ITEM_FAILURE_MESSAGE = "此条处理失败，请稍后重试。";
const EXPORT_UNAVAILABLE_MESSAGE = "导出暂时不可用，请重试。";
const PARSE_FAILURE_MESSAGE = "导入内容格式不正确，请检查后重试。";

const BATCH_IMPORT_FAILURE_MESSAGES: Record<BatchImportFailure, string> = {
  unsupported_file: "请选择 CSV 或 TXT 文件。",
  file_too_large: "文件超过 200 万字符限制。",
  empty_file: "文件中没有可导入的内容。",
  read_failed: "无法读取该文件，请重试。"
};

export function batchImportFailureMessage(reason: BatchImportFailure): string {
  return BATCH_IMPORT_FAILURE_MESSAGES[reason];
}

export function batchEventText(data: Record<string, unknown>): string {
  for (const key of ["text", "output", "result"]) {
    if (typeof data[key] === "string") return data[key].replace(/\u0000/g, "").replace(/\r\n?/g, "\n");
  }
  return "";
}

export function createBatchFlow(deps: BatchFlowDeps): BatchFlow {
  const state = writable<BatchState>(createBatchState());
  const fileNotice = writable<string | null>(null);
  let runController: AbortController | null = null;

  function set(next: BatchState) {
    state.set(next);
  }

  function open() {
    set(openBatch(get(state)));
    fileNotice.set(null);
  }

  function close() {
    runController?.abort();
    runController = null;
    set(closeBatch(get(state)));
    fileNotice.set(null);
  }

  async function parse() {
    const started = beginBatchParse(get(state));
    if (!started) return;
    const bridge = deps.capabilityBridge();
    set(started.state);
    if (!bridge) {
      set(failBatchParse(get(state), started.request, "批处理暂时不可用，请重试。"));
      return;
    }
    try {
      for await (const event of bridge.invoke(
        "batch-runner",
        "parse",
        { format: get(state).format, content: get(state).sourceText },
        { timeoutMs: PLUGIN_TIMEOUT_MS }
      )) {
        if (get(state).request !== started.request) return;
        if (event.status === "result") {
          set(completeBatchParse(get(state), started.request, event.data));
        } else if (event.status === "error" || event.status === "cancelled") {
          set(failBatchParse(get(state), started.request, PARSE_FAILURE_MESSAGE));
        }
      }
    } catch {
      set(failBatchParse(get(state), started.request, "批处理暂时不可用，请重试。"));
    }
  }

  async function importFile(file: File) {
    if (!file || get(state).phase === "parsing" || get(state).phase === "running") return;

    const imported = await readBatchImportFile(file);
    if (!imported.ok) {
      fileNotice.set(batchImportFailureMessage(imported.reason));
      return;
    }

    set(setBatchFormat(get(state), imported.format));
    set(setBatchSourceText(get(state), imported.content));
    fileNotice.set(null);
    await parse();
    if (get(state).phase === "ready") {
      deps.showToast(
        deps.translate("已从 {name} 导入 {count} 条提示词", {
          name: file.name,
          count: get(state).items.length
        })
      );
    }
  }

  function downloadTemplate() {
    const format = get(state).format;
    triggerDownload(
      document,
      batchTemplateContent(format),
      `reflex-batch-template.${format}`,
      plainTextMime(format),
      window
    );
  }

  async function run() {
    const started = beginBatchRun(get(state));
    if (!started) return;
    const coreBridge = deps.coreBridge();
    if (!coreBridge) return;
    const controller = new AbortController();
    runController = controller;
    set(started.state);
    const request = started.request;
    const items = get(state).items;
    const context = deps.requestContext();
    const language = deps.language();

    await runBatchWorkerPool(items, get(state).concurrency, controller.signal, async (item) => {
      if (controller.signal.aborted || get(state).request !== request) return;
      set(startBatchItem(get(state), request, item.id));
      let output = "";
      try {
        const optimizeRequest = {
          text: item.prompt,
          mode: context.mode,
          style: get(state).style,
          scene: get(state).scene,
          scene_policy: get(state).scene ? ("manual" as const) : ("auto" as const),
          provider: context.provider,
          model: context.model,
          stream: true,
          metadata: { host: "tauri" as const, surface: "quick-panel" as const, language }
        };
        for await (const event of coreBridge.optimize(optimizeRequest, {
          signal: controller.signal
        })) {
          if (controller.signal.aborted || get(state).request !== request) return;
          if (event.type === "chunk") output += batchEventText(event.data);
          if (event.type === "done") {
            const completed = batchEventText(event.data);
            if (completed) output = completed;
          }
          if (event.type === "error") {
            set(failBatchItem(get(state), request, item.id, ITEM_FAILURE_MESSAGE));
            return;
          }
        }
        if (!controller.signal.aborted && get(state).request === request) {
          set(completeBatchItem(get(state), request, item.id, output));
        }
      } catch {
        if (!controller.signal.aborted && get(state).request === request) {
          set(failBatchItem(get(state), request, item.id, ITEM_FAILURE_MESSAGE));
        }
      }
    });

    if (runController === controller) runController = null;
    if (!controller.signal.aborted) set(finalizeBatchRun(get(state), request));
  }

  function cancel() {
    runController?.abort();
    runController = null;
    set(cancelBatch(get(state)));
  }

  async function exportResults() {
    if (!batchCanExport(get(state))) return;
    const bridge = deps.capabilityBridge();
    if (!bridge) {
      deps.showToast(EXPORT_UNAVAILABLE_MESSAGE);
      return;
    }
    let content = "";
    try {
      for await (const event of bridge.invoke(
        "batch-runner",
        "export",
        {
          format: get(state).format,
          items: get(state).items.map(({ id, prompt, result, status }) => ({ id, prompt, result, status }))
        },
        { timeoutMs: PLUGIN_TIMEOUT_MS }
      )) {
        if (event.status === "result" && typeof event.data.content === "string") content = event.data.content;
        if (event.status === "error" || event.status === "cancelled") break;
      }
    } catch {
      content = "";
    }
    if (!content) {
      deps.showToast(EXPORT_UNAVAILABLE_MESSAGE);
      return;
    }
    const format = get(state).format;
    triggerDownload(document, content, `reflex-batch-results.${format}`, plainTextMime(format), window);
    deps.showToast("批处理结果已导出");
  }

  return {
    state,
    fileNotice,
    open,
    close,
    parse,
    importFile,
    downloadTemplate,
    run,
    cancel,
    export: exportResults
  };
}
