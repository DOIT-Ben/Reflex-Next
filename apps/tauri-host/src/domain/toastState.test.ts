import { get } from "svelte/store";
import { describe, expect, it } from "vitest";
import {
  TOAST_DURATION_MS,
  createToastController,
  inferToastTone
} from "./toastState";
import type { ToastScheduler } from "./toastState";

function createFakeScheduler(): ToastScheduler & { pending: Array<{ callback: () => void; delayMs: number; id: number }> } {
  let nextId = 1;
  const pending: Array<{ callback: () => void; delayMs: number; id: number }> = [];
  return {
    pending,
    schedule: (callback, delayMs) => {
      const id = nextId++;
      pending.push({ callback, delayMs, id });
      return id;
    },
    cancel: (handle) => {
      const index = pending.findIndex((entry) => entry.id === handle);
      if (index >= 0) pending.splice(index, 1);
    }
  };
}

describe("inferToastTone", () => {
  it("marks failure-like messages as errors", () => {
    expect(inferToastTone("评分未保存，请稍后重试。")).toBe("error");
    expect(inferToastTone("导出暂时不可用，请重试。")).toBe("error");
    expect(inferToastTone("密钥保存失败，请重试。")).toBe("error");
  });

  it("keeps ordinary confirmations as success", () => {
    expect(inferToastTone("✓ 已复制到剪贴板")).toBe("success");
    expect(inferToastTone("评分已保存")).toBe("success");
  });
});

describe("createToastController", () => {
  it("starts hidden with an empty message", () => {
    const toast = createToastController();
    expect(get(toast.state)).toEqual({ visible: false, message: "", tone: "success" });
  });

  it("shows a message with the inferred tone and hides after the duration", () => {
    const scheduler = createFakeScheduler();
    const toast = createToastController({ scheduler });

    toast.show("评分已保存");
    expect(get(toast.state)).toEqual({ visible: true, message: "评分已保存", tone: "success" });
    expect(scheduler.pending).toHaveLength(1);
    expect(scheduler.pending[0].delayMs).toBe(TOAST_DURATION_MS);

    scheduler.pending[0].callback();
    expect(get(toast.state).visible).toBe(false);
  });

  it("cancels the pending hide when a new message arrives", () => {
    const scheduler = createFakeScheduler();
    const toast = createToastController({ scheduler });

    toast.show("第一条");
    toast.show("第二条", "error");
    expect(scheduler.pending).toHaveLength(1);
    expect(get(toast.state)).toEqual({ visible: true, message: "第二条", tone: "error" });
  });

  it("translates messages through the injected translator", () => {
    const noopScheduler: ToastScheduler = {
      schedule: () => 0,
      cancel: () => undefined
    };
    const toast = createToastController({
      translate: (source) => (source === "ready" ? "就绪" : source),
      scheduler: noopScheduler
    });
    toast.show("ready");
    expect(get(toast.state).message).toBe("就绪");
  });
});
