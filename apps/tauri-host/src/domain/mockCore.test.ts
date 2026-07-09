import { describe, expect, it, vi } from "vitest";
import { streamMockOptimization } from "./mockCore";
import { createDraftRequest } from "./reflexSession";

describe("mock core event source", () => {
  it("can emit a recoverable provider unavailable error without network access", async () => {
    vi.useFakeTimers();
    const events = [];
    const iterator = streamMockOptimization(createDraftRequest("模拟服务不可用"));

    events.push((await iterator.next()).value);
    events.push(await nextAfter(iterator, 180));
    events.push(await nextAfter(iterator, 180));

    expect(events).toEqual([
      { type: "status", data: { phase: "analyzing_scene", message: "正在分析场景" } },
      {
        type: "request",
        data: { provider: "MiniMax", model: "abab6.5" }
      },
      {
        type: "error",
        data: {
          code: "provider_unavailable",
          message: "模型服务暂时不可用，请稍后重试。",
          recoverable: true,
          action: "retry",
          diagnostic_id: "mock-provider-unavailable"
        }
      }
    ]);

    vi.useRealTimers();
  });
});

async function nextAfter<T>(iterator: AsyncGenerator<T>, ms: number): Promise<T | undefined> {
  const pending = iterator.next();
  await vi.advanceTimersByTimeAsync(ms);
  return (await pending).value;
}
