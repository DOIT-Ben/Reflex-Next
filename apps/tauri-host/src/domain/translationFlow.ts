import { get, writable, type Writable } from "svelte/store";
import type { CapabilityBridge } from "./capabilityBridge";
import type { CoreBridge } from "./coreBridge";
import type { CurrentResult, HostState } from "./hostState";
import { applyTranslationAsCurrentResult } from "./hostState";
import {
  appendTranslationChunk,
  buildCloudTranslationPlan,
  buildTranslationInput,
  cancelTranslation,
  closeTranslation,
  completeTranslation,
  createTranslationState,
  failTranslation,
  openTranslation,
  selectTranslationTarget,
  startTranslation,
  translationErrorMessage,
  type TranslationState,
  type TranslationTarget
} from "./translationState";

export type CapabilityInvokeBridge = Pick<CapabilityBridge, "invoke">;

export type TranslationFlowDeps = {
  coreBridge: () => CoreBridge | null;
  capabilityBridge: () => CapabilityInvokeBridge | null;
  currentResult: () => CurrentResult | null;
  fallbackRoute: () => { provider?: string | null; model?: string | null };
  updateHostState: (updater: (state: HostState) => HostState) => void;
  writeClipboardValue: (text: string, successMessage: string) => Promise<boolean>;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type TranslationFlow = {
  state: Writable<TranslationState>;
  open: (source: CurrentResult | null, enabled: boolean) => void;
  run: () => Promise<void>;
  chooseTarget: (target: TranslationTarget) => void;
  cancel: () => void;
  close: () => void;
  copy: () => Promise<void>;
  useAsCurrentResult: () => void;
};

const TRANSLATION_UNAVAILABLE_MESSAGE = "翻译暂时不可用，请重试。";
const PLUGIN_TIMEOUT_MS = 60_000;

export function createTranslationFlow(deps: TranslationFlowDeps): TranslationFlow {
  const state = writable<TranslationState>(createTranslationState());
  let runController: AbortController | null = null;
  let sourceResult: CurrentResult | null = null;

  function set(next: TranslationState) {
    state.set(next);
  }

  function open(source: CurrentResult | null, enabled: boolean) {
    if (!source || !source.output.trim() || !enabled) return;
    sourceResult = { ...source };
    const next = openTranslation(get(state), source.output);
    set(next);
    if (next.phase !== "closed") {
      void run();
    }
  }

  async function run() {
    const current = get(state);
    if (current.phase === "closed") return;
    runController?.abort();
    const started = startTranslation(current);
    set(started.state);
    const request = started.request;
    const controller = new AbortController();
    runController = controller;
    const currentRoute = sourceResult ?? {};
    const fallbackRoute = deps.fallbackRoute();
    const input = buildTranslationInput(current, currentRoute, fallbackRoute);
    const cloudPlan = buildCloudTranslationPlan(current, currentRoute, fallbackRoute);
    const bridge = deps.capabilityBridge();
    if (!cloudPlan && (!bridge || !input)) {
      if (runController === controller) {
        set(failTranslation(get(state), request, TRANSLATION_UNAVAILABLE_MESSAGE));
        runController = null;
      }
      return;
    }

    try {
      if (cloudPlan) {
        const coreBridge = deps.coreBridge();
        if (!coreBridge) {
          if (runController === controller) {
            set(failTranslation(get(state), request, TRANSLATION_UNAVAILABLE_MESSAGE));
            runController = null;
          }
          return;
        }
        for await (const event of coreBridge.optimize(cloudPlan.request, {
          signal: controller.signal
        })) {
          if (controller.signal.aborted || runController !== controller) return;
          if (event.type === "chunk") {
            set(appendTranslationChunk(get(state), request, event.data.text));
          } else if (event.type === "done") {
            set(
              completeTranslation(get(state), request, {
                text: event.data.text ?? event.data.final_text,
                source_language: cloudPlan.sourceLanguage,
                target_language: cloudPlan.targetLanguage
              })
            );
          } else if (event.type === "error") {
            set(failTranslation(get(state), request, translationErrorMessage(event.data.code)));
          }
        }
      } else if (bridge && input) {
        for await (const event of bridge.invoke("translator", "translate", input, {
          signal: controller.signal,
          timeoutMs: PLUGIN_TIMEOUT_MS
        })) {
          if (controller.signal.aborted || runController !== controller) return;
          if (event.status === "chunk") {
            set(appendTranslationChunk(get(state), request, event.data.text));
          } else if (event.status === "result") {
            set(completeTranslation(get(state), request, event.data));
          } else if (event.status === "cancelled") {
            set(cancelTranslation(get(state), request));
          } else if (event.status === "error") {
            set(failTranslation(get(state), request, translationErrorMessage(event.code)));
          }
        }
      }
      if (runController === controller && get(state).phase === "streaming") {
        set(
          controller.signal.aborted
            ? cancelTranslation(get(state), request)
            : failTranslation(get(state), request, TRANSLATION_UNAVAILABLE_MESSAGE)
        );
      }
    } catch {
      if (runController === controller) {
        set(
          controller.signal.aborted
            ? cancelTranslation(get(state), request)
            : failTranslation(get(state), request, TRANSLATION_UNAVAILABLE_MESSAGE)
        );
      }
    } finally {
      if (runController === controller) runController = null;
    }
  }

  function chooseTarget(target: TranslationTarget) {
    const next = selectTranslationTarget(get(state), target);
    if (next === get(state)) return;
    set(next);
    void run();
  }

  function cancel() {
    const request = get(state).request;
    runController?.abort();
    runController = null;
    set(cancelTranslation(get(state), request));
  }

  function close() {
    runController?.abort();
    runController = null;
    set(closeTranslation(get(state)));
    sourceResult = null;
  }

  async function copy() {
    const translatedText = get(state).translatedText;
    if (!translatedText) return;
    await deps.writeClipboardValue(translatedText, "✓ 译文已复制");
  }

  function useAsCurrentResult() {
    const current = get(state);
    if (!current.translatedText || !sourceResult) return;
    const source = sourceResult;
    deps.updateHostState((host) =>
      applyTranslationAsCurrentResult(host, current.translatedText, current.request, source)
    );
    close();
    deps.showToast("已设为当前结果");
  }

  return { state, open, run, chooseTarget, cancel, close, copy, useAsCurrentResult };
}
