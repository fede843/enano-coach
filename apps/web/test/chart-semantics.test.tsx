import { describe, expect, it } from "vitest";

import {
  sleepDurationAxisTicks,
  sleepAxisTickPosition,
  sleepDurationValue,
  sleepDurationGuidePosition,
  sleepDurationMaximum,
  sleepNightDurationMaximum,
  sleepStageSegments,
  sleepHourTicks,
  sleepGuidePosition,
  sleepSchedulePosition,
  trendAxisTickLabel,
  trendAxisTicks,
  trendMetricAxisMaximum
} from "../src/view";
import type { MetricState, SleepTrendPoint } from "../src/types";

const point = (night: number | null, nap: number | null = null): SleepTrendPoint => ({
  date: "2026-08-03",
  nightSleepSeconds: { state: (night === null ? "empty" : "value") as MetricState, value: night, unit: "seconds" as const },
  napsSeconds: { state: (nap === null ? "empty" : "value") as MetricState, value: nap, unit: "seconds" as const },
  stages: {
    awakeSeconds: { state: "unsupported" as MetricState, value: null, unit: null },
    lightSeconds: { state: "unsupported" as MetricState, value: null, unit: null },
    deepSeconds: { state: "unsupported" as MetricState, value: null, unit: null },
    remSeconds: { state: "unsupported" as MetricState, value: null, unit: null }
  },
  bedtime: "2026-08-03T23:00:00Z",
  wakeTime: "2026-08-04T06:00:00Z"
});

