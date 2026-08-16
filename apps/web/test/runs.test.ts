import { describe, expect, it } from "vitest";

import { createIdempotencyKey } from "../src/api";
import { dedupeRuns, hasUsableNextPage, isCursorResetError, resetRunsList } from "../src/runs";
import type { RunItem } from "../src/types";

function run(runKey: string): RunItem {
  return {
    runKey,
    state: "pending",
    requestedAt: "2024-01-02T08:00:00Z",
    startedAt: null,
    finishedAt: null,
    counts: {
      recordsSeen: null,
      recordsAccepted: null,
      recordsRejected: null,
      recordsDuplicated: null,
      fieldsUnsupported: null
    }
  };
}

describe("opaque run pagination", () => {
  it("deduplicates keys across pages", () => {
    const merged = dedupeRuns([run("verify-demo-01"), run("verify-demo-02")], [run("verify-demo-02"), run("verify-demo-03"), run("verify-demo-03")]);
    expect(merged.map((item) => item.runKey)).toEqual(["verify-demo-01", "verify-demo-02", "verify-demo-03"]);
  });

  it("rejects missing, malformed, and already requested cursors", () => {
    expect(hasUsableNextPage({ hasNext: true, nextCursor: null, seenCursors: new Set() })).toBe(false);
    expect(hasUsableNextPage({ hasNext: true, nextCursor: "\u0000bad", seenCursors: new Set() })).toBe(false);
    expect(hasUsableNextPage({ hasNext: true, nextCursor: "cursor-demo-02", seenCursors: new Set(["cursor-demo-02"]) })).toBe(false);
    expect(hasUsableNextPage({ hasNext: true, nextCursor: "cursor-demo-02", seenCursors: new Set() })).toBe(true);
  });

  it("resets list state without discarding the held creation key", () => {
    const createKey = createIdempotencyKey();
    const reset = resetRunsList({ items: [run("verify-demo-01")], nextCursor: "cursor-demo-02", hasNext: true, loadingMore: true, error: { code: "NETWORK_ERROR" } as never, createError: { code: "RATE_LIMITED" } as never, createKey, creating: false, filters: { from: "", to: "", state: "" }, seenCursors: new Set(["cursor-demo-02"]) });
    expect(reset.items).toEqual([]);
    expect(reset.nextCursor).toBe(null);
    expect(reset.hasNext).toBe(false);
    expect(reset.loadingMore).toBe(false);
    expect(reset.error).toBe(null);
    expect(reset.createError).toBe(null);
    expect(reset.createKey).toBe(createKey);
    expect(reset.seenCursors).toEqual(new Set());
  });

  it("classifies cursor failures as reset candidates", () => {
    expect(isCursorResetError({ code: "INVALID_CURSOR" } as never)).toBe(true);
    expect(isCursorResetError({ code: "CURSOR_CONTEXT_MISMATCH" } as never)).toBe(true);
    expect(isCursorResetError({ code: "CURSOR_EXPIRED" } as never)).toBe(true);
    expect(isCursorResetError({ code: "NETWORK_ERROR" } as never)).toBe(false);
  });
});
