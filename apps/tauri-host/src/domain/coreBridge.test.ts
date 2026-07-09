import { describe, expect, it } from "vitest";
import {
  createCancelCommand,
  createOptimizeCommand,
  parseNdjsonEnvelopes,
  parseNdjsonEvents,
  selectEventsForRequest
} from "./coreBridge";
import { createDraftRequest } from "./reflexSession";

describe("core bridge", () => {
  it("parses sidecar NDJSON into CoreEvent objects", () => {
    const events = parseNdjsonEvents(
      [
        '{"version":1,"request_id":"req-1","event":{"type":"status","data":{"message":"正在分析场景"}}}',
        '{"version":1,"request_id":"req-1","event":{"type":"done","data":{"text":"优化结果","scene":"email"}}}'
      ].join("\n")
    );

    expect(events).toEqual([
      { type: "status", data: { message: "正在分析场景" } },
      { type: "done", data: { text: "优化结果", scene: "email" } }
    ]);
  });

  it("keeps compatibility with bare CoreEvent lines during frontend-only previews", () => {
    expect(parseNdjsonEvents('{"type":"chunk","data":{"text":"片段"}}')).toEqual([
      { type: "chunk", data: { text: "片段" } }
    ]);
  });

  it("rejects unknown event types from a host bridge", () => {
    expect(() => parseNdjsonEvents('{"type":"debug","data":{}}')).toThrow(
      "Unknown Core event type"
    );
  });

  it("creates Runtime optimize and cancel command envelopes", () => {
    const request = {
      ...createDraftRequest("写一封邮件"),
      style: "concise" as const,
      provider: "minimax"
    };

    expect(createOptimizeCommand("req-1", request)).toEqual({
      version: 1,
      request_id: "req-1",
      type: "optimize",
      payload: request
    });
    expect(createCancelCommand("req-1")).toEqual({
      version: 1,
      request_id: "req-1",
      type: "cancel",
      payload: {}
    });
  });

  it("filters stale Runtime events by active request id", () => {
    const envelopes = parseNdjsonEnvelopes(
      [
        '{"version":1,"request_id":"old","event":{"type":"chunk","data":{"text":"旧结果"}}}',
        '{"version":1,"request_id":"active","event":{"type":"chunk","data":{"text":"新结果"}}}'
      ].join("\n")
    );

    expect(selectEventsForRequest(envelopes, "active")).toEqual([
      { type: "chunk", data: { text: "新结果" } }
    ]);
  });
});