describe("chart semantics", () => {
  it("uses exact even-hour ticks in a data-derived schedule", () => {
    expect(sleepHourTicks({ min: 22, max: 36 })).toEqual([36, 34, 32, 30, 28, 26, 24, 22]);
    expect(sleepAxisTickPosition(36, { min: 22, max: 36 })).toBe("0%");
    expect(sleepAxisTickPosition(22, { min: 22, max: 36 })).toBe("100%");
    expect(Number.parseFloat(sleepSchedulePosition("2026-08-03T23:00:00Z", "2026-08-04T06:00:00Z", "UTC", { min: 22, max: 36 })?.top || "0")).toBeCloseTo(42.8571, 3);
    expect(Number.parseFloat(sleepSchedulePosition("2026-08-03T23:00:00Z", "2026-08-04T06:00:00Z", "UTC", { min: 22, max: 36 })?.height || "0")).toBeCloseTo(50, 3);
  });

  it("omits schedule guides that cannot be represented in the bounded window", () => {
    expect(sleepSchedulePosition("2026-08-03T15:00:00Z", "2026-08-04T06:00:00Z", "UTC", { min: 23, max: 35 })).toBeNull();
  });

  it("keeps a valid overnight bar through a late wake time", () => {
    expect(sleepSchedulePosition("2026-08-01T05:06:00Z", "2026-08-01T15:07:00Z", "America/Argentina/Buenos_Aires", { min: 22, max: 38 })).toEqual({ top: "11.770833333333329%", height: "62.60416666666666%" });
  });

  it("omits average guides outside the fixed schedule domain instead of clamping them", () => {
    expect(sleepGuidePosition(15, 23, { min: 22, max: 38 })).toBeNull();
    expect(sleepGuidePosition(12, 35, { min: 22, max: 38 })).toBe("12.5%");
  });

  it("keeps comparable guides when the other average is outside the domain", () => {
    expect(sleepGuidePosition(23, 23, { min: 22, max: 38 })).toBe("93.75%");
    expect(sleepGuidePosition(6, 35, { min: 22, max: 38 })).toBe("50%");
  });

  it("uses a clean night-only duration scale even when naps exist", () => {
    const points = [point(25_200, 7_200), point(21_600, null)];
    expect(sleepNightDurationMaximum(points)).toBe(28_800);
    expect(sleepDurationAxisTicks(25_200)).toEqual([28_800, 21_600, 14_400, 7_200, 0]);
    expect(sleepDurationGuidePosition(25_200, 28_800)).toBe("87.5%");
  });

  it("segments validated night stages without folding naps into the night bar", () => {
    const staged = point(25_200, 1_800);
    staged.stages = {
      awakeSeconds: { state: "zero", value: 0, unit: "seconds" },
      lightSeconds: { state: "value", value: 12_600, unit: "seconds" },
      deepSeconds: { state: "value", value: 5_400, unit: "seconds" },
      remSeconds: { state: "value", value: 7_200, unit: "seconds" }
    };
    expect(sleepStageSegments(staged)).toEqual([
      { kind: "light", seconds: 12_600 },
      { kind: "deep", seconds: 5_400 },
      { kind: "rem", seconds: 7_200 }
    ]);
  });

  it("includes awake in the time-in-bed composition without changing sleep duration", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 12_600, unit: "seconds" },
      deepSeconds: { state: "value", value: 5_400, unit: "seconds" },
      remSeconds: { state: "value", value: 7_200, unit: "seconds" }
    };

    expect(sleepStageSegments(staged)).toEqual([
      { kind: "awake", seconds: 1_800 },
      { kind: "light", seconds: 12_600 },
      { kind: "deep", seconds: 5_400 },
      { kind: "rem", seconds: 7_200 }
    ]);
    expect(sleepDurationMaximum([staged])).toBe(27_000);
  });

  it("returns no stage segments when specific stages under-cover the night", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 7_200, unit: "seconds" },
      deepSeconds: { state: "value", value: 3_600, unit: "seconds" },
      remSeconds: { state: "value", value: 3_600, unit: "seconds" }
    };

    expect(sleepStageSegments(staged)).toEqual([]);
  });

  it("returns no stage segments when specific stages over-cover the night", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 14_400, unit: "seconds" },
      deepSeconds: { state: "value", value: 7_200, unit: "seconds" },
      remSeconds: { state: "value", value: 7_200, unit: "seconds" }
    };

    expect(sleepStageSegments(staged)).toEqual([]);
    expect(sleepDurationMaximum([staged])).toBe(1);
  });

  it("renders specific stages only when they exactly equal the night", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 12_600, unit: "seconds" },
      deepSeconds: { state: "value", value: 5_400, unit: "seconds" },
      remSeconds: { state: "value", value: 7_200, unit: "seconds" }
    };

    expect(sleepStageSegments(staged)).toEqual([
      { kind: "awake", seconds: 1_800 },
      { kind: "light", seconds: 12_600 },
      { kind: "deep", seconds: 5_400 },
      { kind: "rem", seconds: 7_200 }
    ]);
  });

  it("renders explicit generic sleep with specific stages only at exact equality", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 7_200, unit: "seconds" },
      deepSeconds: { state: "value", value: 3_600, unit: "seconds" },
      remSeconds: { state: "value", value: 3_600, unit: "seconds" }
    };

    expect(sleepStageSegments(staged, 10_800)).toEqual([
      { kind: "awake", seconds: 1_800 },
      { kind: "night", seconds: 10_800 },
      { kind: "light", seconds: 7_200 },
      { kind: "deep", seconds: 3_600 },
      { kind: "rem", seconds: 3_600 }
    ]);
    expect(sleepStageSegments(point(25_200), 25_200)).toEqual([{ kind: "night", seconds: 25_200 }]);
  });

  it("does not invent generic sleeping when only an aggregate duration exists", () => {
    expect(sleepStageSegments(point(25_200))).toEqual([]);
  });

  it("renders an explicit unclassified remainder without inventing a sleep stage", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "value", value: 1_800, unit: "seconds" },
      lightSeconds: { state: "value", value: 10_800, unit: "seconds" },
      deepSeconds: { state: "value", value: 3_600, unit: "seconds" },
      remSeconds: { state: "null", value: null, unit: null }
    };
    (staged as SleepTrendPoint & { unclassifiedSeconds: SleepTrendPoint["nightSleepSeconds"] }).unclassifiedSeconds = {
      state: "value",
      value: 10_800,
      unit: "seconds"
    };

    expect(sleepStageSegments(staged)).toEqual([
      { kind: "awake", seconds: 1_800 },
      { kind: "unclassified", seconds: 10_800 },
      { kind: "light", seconds: 10_800 },
      { kind: "deep", seconds: 3_600 }
    ]);
  });

  it("does not render an unclassified segment for a zero remainder", () => {
    const staged = point(25_200);
    staged.stages = {
      awakeSeconds: { state: "zero", value: 0, unit: "seconds" },
      lightSeconds: { state: "value", value: 12_600, unit: "seconds" },
      deepSeconds: { state: "value", value: 5_400, unit: "seconds" },
      remSeconds: { state: "value", value: 7_200, unit: "seconds" }
    };
    staged.unclassifiedSeconds = { state: "zero", value: 0, unit: "seconds" };

    expect(sleepStageSegments(staged)).toEqual([
      { kind: "light", seconds: 12_600 },
      { kind: "deep", seconds: 5_400 },
      { kind: "rem", seconds: 7_200 }
    ]);
  });

  it("formats exact duration hours without a zero-minute suffix", () => {
    expect(sleepDurationValue(12 * 3600)).toBe("12 h");
    expect(sleepDurationValue(12 * 3600 + 15 * 60)).toBe("12 h 15 min");
  });

  it("keeps guide geometry on the same reversed schedule scale as bars", () => {
    const bar = sleepSchedulePosition("2026-08-03T23:00:00Z", "2026-08-04T06:00:00Z", "UTC", { min: 23, max: 35 });
    expect(bar?.top).toBe(sleepGuidePosition(6, 35, { min: 23, max: 35 }));
    expect(Number.parseFloat(bar?.top || "0") + Number.parseFloat(bar?.height || "0")).toBeCloseTo(100, 5);
  });

  it("uses clean count and metric ticks instead of data-derived midpoints", () => {
    expect(trendMetricAxisMaximum(8246, "steps")).toBe(10_000);
    expect(trendAxisTicks(8246, "steps")).toEqual([10_000, 8_000, 6_000, 4_000, 2_000, 0]);
    expect(trendMetricAxisMaximum(5400, "distanceMeters")).toBe(6000);
    expect(trendAxisTicks(5400, "distanceMeters")).toEqual([6000, 4000, 2000, 0]);
    expect(trendAxisTicks(8246, "steps")).not.toContain(4123);
    expect(trendAxisTicks(5400, "distanceMeters")).not.toContain(2700);
  });

  it("bounds long-range activity axes with evenly spaced nice integer ticks", () => {
    const maximum = 123_456;
    const ticks = trendAxisTicks(maximum, "steps");
    const intervals = ticks.slice(0, -1).map((tick, index) => tick - ticks[index + 1]);

    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks.length).toBeLessThanOrEqual(6);
    expect(ticks[0]).toBeGreaterThanOrEqual(maximum);
    expect(ticks.at(-1)).toBe(0);
    expect(new Set(ticks).size).toBe(ticks.length);
    expect(intervals.every((interval) => interval === intervals[0])).toBe(true);
    expect(intervals[0]).toBe(25_000);
    expect(ticks.every((tick) => Number.isFinite(tick) && Number.isInteger(tick))).toBe(true);
    expect(new Set(ticks.map((tick) => trendAxisTickLabel(tick, "steps"))).size).toBe(ticks.length);
  });

  it("bounds long-range sleep axes with readable hour-based ticks", () => {
    const maximum = 156 * 3600;
    const ticks = sleepDurationAxisTicks(maximum);
    const intervals = ticks.slice(0, -1).map((tick, index) => tick - ticks[index + 1]);

    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks.length).toBeLessThanOrEqual(6);
    expect(ticks[0]).toBeGreaterThanOrEqual(maximum);
    expect(ticks.at(-1)).toBe(0);
    expect(new Set(ticks).size).toBe(ticks.length);
    expect(intervals.every((interval) => interval === intervals[0])).toBe(true);
    expect(intervals[0] / 3600).toBe(50);
    expect(ticks.every(Number.isFinite)).toBe(true);
    expect(new Set(ticks.map(sleepDurationValue)).size).toBe(ticks.length);
  });

  it("keeps empty, tiny, and large axes finite and honest", () => {
    expect(trendAxisTicks(0, "steps")).toEqual([0]);
    expect(trendAxisTicks(Number.NaN, "steps")).toEqual([0]);
    expect(sleepDurationAxisTicks(0)).toEqual([0]);
    expect(sleepDurationAxisTicks(Number.POSITIVE_INFINITY)).toEqual([0]);

    for (const [maximum, ticks] of [
      [1, trendAxisTicks(1, "steps")],
      [9_876_543, trendAxisTicks(9_876_543, "steps")],
      [1, sleepDurationAxisTicks(1)],
      [365 * 24 * 3600, sleepDurationAxisTicks(365 * 24 * 3600)]
    ] as const) {
      expect(ticks[0]).toBeGreaterThanOrEqual(maximum);
      expect(ticks.at(-1)).toBe(0);
      expect(ticks.every(Number.isFinite)).toBe(true);
      expect(new Set(ticks).size).toBe(ticks.length);
      expect(ticks.every((tick, index) => index === 0 || tick < ticks[index - 1])).toBe(true);
    }
  });
});
