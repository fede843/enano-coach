import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_ROUTES,
  ApiError,
  InvalidResponse,
  buildApiUrl,
  createIdempotencyKey,
  createVerificationRun,
  getOverview,
  getRuns,
  getSettings,
  parseEnvelope,
  parseOverviewEnvelope,
  parseActivityTrendEnvelope,
  parseRunDetailEnvelope,
  parseRetryAfter,
  parseRunsEnvelope,
  parseSession,
  parseSettingsEnvelope
} from "../src/api";
import type { Envelope } from "../src/types";

function envelope(data: unknown, overrides: Record<string, unknown> = {}): Envelope {
  return {
    schemaVersion: "1",
    asOf: "2024-01-02T12:30:00Z",
    timezone: "UTC",
    data,
    coverage: {},
    warnings: [],
    extensions: {},
    ...overrides
  } as Envelope;
}

function metric(state: string, value: number | null, unit: string | null, isDailyTotal: boolean | null, extra: Record<string, unknown> = {}) {
  return { state, value, unit, isDailyTotal, ...extra };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("BFF client and parser", () => {
  function trendEnvelope(overrides: Record<string, unknown> = {}): Envelope {
    const dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07"];
    const point = (state = "value", value: number | null = 1, unit: string | null = "count") => ({ state, value, unit });
    return envelope({
      logicalDate: "2024-01-07",
      range: "7d",
      steps: { unit: "count", totalObserved: 7, averageObserved: 1, observedDays: 7, expectedDays: 7 },
      distanceMeters: { unit: "meters", totalObserved: 14, averageObserved: 2, observedDays: 7, expectedDays: 7 },
      points: dates.map((date) => ({ date, steps: point(), distanceMeters: point("value", 2, "meters") }))
    }, overrides);
  }

  it("rejects a trend whose dates are not the exact ascending seven-day window", () => {
    const invalid = trendEnvelope();
    const data = invalid.data as Record<string, unknown>;
    data.points = [...(data.points as unknown[]).slice(1), (data.points as unknown[])[0]];
    expect(() => parseActivityTrendEnvelope(invalid, { date: "2024-01-07", timezone: "UTC" })).toThrow(InvalidResponse);
  });

  it("rejects trend point state, value, and unit contradictions", () => {
    const invalid = trendEnvelope();
    const data = invalid.data as Record<string, unknown>;
    (data.points as Array<Record<string, unknown>>)[0].steps = { state: "zero", value: 1, unit: "count" };
    expect(() => parseActivityTrendEnvelope(invalid)).toThrow(InvalidResponse);
  });

  it("requires the exact bucket mode for each trend range", () => {
    for (const [range, bucketMode] of [
      ["daily", "daily"],
      ["7d", "daily"],
      ["monthly", "daily"],
      ["180d", "calendar-month"],
      ["annual", "calendar-month"]
    ] as const) {
      const valid = trendEnvelope({
        data: {
          ...(trendEnvelope().data as Record<string, unknown>),
          range,
          bucketMode,
          points: range === "7d"
            ? (trendEnvelope().data as Record<string, unknown>).points
            : []
        }
      });
      if (range === "7d") expect(() => parseActivityTrendEnvelope(valid)).not.toThrow();
    }

    for (const range of ["daily", "7d", "monthly"] as const) {
      const invalid = trendEnvelope({ data: { ...(trendEnvelope().data as Record<string, unknown>), range, bucketMode: "calendar-month" } });
      expect(() => parseActivityTrendEnvelope(invalid)).toThrow(InvalidResponse);
    }
    for (const range of ["180d", "annual"] as const) {
      const invalid = trendEnvelope({ data: { ...(trendEnvelope().data as Record<string, unknown>), range, bucketMode: "daily" } });
      expect(() => parseActivityTrendEnvelope(invalid)).toThrow(InvalidResponse);
    }
  });

  it("parses the annual calendar-month response", () => {
    const base = trendEnvelope().data as Record<string, unknown>;
    const points = Array.from({ length: 12 }, (_, index) => ({
      date: `2026-${String(index + 1).padStart(2, "0")}-01`,
      steps: { state: index === 7 ? "value" : "empty", value: index === 7 ? 800 : null, unit: index === 7 ? "count" : null },
      distanceMeters: { state: "empty", value: null, unit: null }
    }));
    const parsed = parseActivityTrendEnvelope(envelope({
      ...base,
      logicalDate: "2026-08-03",
      range: "annual",
      bucketMode: "calendar-month",
      steps: { unit: "count", totalObserved: 800, averageObserved: 800, observedDays: 1, expectedDays: 365 },
      distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 365 },
      points
    }), { date: "2026-08-03", timezone: "UTC" });
    expect(parsed.data?.range).toBe("annual");
    expect(parsed.data?.points).toHaveLength(12);
  });

  it("parses 180d calendar-month points across a calendar year boundary", () => {
    const base = trendEnvelope().data as Record<string, unknown>;
    const points = ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"].map((date) => ({
      date,
      steps: { state: "empty", value: null, unit: null },
      distanceMeters: { state: "empty", value: null, unit: null }
    }));
    const parsed = parseActivityTrendEnvelope(envelope({
      ...base,
      logicalDate: "2026-05-15",
      range: "180d",
      bucketMode: "calendar-month",
      steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 180 },
      distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 180 },
      points
    }), { date: "2026-05-15", timezone: "UTC" });
    expect(parsed.data?.points.map((point) => point.date)).toEqual(points.map((point) => point.date));
  });

  it("accepts a numeric partial trend point for compatibility", () => {
    const valid = trendEnvelope();
    const data = valid.data as Record<string, unknown>;
    (data.points as Array<Record<string, unknown>>)[0].steps = {
      state: "partial",
      value: 0,
      unit: "count"
    };
    const parsed = parseActivityTrendEnvelope(valid);
    expect((parsed.data?.points[0].steps)).toEqual({ state: "partial", value: 0, unit: "count" });
  });

  it("rejects negative trend values and aggregates", () => {
    const invalidPoint = trendEnvelope();
    ((invalidPoint.data as Record<string, unknown>).points as Array<Record<string, unknown>>)[0].steps = { state: "value", value: -1, unit: "count" };
    expect(() => parseActivityTrendEnvelope(invalidPoint)).toThrow(InvalidResponse);

    const invalidAggregate = trendEnvelope();
    ((invalidAggregate.data as Record<string, unknown>).steps as Record<string, unknown>).totalObserved = -1;
    expect(() => parseActivityTrendEnvelope(invalidAggregate)).toThrow(InvalidResponse);
  });

  it("builds only relative allowlisted paths", () => {
    expect(buildApiUrl(API_ROUTES.overview, { date: "2024-01-02", timezone: "UTC" })).toBe("/api/v1/me/verify/overview?date=2024-01-02&timezone=UTC");
    expect(() => buildApiUrl(API_ROUTES.settings, { userId: "not-allowed" })).toThrow(InvalidResponse);
    expect(() => buildApiUrl(API_ROUTES.runs, { timezone: "UTC" })).toThrow(InvalidResponse);
    expect(() => buildApiUrl("https://provider.example.test/data", {})).toThrow(InvalidResponse);
  });

  it("rejects unknown top-level response fields and browser identity fields", () => {
    expect(() => parseOverviewEnvelope(envelope({ user_id: "not-a-browser-field" }))).toThrow(InvalidResponse);
    expect(() => parseEnvelope({ ...envelope({}), privatePayload: { message: "not public" } })).toThrow(InvalidResponse);
  });

  it("discards hostile warning and error prose before it can render", () => {
    const warningResponse = envelope(
      { logicalDate: "2024-01-02", summary: {} },
      { warnings: [{ code: "PARTIAL_COVERAGE", severity: "warning", message: "<img src=x onerror=alert(1)>", domain: "activity" }] }
    );
    expect(parseEnvelope(warningResponse).warnings[0]).toEqual({ code: "PARTIAL_COVERAGE", severity: "warning", domain: "activity" });
    const errorResponse = envelope(null, { error: { code: "UPSTREAM_TIMEOUT", message: "<script>alert(1)</script>", requestId: "req-demo-hostile", retryable: true, field: null } });
    expect("message" in (parseEnvelope(errorResponse).error || {})).toBe(false);
  });

  it("drops unknown extension namespaces while preserving the allowlist", () => {
    const parsed = parseEnvelope(envelope({ logicalDate: "2024-01-02", summary: {} }, { extensions: { future: { privatePath: "drop" } } }));
    expect(parsed.extensions).toEqual({});
  });

  it("preserves value, real zero, null, partial, unsupported, and ambiguous states", () => {
    const parsed = parseOverviewEnvelope(envelope({
      logicalDate: "2024-01-02",
      summary: {
        steps: metric("value", 8123, "count", true),
        distanceMeters: metric("partial", 5300, "meters", true, { coverage: { expectedDays: 1, availableDays: 1, observedFraction: 0.5 } }),
        activeCaloriesKcal: metric("zero", 0, "kcal", true),
        recoveryScore: metric("null", null, null, false),
        stress: metric("unsupported", null, null, null),
        heartRate: metric("source_ambiguous", 72, "bpm", false)
      }
    }));
    expect(parsed.data?.summary.activeCaloriesKcal?.value).toBe(0);
    expect(parsed.data?.summary.recoveryScore?.value).toBe(null);
    expect(parsed.data?.summary.distanceMeters?.coverage?.observedFraction).toBe(0.5);
    expect(parsed.data?.summary.heartRate?.value).toBe(72);
  });

  it("keeps scalar heart rate scalar and recovery unitless", () => {
    expect(() => parseOverviewEnvelope(envelope({ logicalDate: "2024-01-02", summary: { heartRate: { state: "value", value: 72, unit: "bpm", isDailyTotal: false, avgBpm: 72 } } }))).toThrow(InvalidResponse);
    expect(() => parseOverviewEnvelope(envelope({ logicalDate: "2024-01-02", summary: { recoveryScore: metric("value", 82, "percent", false) } }))).toThrow(InvalidResponse);
  });

  it("rejects contradictory session access flags", () => {
    expect(() => parseSession(envelope({ authenticated: false, accessState: "active", canReadVerification: true }))).toThrow(InvalidResponse);
  });

  it("validates opaque continuation semantics", () => {
    const page = parseRunsEnvelope(envelope({ items: [{ runKey: "verify-demo-01", state: "pending", requestedAt: "2024-01-02T08:00:00Z", startedAt: null, finishedAt: null, counts: { recordsSeen: null, recordsAccepted: null, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null } }], page: { nextCursor: "opaque-cursor-from-bff", hasNext: true, totalCount: null } }));
    expect(page.data?.page.nextCursor).toBe("opaque-cursor-from-bff");
    expect(() => parseRunsEnvelope(envelope({ items: [], page: { nextCursor: null, hasNext: true, totalCount: null } }))).toThrow(InvalidResponse);
  });

  it("uses stable copy for errors instead of response prose", () => {
    const parsed = parseEnvelope(envelope(null, { error: { code: "UPSTREAM_TIMEOUT", message: "provider internals", requestId: "req-demo-001", retryable: true, field: null } }));
    const error = new ApiError({ status: 504, code: parsed.error?.code, requestId: parsed.error?.requestId, retryable: parsed.error?.retryable });
    expect(error.message).toBe("La fuente tardó demasiado en responder.");
    expect(error.requestId).toBe("req-demo-001");
  });

  it("accepts only the current synthetic OW reference value", () => {
    const settings = {
      contract: "bff-ui-v1",
      versions: { bffSchema: "1", owReference: "not_pinned" },
      capabilities: { gps: "not_verifiable", workoutDetails: "aggregate_only", segments: "not_verifiable", hrZones: "not_verifiable" },
      technicalState: "ready"
    };
    expect(parseSettingsEnvelope(envelope(settings)).data?.versions.owReference).toBe("not_pinned");
  });

  it("fails closed for hostile OW reference URL, path, and credential-like values", () => {
    const hostileValues = ["https://example.test/ow/reference", "/srv/example-service/ow", "Authorization: <redacted>"];
    for (const owReference of hostileValues) {
      const parsed = parseSettingsEnvelope(envelope({
        contract: "bff-ui-v1",
        versions: { bffSchema: "1", owReference },
        capabilities: { gps: "not_verifiable", workoutDetails: "aggregate_only", segments: "not_verifiable", hrZones: "not_verifiable" },
        technicalState: "ready"
      }));
      expect(parsed.data?.versions.owReference).toBe("not_pinned");
    }
  });

  it("parses bounded Retry-After values", () => {
    const now = Date.parse("2024-01-02T12:30:00Z");
    expect(parseRetryAfter("5", now)).toBe(5_000);
    expect(parseRetryAfter("Wed, 02 Jan 2024 12:30:07 GMT", now)).toBe(7_000);
    expect(parseRetryAfter("not-a-deadline", now)).toBe(null);
  });

  it("creates unique in-memory idempotency keys", () => {
    const first = createIdempotencyKey();
    const second = createIdempotencyKey();
    expect(typeof first).toBe("object");
    expect(typeof second).toBe("object");
    expect(first).not.toBe(second);
  });

  it("rejects a forged idempotency value before sending a POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("must not fetch"));
    await expect(createVerificationRun({
      date: "2024-01-02",
      timezone: "UTC",
      domains: ["activity"],
      idempotencyKey: "verify-ui-key-forged" as never
    })).rejects.toMatchObject({ code: "INVALID_QUERY", field: "Idempotency-Key", retryable: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reuses one branded key for an explicit retry and generates a different key for a new run", async () => {
    const responseBody = JSON.stringify(envelope({
      verificationRun: {
        runKey: "verify-demo-05",
        state: "pending",
        requestedAt: "2024-01-02T12:30:00Z",
        startedAt: null,
        finishedAt: null,
        scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
        counts: { recordsSeen: null, recordsAccepted: null, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null },
        warnings: []
      }
    }));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(responseBody, { status: 202, headers: { "Content-Type": "application/json" } }));
    const firstKey = createIdempotencyKey();
    const secondKey = createIdempotencyKey();
    await createVerificationRun({ date: "2024-01-02", timezone: "UTC", domains: ["activity"], idempotencyKey: firstKey });
    await createVerificationRun({ date: "2024-01-02", timezone: "UTC", domains: ["activity"], idempotencyKey: firstKey });
    await createVerificationRun({ date: "2024-01-02", timezone: "UTC", domains: ["activity"], idempotencyKey: secondKey });
    const headers = fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get("Idempotency-Key"));
    expect(headers[0]).toBe(headers[1]);
    expect(headers[2]).not.toBe(headers[0]);
  });

  it("fails closed without Web Crypto and does not send a POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("must not fetch"));
    vi.stubGlobal("crypto", undefined);
    await expect(createVerificationRun({ date: "2024-01-02", timezone: "UTC", domains: ["activity"] })).rejects.toMatchObject({ code: "CLIENT_CRYPTO_UNAVAILABLE", retryable: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a forged crypto source and never authorizes a POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("must not fetch"));
    vi.stubGlobal("crypto", { randomUUID: () => "caller-controlled-idempotency-value" });
    await expect(createVerificationRun({ date: "2024-01-02", timezone: "UTC", domains: ["activity"] })).rejects.toMatchObject({ code: "CLIENT_CRYPTO_UNAVAILABLE", retryable: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects invalid filters without fetching and marks them non-retryable", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("must not fetch"));
    await expect(getRuns({ from: "2024-01-04", to: "2024-01-02" })).rejects.toMatchObject({ code: "INVALID_QUERY", field: "from", retryable: false });
    await expect(getRuns({ state: "raw-provider-state" })).rejects.toMatchObject({ code: "INVALID_QUERY", field: "state", retryable: false });
    await expect(getOverview({ date: "2024-02-31", timezone: "UTC" })).rejects.toMatchObject({ code: "INVALID_QUERY", field: "date", retryable: false });
    await expect(createVerificationRun({ date: "2024-01-02", timezone: "Not/AZone", domains: ["activity"] })).rejects.toMatchObject({ code: "INVALID_QUERY", field: "timezone", retryable: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects unknown run filter keys instead of silently dropping them", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("must not fetch"));
    await expect(getRuns({ unexpectedFilter: "drop-me" })).rejects.toMatchObject({
      status: 400,
      code: "INVALID_QUERY",
      field: null,
      retryable: false
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects metric-specific semantic contradictions without inventing bounds", () => {
    const invalidMetrics = [
      { steps: metric("value", 1.5, "count", true) },
      { steps: metric("value", -1, "count", true) },
      { steps: metric("value", 0, "count", true) },
      { distanceMeters: metric("value", -0.1, "meters", false) },
      { activeCaloriesKcal: metric("value", -1, "kcal", true) },
      { sleepDurationSeconds: metric("value", 1.5, "seconds", false) },
      { recoveryScore: metric("value", 82.5, null, false) },
      { recoveryScore: metric("value", 0, null, false) },
      { recoveryScore: metric("value", 101, null, false) },
      { heartRate: metric("value", -1, "bpm", false) }
    ];
    for (const summaryMetric of invalidMetrics) {
      expect(() => parseOverviewEnvelope(envelope({ logicalDate: "2024-01-02", summary: summaryMetric }))).toThrow(InvalidResponse);
    }
  });

  it("accepts valid zero, null, partial, unsupported, ambiguous, pending, and unitless recovery states", () => {
    const parsed = parseOverviewEnvelope(envelope({
      logicalDate: "2024-01-02",
      summary: {
        steps: metric("zero", 0, "count", true),
        distanceMeters: metric("partial", 0.5, "meters", false, { coverage: { expectedDays: 2, availableDays: 1, observedFraction: 0.25 } }),
        activeCaloriesKcal: metric("null", null, null, false),
        sleepDurationSeconds: metric("pending", null, null, null),
        recoveryScore: metric("zero", 0, null, false),
        stress: metric("unsupported", null, null, null),
        heartRate: metric("source_ambiguous", 72, "bpm", false)
      }
    }));
    expect(parsed.data?.summary.steps?.state).toBe("zero");
    expect(parsed.data?.summary.distanceMeters?.state).toBe("partial");
    expect(parsed.data?.summary.recoveryScore?.unit).toBe(null);
    expect(parsed.data?.summary.heartRate?.value).toBe(72);
  });

  it("rejects impossible verification-run chronology and terminal/pending states", () => {
    const baseRun = {
      runKey: "verify-demo-05",
      state: "persisted",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: []
    };
    const variants = [
      { ...baseRun, startedAt: "not-a-timestamp" },
      { ...baseRun, startedAt: "2024-01-02T12:29:59Z" },
      { ...baseRun, startedAt: null },
      { ...baseRun, finishedAt: "2024-01-02T12:30:00Z" },
      { ...baseRun, finishedAt: null },
      { ...baseRun, state: "pending", finishedAt: "2024-01-02T12:30:02Z" },
      { ...baseRun, state: "completed_with_findings" },
      { ...baseRun, results: [{ metric: "steps", state: "mismatch", expected: 1, observed: 2, unit: "count", expectedIsDailyTotal: true, observedIsDailyTotal: true }] }
    ];
    for (const verificationRun of variants) {
      expect(() => parseRunDetailEnvelope(envelope({ verificationRun }))).toThrow(InvalidResponse);
    }
  });

  it("rejects invalid calendar instants and an envelope produced before its run", () => {
    const run = {
      runKey: "verify-demo-05",
      state: "persisted",
      requestedAt: "2024-02-31T12:30:00Z",
      startedAt: "2024-03-03T12:30:01Z",
      finishedAt: "2024-03-03T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: []
    };
    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: run }))).toThrow(InvalidResponse);

    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...run,
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z"
    } }, { asOf: "2024-01-02T12:29:59Z" }))).toThrow(InvalidResponse);
  });

  it("rejects result reason codes that contradict their result state", () => {
    const base = {
      runKey: "verify-demo-08",
      state: "inconclusive",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null },
      warnings: [{ code: "INCONCLUSIVE", severity: "warning", message: "ignored" }]
    };
    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...base,
      results: [{ metric: "steps", state: "inconclusive", reasonCode: "NO_PUBLIC_WORKOUT_DETAIL" }]
    } }))).toThrow(InvalidResponse);
    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...base,
      results: [{ metric: "extended_workout_detail", state: "not_verifiable", reasonCode: "CURSOR_EXPIRED" }]
    } }))).toThrow(InvalidResponse);
  });

  it("rejects contradictory partial results while preserving valid findings and warnings", () => {
    const partialRun = {
      runKey: "verify-demo-02",
      state: "partial",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 2, recordsAccepted: 1, recordsRejected: 1, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: [{ code: "PARTIAL_COVERAGE", severity: "warning", message: "ignored" }],
      results: [{ metric: "steps", state: "match" }]
    };
    const parsed = parseRunDetailEnvelope(envelope({ verificationRun: partialRun }, { asOf: "2024-01-02T12:30:03Z" }));
    expect(parsed.data?.verificationRun.results).toEqual([{ metric: "steps", state: "match" }]);
    expect(parsed.data?.verificationRun.warnings).toEqual([{ code: "PARTIAL_COVERAGE", severity: "warning" }]);

    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...partialRun,
      results: [{ metric: "steps", state: "mismatch", expected: 1, observed: 2, unit: "count", expectedIsDailyTotal: true, observedIsDailyTotal: true }]
    } }, { asOf: "2024-01-02T12:30:03Z" }))).toThrow(InvalidResponse);
    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...partialRun,
      results: [{ metric: "steps", state: "inconclusive", reasonCode: "CURSOR_EXPIRED" }]
    } }, { asOf: "2024-01-02T12:30:03Z" }))).toThrow(InvalidResponse);
  });

  it("allows an explicit inconclusive result only for an inconclusive run", () => {
    const run = {
      runKey: "verify-demo-08",
      state: "inconclusive",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null },
      warnings: [{ code: "INCONCLUSIVE", severity: "warning", message: "ignored" }],
      results: [{ metric: "steps", state: "inconclusive", reasonCode: "CURSOR_EXPIRED" }]
    };
    const parsed = parseRunDetailEnvelope(envelope({ verificationRun: run }, { asOf: "2024-01-02T12:30:03Z" }));
    expect(parsed.data?.verificationRun.results?.[0].state).toBe("inconclusive");
  });

  it("accepts closed matches alongside a closed mismatch", () => {
    const parsed = parseRunDetailEnvelope(envelope({ verificationRun: {
      runKey: "verify-demo-07",
      state: "completed_with_findings",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 2, recordsAccepted: 2, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: [{ code: "MISMATCH", severity: "warning", message: "ignored" }],
      results: [
        { metric: "steps", state: "match" },
        { metric: "steps", state: "mismatch", expected: 1, observed: 2, unit: "count", expectedIsDailyTotal: true, observedIsDailyTotal: true }
      ]
    } }, { asOf: "2024-01-02T12:30:03Z" }));
    expect(parsed.data?.verificationRun.results?.map((result) => result.state)).toEqual(["match", "mismatch"]);
  });

  it("accepts valid pending and completed-with-findings verification runs", () => {
    const pending = parseRunDetailEnvelope(envelope({ verificationRun: {
      runKey: "verify-demo-05",
      state: "pending",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: null,
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: null, recordsAccepted: null, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null },
      warnings: []
    } }, { asOf: "2024-01-02T12:30:03Z" }));
    const findings = parseRunDetailEnvelope(envelope({ verificationRun: {
      runKey: "verify-demo-07",
      state: "completed_with_findings",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: [{ code: "MISMATCH", severity: "warning", message: "ignored" }],
      results: [{ metric: "steps", state: "mismatch", expected: 1, observed: 2, unit: "count", expectedIsDailyTotal: true, observedIsDailyTotal: true }]
    } }, { asOf: "2024-01-02T12:30:03Z" }));
    expect(pending.data?.verificationRun.state).toBe("pending");
    expect(findings.data?.verificationRun.state).toBe("completed_with_findings");
  });

  it("rejects every lifecycle timestamp that is after the response asOf", () => {
    const run = {
      runKey: "verify-demo-05",
      state: "persisted",
      requestedAt: "2024-01-02T12:30:00Z",
      startedAt: "2024-01-02T12:30:01Z",
      finishedAt: "2024-01-02T12:30:02Z",
      scope: { date: "2024-01-02", timezone: "UTC", domains: ["activity"] },
      counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 },
      warnings: []
    };
    for (const field of ["requestedAt", "startedAt", "finishedAt"] as const) {
      expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
        ...run,
        [field]: "2024-01-02T12:30:04Z"
      } }, { asOf: "2024-01-02T12:30:03Z" }))).toThrow(InvalidResponse);
    }
    for (const field of ["startedAt", "finishedAt"] as const) {
      expect(() => parseRunsEnvelope(envelope({
        items: [{ ...run, [field]: "2024-01-02T12:30:04Z" }],
        page: { nextCursor: null, hasNext: false, totalCount: null }
      }, { asOf: "2024-01-02T12:30:03Z" }))).toThrow(InvalidResponse);
    }
    expect(() => parseRunDetailEnvelope(envelope({ verificationRun: {
      ...run,
      finishedAt: "2024-01-02T12:30:00.500Z"
    } }, { asOf: "2024-01-02T12:30:03Z" }))).toThrow(InvalidResponse);
  });

  it("passes AbortSignal through and preserves cancellation", async () => {
    const controller = new AbortController();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      expect(init?.signal).toBe(controller.signal);
      const error = new Error("aborted");
      error.name = "AbortError";
      throw error;
    });
    await expect(getSettings({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });

  it("exposes Retry-After from a rate-limited BFF response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(envelope(null, { error: { code: "RATE_LIMITED", message: "ignored", requestId: "req-demo-rate-limit", retryable: true, field: null } })), { status: 429, headers: { "Content-Type": "application/json", "Retry-After": "5" } }));
    await expect(getSettings()).rejects.toMatchObject({ code: "RATE_LIMITED", retryAfterMs: 5_000 });
  });

  it("uses the sole BFF mutation with a stable key and no runs timezone query", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(envelope({
      verificationRun: {
        runKey: "verify-demo-05",
        state: "pending",
        requestedAt: "2024-01-02T12:30:00Z",
        startedAt: null,
        finishedAt: null,
        scope: { date: "2024-01-02", timezone: "Europe/Madrid", domains: ["activity"] },
        counts: { recordsSeen: null, recordsAccepted: null, recordsRejected: null, recordsDuplicated: null, fieldsUnsupported: null },
        warnings: []
      }
    }, { timezone: "Europe/Madrid" })), { status: 202, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }));
    const key = createIdempotencyKey();
    const result = await createVerificationRun({ date: "2024-01-02", timezone: "Europe/Madrid", domains: ["activity"], idempotencyKey: key });
    expect(result.data?.verificationRun.state).toBe("pending");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe(API_ROUTES.runs);
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toMatch(/^verify-ui-key-/);
    expect(JSON.parse(String(init?.body))).toEqual({ date: "2024-01-02", timezone: "Europe/Madrid", domains: ["activity"] });
    expect(String(path)).not.toContain("timezone=");
  });
});
