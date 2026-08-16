import { describe, expect, it } from "vitest";

import { RequestGate } from "../src/request-gate";

describe("request identity gate", () => {
  it("aborts and invalidates the older request", () => {
    const gate = new RequestGate();
    const first = gate.begin("overview");
    const second = gate.begin("overview");
    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.signal.aborted).toBe(false);
    expect(second.isCurrent()).toBe(true);
  });

  it("cancels all route requests so stale results cannot apply", () => {
    const gate = new RequestGate();
    const overview = gate.begin("overview");
    const runs = gate.begin("runs");
    gate.cancelAll();
    expect(overview.signal.aborted).toBe(true);
    expect(runs.signal.aborted).toBe(true);
    expect(overview.isCurrent()).toBe(false);
    expect(runs.isCurrent()).toBe(false);
  });
});
