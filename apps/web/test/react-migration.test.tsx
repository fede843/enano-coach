import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { parseEnvelope, parseOverviewEnvelope, parseSession, parseSettingsEnvelope } from "../src/api";
import { initialState } from "../src/App";
import { AppView } from "../src/view";

function envelope(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "1" as const,
    asOf: "2024-01-02T12:30:00Z",
    timezone: "UTC",
    data,
    coverage: {},
    warnings: [],
    extensions: {},
    ...overrides
  };
}

const actions = {
  navigate: () => undefined,
  onRouteClick: () => undefined,
  onContextSubmit: () => undefined,
  onRunsSubmit: () => undefined,
  onAction: () => undefined
};

describe("React migration contract", () => {
  it("rejects hostile response prose and unknown browser fields before rendering", () => {
    const response = envelope(
      { logicalDate: "2024-01-02", summary: {} },
      {
        warnings: [{
          code: "PARTIAL_COVERAGE",
          severity: "warning",
          message: "<img src=x onerror=alert(1)>",
          domain: "activity"
        }],
        extensions: { future: { privateValue: "drop" } }
      }
    );

    const parsed = parseOverviewEnvelope(parseEnvelope(response));
    expect(parsed.warnings[0]).toEqual({
      code: "PARTIAL_COVERAGE",
      severity: "warning",
      domain: "activity"
    });
    expect(parsed.extensions).toEqual({});
    expect(() => parseEnvelope({ ...response, privatePayload: "drop" })).toThrow();
  });

  it("renders semantic landmarks and distinct zero, null, partial, unsupported, and mobile states", () => {
    const state = {
      route: { name: "overview" as const, path: "/verify" },
      context: { date: "2024-01-02", timezone: "UTC" },
      sessionStatus: "ready" as const,
      session: parseSession(envelope({ authenticated: true, accessState: "active", canReadVerification: true })),
      sessionError: null,
      retryUntil: null,
      retryError: null,
      page: {
        status: "ready" as const,
        envelope: parseOverviewEnvelope(envelope({
          logicalDate: "2024-01-02",
          summary: {
            steps: { state: "value", value: 8123, unit: "count", isDailyTotal: true },
            distanceMeters: {
              state: "partial",
              value: 5300,
              unit: "meters",
              isDailyTotal: true,
              coverage: { expectedDays: 1, availableDays: 1, observedFraction: 0.5 }
            },
            activeCaloriesKcal: { state: "zero", value: 0, unit: "kcal", isDailyTotal: true },
            recoveryScore: { state: "null", value: null, unit: null, isDailyTotal: false },
            stress: { state: "unsupported", value: null, unit: null, isDailyTotal: null },
            heartRate: { state: "source_ambiguous", value: 72, unit: "bpm", isDailyTotal: false }
          }
        }, {
          coverage: {
            requested: {
              logicalDate: "2024-01-02",
              from: "2024-01-02T00:00:00Z",
              to: "2024-01-03T00:00:00Z",
              timezone: "UTC"
            },
            expectedDays: 1,
            availableDays: 1,
            isPartial: true,
            byDomain: {}
          },
          warnings: [{ code: "PARTIAL_COVERAGE", severity: "warning", message: "ignored" }]
        })),
        error: null
      },
      runs: {
        filters: { from: "", to: "", state: "" },
        items: [],
        nextCursor: null,
        hasNext: false,
        loadingMore: false,
        error: null,
        createError: null,
        createKey: null,
        seenCursors: new Set<string>(),
        creating: false
      }
    };

    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("<main");
    expect(markup).toContain("aria-live=\"polite\"");
    expect(markup).toContain("Cero real");
    expect(markup).toContain("Sin medición");
    expect(markup).toContain("No soportado");
    expect(markup).toContain("mobile-nav");
    expect(markup).not.toContain("<img src=x");
    expect(markup).not.toContain("dangerouslySetInnerHTML");
  });

  it("renders the fixed pending OW reference instead of hostile settings text", () => {
    const hostileReference = "https://example.test/private/ow";
    const settings = parseSettingsEnvelope(envelope({
      contract: "bff-ui-v1",
      versions: { bffSchema: "1", owReference: hostileReference },
      capabilities: { gps: "not_verifiable", workoutDetails: "aggregate_only", segments: "not_verifiable", hrZones: "not_verifiable" },
      technicalState: "ready"
    }));
    const state = initialState("/verify/settings");
    state.sessionStatus = "ready";
    state.session = parseSession(envelope({ authenticated: true, accessState: "active", canReadVerification: true }));
    state.page = { status: "ready", envelope: settings, error: null };

    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("Sin referencia fijada");
    expect(markup).not.toContain(hostileReference);
  });
});
