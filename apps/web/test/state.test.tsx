import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api";
import { initialState, routeFromPath, shiftTrendDate, TREND_RANGES } from "../src/App";
import { isRetryBlocked, retryGateRemaining, retryRequestKind, shouldHandleRouteClick } from "../src/controller-state";
import { formatMetricDetail, formatMetricValue, stateLabel, warningText } from "../src/format";
import { focusInvalidField, validationFieldId } from "../src/validation";
import { AppView, formatTrendBucketLabel, formatTrendPointLabel, formatTrendRangeLabel, renderErrorPanel, trendAxisTickLabel, trendAxisTicks, trendBarHeight, trendGuidePosition, trendMetricMaximum, trendMetricText, trendPointText } from "../src/view";
import type { AppState } from "../src/types";

function activeState(overrides: Partial<AppState> = {}): AppState {
  const state = initialState("/verify");
  return {
    ...state,
    sessionStatus: "ready",
    session: {
      schemaVersion: "1",
      asOf: "2024-01-02T12:30:00Z",
      timezone: "UTC",
      data: { authenticated: true, accessState: "active", canReadVerification: true },
      coverage: {},
      warnings: [],
      extensions: {}
    },
    page: { status: "ready", envelope: null, error: null },
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

describe("controller and render state", () => {
  it("uses user-facing range and localized calendar-month labels", () => {
    expect(formatTrendRangeLabel("daily")).toBe("Diario");
    expect(formatTrendRangeLabel("7d")).toBe("7 días");
    expect(formatTrendRangeLabel("monthly")).toBe("Mensual");
    expect(formatTrendRangeLabel("180d")).toBe("180 días");
    expect(formatTrendRangeLabel("annual")).toBe("Anual");
    expect(formatTrendBucketLabel("2024-02-01")).toMatch(/febrero|feb\.?/i);
    expect(formatTrendBucketLabel("2024-02-01")).not.toBe("2024-02-01");
    expect(TREND_RANGES.map((range) => range.label)).toEqual(["Diario", "7 días", "Mensual", "180 días", "Anual"]);
  });

  it("shifts each range by its exact window and blocks future dates", () => {
    expect(shiftTrendDate("2024-01-10", "daily", 1, "2024-12-31")).toBe("2024-01-11");
    expect(shiftTrendDate("2024-01-10", "7d", -1, "2024-12-31")).toBe("2024-01-03");
    expect(shiftTrendDate("2024-02-29", "monthly", 1, "2024-12-31")).toBe("2024-03-01");
    expect(shiftTrendDate("2024-01-01", "annual", 1, "2024-06-01")).toBe("2024-01-01");
  });

  it("keeps a successful overview visible when the secondary trend fails", () => {
    const state = activeState({
      page: {
        status: "ready",
        error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-02", summary: { steps: { state: "value", value: 10, unit: "count", isDailyTotal: true } } },
          coverage: { expectedDays: 1, availableDays: 1, isPartial: false }, warnings: [], extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("10");
    expect(markup).not.toContain("No se pudo cargar la tendencia");
  });

  it("maps numeric trend values proportionally within each metric scale", () => {
    expect(trendMetricText({ totalObserved: 0, averageObserved: 0, observedDays: 7, expectedDays: 7, unit: "count" }, "average")).toBe("0");
    expect(trendPointText("partial", 1200, "pasos")).toBe("1200 pasos");
    expect(trendPointText("source_ambiguous", null, "pasos")).toBe("Fuente ambigua");
    expect(trendPointText("zero", 0, "pasos")).toBe("0 pasos");
    expect(trendBarHeight("value", 1000, 4000)).toBe("25%");
    expect(trendBarHeight("value", 2000, 4000)).toBe("50%");
    expect(trendBarHeight("value", 4000, 4000)).toBe("100%");
    expect(trendBarHeight("partial", 2000, 4000)).toBe("50%");
    expect(trendBarHeight("source_ambiguous", null, 100)).toBe("0%");
    expect(trendBarHeight("zero", 0, 4000)).toBe("0%");
    expect(trendBarHeight("null", null, 4000)).toBe("0%");
    expect(trendBarHeight("empty", null, 4000)).toBe("0%");
    expect(trendBarHeight("inconclusive", null, 4000)).toBe("0%");
  });

  it("keeps steps and distance maxima independent and ignores nonnumeric points", () => {
    const points = [
      { steps: { state: "value", value: 1000 }, distanceMeters: { state: "value", value: 50 } },
      { steps: { state: "value", value: 4000 }, distanceMeters: { state: "value", value: 200 } },
      { steps: { state: "empty", value: null }, distanceMeters: { state: "null", value: null } }
    ] as Parameters<typeof trendMetricMaximum>[0];
    expect(trendMetricMaximum(points, "steps")).toBe(4000);
    expect(trendMetricMaximum(points, "distanceMeters")).toBe(200);
    expect(trendBarHeight("value", 50, trendMetricMaximum(points, "distanceMeters"))).toBe("25%");
    expect(trendBarHeight("value", 50, 200)).toBe("25%");
    expect(trendAxisTicks(4000)).toEqual([4000, 2000, 0]);
    expect(trendAxisTicks(200)).toEqual([200, 100, 0]);
    expect(trendAxisTickLabel(2000, "steps")).toBe("2000");
    expect(trendAxisTickLabel(1000, "distanceMeters")).toBe("1 km");
  });

  it("positions observed-average guides on each metric's independent scale", () => {
    expect(trendGuidePosition(1000, 4000)).toBe("25%");
    expect(trendGuidePosition(50, 200)).toBe("25%");
  });

  it("omits guides for missing or nonnumeric averages but keeps zero at the baseline", () => {
    expect(trendGuidePosition(null, 4000)).toBe(null);
    expect(trendGuidePosition(Number.NaN, 4000)).toBe(null);
    expect(trendGuidePosition(0, 4000)).toBe("0%");
  });

  it("renders two separate seven-position trend series", () => {
    const points = Array.from({ length: 7 }, (_, index) => ({
      date: `2024-01-0${index + 1}`,
       steps: { state: index === 1 ? "partial" : "value", value: index === 1 ? 0 : index, unit: "count" },
      distanceMeters: { state: index === 2 ? "source_ambiguous" : "value", value: index === 2 ? null : index * 2, unit: "meters" }
    }));
    const state = activeState({
      page: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-07T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-07", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {}
        }
      },
      activityTrend: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-07T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-07", range: "7d", steps: { unit: "count", totalObserved: 100, averageObserved: 14, observedDays: 6, expectedDays: 7 }, distanceMeters: { unit: "meters", totalObserved: 200, averageObserved: 28, observedDays: 6, expectedDays: 7 }, points }, coverage: {}, warnings: [], extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, trendRange: "7d", trendRanges: TREND_RANGES }} />);
    expect(markup.match(/class=\"trend-bar trend-/g)?.length).toBe(14);
    expect(markup.match(/class=\"trend-series /g)?.length).toBe(2);
    expect(markup.match(/class=\"trend-average-guide/g)?.length).toBe(2);
    expect(markup).toContain("Promedio observado</span>");
    expect(markup).toContain("Promedio pasos: <strong>14</strong>");
    expect(markup).toContain("Promedio distancia: <strong>28 m</strong>");
    expect(markup).toContain("2 pasos");
    expect(markup).toContain("Fuente ambigua");
    expect(markup).toContain("2024-01-02: 0 pasos");
    expect(markup).toContain('aria-label="Series separadas de pasos y distancia por día"');
    expect(markup).not.toContain('grid-template-columns: repeat(2');
    expect(markup.indexOf('trend-bar-group-label">Pasos')).toBeLessThan(markup.indexOf('trend-bar-group-label">Distancia'));
    expect(markup).toContain('aria-label="Escala de Pasos"');
    expect(markup).toContain('aria-label="Escala de Distancia"');
      expect(markup).toContain('title="2024-01-02 · Pasos: 0 pasos · Estado: Parcial"');
      expect(markup).toContain('class="trend-bar trend-partial trend-bar-numeric"');
      expect(markup).toContain('data-tooltip="Pasos: 0 pasos · Estado: Parcial"');
      expect(markup).not.toContain('data-tooltip="2024-01-02 ·');
      expect(markup).toContain('aria-label="2024-01-02: 0 pasos; estado Parcial"');
      expect(markup).toContain('title="2024-01-03 · Distancia: Fuente ambigua · Estado: Fuente ambigua"');
     expect(markup).not.toContain('tabindex="0" title="2024-01-03 · Distancia: Fuente ambigua');
    expect(markup).toContain('aria-label="Seleccionar ventana Diario"');
    expect(markup).toContain('aria-label="Seleccionar ventana Anual"');
    expect(markup).toContain('aria-label="Seleccionar ventana 7D" aria-current="true" aria-pressed="true"');
    expect(markup).toContain('aria-label="Seleccionar ventana Diario" aria-pressed="false"');
  });

  it("renders three readable ticks for each metric scale without changing state bars", () => {
    const points = [
      { date: "2024-01-01", steps: { state: "zero", value: 0, unit: "count" }, distanceMeters: { state: "value", value: 100, unit: "meters" } },
      { date: "2024-01-02", steps: { state: "null", value: null, unit: null }, distanceMeters: { state: "partial", value: 2000, unit: "meters" } },
      { date: "2024-01-03", steps: { state: "inconclusive", value: null, unit: null }, distanceMeters: { state: "empty", value: null, unit: null } }
    ];
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-03T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-03", summary: { steps: { state: "zero", value: 0, unit: "count", isDailyTotal: true } } }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      activityTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-03T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-03", range: "7d", steps: { unit: "count", totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 3 }, distanceMeters: { unit: "meters", totalObserved: 2100, averageObserved: 1050, observedDays: 2, expectedDays: 3 }, points }, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup.match(/aria-label="Escala de Pasos"/g)?.length).toBe(1);
    expect(markup.match(/aria-label="Escala de Distancia"/g)?.length).toBe(1);
     expect(markup).toContain(">0</span><span>0</span><span>0</span>");
     expect(markup).toContain(">2 km</span><span>1 km</span><span>0 m</span>");
    expect(markup).toContain('class="trend-bar trend-zero trend-bar-numeric"');
    expect(markup).toContain('class="trend-bar trend-null"');
    expect(markup).toContain('class="trend-bar trend-inconclusive"');
    expect(markup).toContain('class="trend-bar trend-empty"');
  });

  it("adds compact localized day labels without putting dates in the hover tooltip", () => {
    expect(formatTrendPointLabel("2024-01-02", "7d")).toMatch(/mar|02/i);
    expect(formatTrendPointLabel("2024-01-02", "monthly")).toBe("02");
    expect(formatTrendPointLabel("2024-01-02", "daily")).toMatch(/mar|02/i);
  });

  it("uses Observado for numeric trend state and renders monthly long-range buckets", () => {
    const points = Array.from({ length: 12 }, (_, index) => ({
      date: `2024-${String(index + 1).padStart(2, "0")}-01`,
      steps: { state: index === 1 ? "value" : "empty", value: index === 1 ? 200 : null, unit: index === 1 ? "count" : null },
      distanceMeters: { state: "empty", value: null, unit: null }
    }));
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-12-31T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-12-31", summary: { steps: { state: "value", value: 10, unit: "count", isDailyTotal: true } } }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      activityTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-12-31T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-12-31", range: "annual", bucketMode: "calendar-month", steps: { unit: "count", totalObserved: 200, averageObserved: 200, observedDays: 1, expectedDays: 366 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 366 }, points }, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, trendRange: "annual", trendRanges: TREND_RANGES }} />);
    expect(markup).toContain("Resumen mensual");
    expect(markup).toContain('aria-label="Series separadas de pasos y distancia por mes"');
    expect(markup).toContain("Observado");
    expect(markup).toContain("<ul class=\"trend-bucket-summary\"");
  });

  it("renders dense monthly points without visible absence labels and exposes quick controls", () => {
    const points = Array.from({ length: 31 }, (_, index) => ({
      date: `2024-01-${String(index + 1).padStart(2, "0")}`,
      steps: { state: index % 3 === 0 ? "empty" : "value", value: index % 3 === 0 ? null : index * 100, unit: index % 3 === 0 ? null : "count" },
      distanceMeters: { state: index % 4 === 0 ? "null" : "value", value: index % 4 === 0 ? null : index * 10, unit: index % 4 === 0 ? null : "meters" }
    }));
    const state = activeState({
      page: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-31T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-31", summary: { steps: { state: "value", value: 10, unit: "count", isDailyTotal: true } } }, coverage: { availableDays: 1 }, warnings: [], extensions: {}
        }
      },
      activityTrend: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-31T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-31", range: "monthly", bucketMode: "daily", steps: { unit: "count", totalObserved: 27900, averageObserved: 1395, observedDays: 20, expectedDays: 31 }, distanceMeters: { unit: "meters", totalObserved: 2320, averageObserved: 116, observedDays: 23, expectedDays: 31 }, points }, coverage: {}, warnings: [], extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, trendRange: "monthly", trendRanges: TREND_RANGES }} />);
    expect(markup.match(/class="trend-bar trend-/g)?.length).toBe(62);
    expect(markup).toContain('aria-label="Ventana anterior"');
    expect(markup).toContain('aria-label="Seleccionar ventana Diario"');
    expect(markup).toContain('aria-label="Seleccionar ventana 1M"');
    expect(markup).toContain('aria-current="true"');
    expect(markup).toContain("Promedio observado");
    expect(markup).not.toContain(">Sin medición</span>");
    expect(markup).not.toContain(">Ausente</span>");
    expect(markup).toContain('aria-label="Seleccionar ventana 1M" aria-current="true" aria-pressed="true"');
    expect(markup).toContain('aria-label="Seleccionar ventana 7D" aria-pressed="false"');
  });

  it("renders long-range buckets with localized labels and preserves the overview", () => {
    const points = Array.from({ length: 12 }, (_, index) => ({
      date: `2024-${String(index + 1).padStart(2, "0")}-01`,
      steps: { state: index === 1 ? "value" : "empty", value: index === 1 ? 200 : null, unit: index === 1 ? "count" : null },
      distanceMeters: { state: "empty", value: null, unit: null }
    }));
    const state = activeState({
      page: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-12-31T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-12-31", summary: { steps: { state: "value", value: 10, unit: "count", isDailyTotal: true } } }, coverage: { availableDays: 1 }, warnings: [], extensions: {}
        }
      },
      activityTrend: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-12-31T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-12-31", range: "annual", bucketMode: "calendar-month", steps: { unit: "count", totalObserved: 200, averageObserved: 200, observedDays: 1, expectedDays: 366 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 366 }, points }, coverage: {}, warnings: [], extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, trendRange: "annual", trendRanges: TREND_RANGES }} />);
    expect(markup).toContain("Actividad por ventana");
    expect(markup).toContain("Anual");
    expect(markup).toContain("febrero de 2024");
    expect(markup).toContain("(2024-02-01)");
    expect(markup).not.toContain("<strong>2024-02-01</strong>");
    expect(markup).toContain("10");
  });

  it("renders explicit absence without units for missing trend aggregates", () => {
    const state = activeState({
      page: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-07T12:30:00Z", timezone: "UTC",
          data: { logicalDate: "2024-01-07", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {}
        }
      },
      activityTrend: {
        status: "ready", error: null,
        envelope: {
          schemaVersion: "1", asOf: "2024-01-07T12:30:00Z", timezone: "UTC",
          data: {
            logicalDate: "2024-01-07", range: "7d",
            steps: { unit: "count", totalObserved: 0, averageObserved: null, observedDays: 1, expectedDays: 7 },
            distanceMeters: { unit: "meters", totalObserved: null, averageObserved: 0, observedDays: 1, expectedDays: 7 },
            points: [],
          }, coverage: {}, warnings: [], extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("Total pasos: ");
    expect(markup).toContain("<strong>0</strong>");
    expect(markup).toContain("Promedio pasos: <strong>Sin medición</strong>");
    expect(markup).toContain("Total distancia: <strong>Sin medición</strong>");
    expect(markup).toContain("Promedio distancia: <strong>0 m</strong>");
  });
  it("maps every browser route without exposing an arbitrary route target", () => {
    expect(routeFromPath("/")).toEqual({ name: "overview", path: "/verify" });
    expect(routeFromPath("/verify/runs/verify-demo-01")).toEqual({ name: "detail", path: "/verify/runs/verify-demo-01", runKey: "verify-demo-01" });
    expect(routeFromPath("/verify/runs/not-an-opaque-key").name).toBe("unknown");
  });

  it("keeps retry ownership between session and route errors", () => {
    expect(retryRequestKind({ session: null, sessionError: { code: "NETWORK_ERROR" } } as AppState)).toBe("session");
    expect(retryRequestKind({ session: activeState().session, sessionError: null } as AppState)).toBe("route");
    expect(retryGateRemaining(6_000, 1_000)).toBe(5_000);
    expect(isRetryBlocked(1_001, 1_000)).toBe(true);
    expect(isRetryBlocked(1_000, 1_000)).toBe(false);
  });

  it("keeps normal browser modifier and middle-click behavior", () => {
    expect(shouldHandleRouteClick({ button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false })).toBe(true);
    expect(shouldHandleRouteClick({ button: 1, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false })).toBe(false);
    expect(shouldHandleRouteClick({ button: 0, metaKey: true, ctrlKey: false, shiftKey: false, altKey: false })).toBe(false);
  });

  it("keeps null distinct from a confirmed zero and recovery unitless", () => {
    expect(formatMetricValue({ state: "null", value: null, unit: null, isDailyTotal: false })).toEqual({ value: "Sin medición", unit: "", isValue: false });
    expect(formatMetricValue({ state: "zero", value: 0, unit: "kcal", isDailyTotal: true })).toMatchObject({ value: "0", isValue: true });
    expect(formatMetricValue({ state: "value", value: 82, unit: null, isDailyTotal: false })).toEqual({ value: "82", unit: "", isValue: true });
  });

  it("keeps scalar heart-rate copy free of aggregate claims", () => {
    const detail = formatMetricDetail("heartRate", { state: "value", value: 72, unit: "bpm", isDailyTotal: false });
    expect(detail).toContain("escalar");
    expect(detail).not.toMatch(/avg|min|max|average|minimum|maximum/i);
  });

  it("does not describe non-terminal or unverifiable metric states as daily totals", () => {
    const cases = [
      ["error", "Fallo técnico; no se afirma un total diario."],
      ["pending", "Proceso pendiente; no se afirma un total diario."],
      ["inconclusive", "La consulta no pudo cerrarse; no se afirma un total diario."],
      ["not_verifiable", "La API disponible no puede probar esta lectura ni su total diario."]
    ] as const;

    for (const [state, detail] of cases) {
      expect(formatMetricDetail("steps", { state, value: null, unit: null, isDailyTotal: true })).toBe(detail);
      expect(formatMetricDetail("steps", { state, value: null, unit: null, isDailyTotal: true })).not.toContain("Total diario declarado");
    }
  });

  it("associates invalid date fields with their controls and focuses the mapped field", () => {
    const control = { focus: vi.fn() };
    vi.stubGlobal("document", {
      getElementById: vi.fn((id: string) => id === "context-date" ? control : null)
    });

    expect(validationFieldId("date")).toBe("context-date");
    expect(validationFieldId("untrusted-field")).toBe(null);
    expect(focusInvalidField("date")).toBe(true);
    expect(control.focus).toHaveBeenCalledWith({ preventScroll: true });
    vi.unstubAllGlobals();
  });

  it("selects warning copy by stable code and discards hostile prose", () => {
    const hostile = { code: "PARTIAL_COVERAGE", message: "<img src=x onerror=alert(1)>" };
    expect(warningText(hostile)).toBe("La ventana solo tiene observaciones parciales.");
    expect(warningText(hostile)).not.toMatch(/[<>]/);
    expect(stateLabel("unsupported")).not.toBe(stateLabel("empty"));
  });

  it("keeps the required data, source, and processing states distinct in copy", () => {
    const states = ["empty", "value", "zero", "null", "partial", "unsupported", "ready", "pending", "completed_with_findings", "error", "source_ambiguous", "not_verifiable", "inconclusive"];
    const labels = states.map(stateLabel);
    expect(new Set(labels).size).toBe(states.length);
    expect(labels).toContain("Pendiente");
    expect(labels).toContain("No verificable");
    expect(labels).toContain("Inconclusa");
    expect(labels).toContain("Con hallazgos");
  });

  it("renders an empty window without turning absence into zero", () => {
    const state = activeState({
      page: {
        status: "ready",
        error: null,
        envelope: {
          schemaVersion: "1",
          asOf: "2024-01-04T12:30:00Z",
          timezone: "UTC",
          data: { logicalDate: "2024-01-04", summary: {} },
          coverage: { requested: { logicalDate: "2024-01-04", from: "2024-01-04T00:00:00Z", to: "2024-01-05T00:00:00Z", timezone: "UTC" }, expectedDays: 1, availableDays: 0, isPartial: false, byDomain: {} },
          warnings: [],
          extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("No hay datos para esta ventana");
    expect(markup).not.toContain("0 kcal");
    expect(markup).not.toContain("<script");
  });

  it("renders an empty window when only unsupported capability placeholders exist", () => {
    const state = activeState({
      page: {
        status: "ready",
        error: null,
        envelope: {
          schemaVersion: "1",
          asOf: "2026-08-25T12:30:00Z",
          timezone: "UTC",
          data: {
            logicalDate: "2026-08-25",
            summary: {
              stress: { state: "unsupported", value: null, unit: null, isDailyTotal: null }
            }
          },
          coverage: { requested: { logicalDate: "2026-08-25", from: "2026-08-25T00:00:00Z", to: "2026-08-26T00:00:00Z", timezone: "UTC" }, expectedDays: 1, availableDays: 0, isPartial: false, byDomain: {} },
          warnings: [],
          extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("No hay datos para esta ventana");
    expect(markup).not.toContain("1 campo");
  });

  it("renders a source-specific empty inventory with the requested context", () => {
    const state = activeState({
      route: { name: "sources", path: "/verify/sources" },
      context: { date: "2024-01-04", timezone: "UTC" },
      page: {
        status: "ready",
        error: null,
        envelope: {
          schemaVersion: "1",
          asOf: "2024-01-04T12:30:00Z",
          timezone: "UTC",
          data: { items: [] },
          coverage: {},
          warnings: [],
          extensions: {}
        }
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("No hay fuentes declaradas para esta consulta");
    expect(markup).toContain("Inventario de proveniencia");
    expect(markup).toContain("2024-01-04");
    expect(markup).toContain("UTC");
    expect(markup).not.toContain("Ventana vacía");
    expect(markup).not.toContain("No hay datos para esta ventana");
    expect(markup).not.toContain("La ventana está completa y no contiene observaciones");
    expect(markup).not.toContain("días");
  });

  it("associates context validation errors with a deterministic field message", () => {
    const state = activeState({
      page: { status: "error", envelope: null, error: new ApiError({ status: 400, code: "INVALID_QUERY", field: "date" }) }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain('id="context-date-error"');
    expect(markup).toContain('aria-invalid="true"');
    expect(markup).toContain('aria-describedby="context-date-error"');
    expect(markup).toContain("Revisa la fecha seleccionada.");
  });

  it("associates run filter validation errors and disables submission while loading", () => {
    const invalidState = activeState({
      route: { name: "runs", path: "/verify/runs" },
      page: { status: "error", envelope: null, error: new ApiError({ status: 400, code: "INVALID_QUERY", field: "from" }) }
    });
    const invalidMarkup = renderToStaticMarkup(<AppView state={invalidState} actions={actions} />);
    expect(invalidMarkup).toContain('id="runs-from-error"');
    expect(invalidMarkup).toContain('aria-invalid="true"');
    expect(invalidMarkup).toContain('aria-describedby="runs-from-error"');
    expect(invalidMarkup).toContain("Revisa la fecha inicial.");

    const loadingState = activeState({
      route: { name: "runs", path: "/verify/runs" },
      page: { status: "loading", envelope: null, error: null }
    });
    const loadingMarkup = renderToStaticMarkup(<AppView state={loadingState} actions={actions} />);
    expect(loadingMarkup).toContain('data-form="runs"');
    expect(loadingMarkup).toContain('aria-busy="true"');
    expect(loadingMarkup).toContain('id="runs-filter-status"');
    expect(loadingMarkup).toContain("Aplicando filtros…");
    expect(loadingMarkup).toMatch(/<button[^>]*disabled[^>]*>Aplicar filtros<\/button>/);
  });

  it("renders labeled scroll regions and compact alternatives for wide lists", () => {
    const state = activeState({
      route: { name: "runs", path: "/verify/runs" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { items: [], page: { nextCursor: null, hasNext: false, totalCount: null } }, coverage: {}, warnings: [], extensions: {} } },
      runs: {
        ...initialState().runs,
        items: [{ runKey: "verify-demo-01", state: "persisted", requestedAt: "2024-01-02T08:00:00Z", startedAt: "2024-01-02T08:00:01Z", finishedAt: "2024-01-02T08:00:02Z", counts: { recordsSeen: 1, recordsAccepted: 1, recordsRejected: 0, recordsDuplicated: 0, fieldsUnsupported: 0 } }]
      }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup).toContain("role=\"region\"");
    expect(markup).toContain("mobile-only");
    expect(markup).toContain("role=\"list\"");
    expect(markup).not.toContain("name=\"timezone\"");
  });

  it("renders explicit safe states for the contracted HTTP errors", () => {
    const cases = [
      [400, "INVALID_QUERY"],
      [401, "SESSION_REQUIRED"],
      [403, "ACCESS_BLOCKED"],
      [404, "RUN_NOT_FOUND"],
      [409, "IDEMPOTENCY_CONFLICT"],
      [410, "CURSOR_EXPIRED"],
      [422, "INVALID_SCOPE"],
      [429, "RATE_LIMITED"],
      [500, "INTERNAL_ERROR"],
      [502, "UPSTREAM_INVALID"],
      [503, "UPSTREAM_UNAVAILABLE"],
      [504, "UPSTREAM_TIMEOUT"]
    ] as const;
    for (const [status, code] of cases) {
      const markup = renderToStaticMarkup(renderErrorPanel(new ApiError({ status, code, retryable: false, requestId: "req-demo-safe" })));
      expect(markup).toContain(code);
      expect(markup).not.toContain("provider internals");
    }
  });
});
