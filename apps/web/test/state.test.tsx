import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api";
import { DEFAULT_TIMEZONE, initialState, routeFromPath, shiftSleepSelection, shiftTrendDate, TREND_RANGES } from "../src/App";
import { isRetryBlocked, retryGateRemaining, retryRequestKind, shouldHandleRouteClick } from "../src/controller-state";
import { formatMetricDetail, formatMetricValue, formatTimestamp, stateLabel, warningText } from "../src/format";
import { focusInvalidField, validationFieldId } from "../src/validation";
 import { AppView, formatTrendBucketLabel, formatTrendPointLabel, formatTrendRangeLabel, renderErrorPanel, sleepDurationAxis, sleepDurationGuidePosition, sleepDurationMaximum, sleepNightDurationMaximum, sleepDurationSegments, sleepSchedulePosition, sleepHourBounds, sleepDurationBarHeight, sleepValue, sleepGuidePosition, trendAxisTickLabel, trendAxisTicks, trendBarHeight, trendGuidePosition, trendMetricMaximum, trendMetricText, trendPointText } from "../src/view";
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
  it("uses Argentina as the explicit local default timezone", () => {
    expect(DEFAULT_TIMEZONE).toBe("America/Argentina/Buenos_Aires");
    expect(initialState("/verify").context.timezone).toBe(DEFAULT_TIMEZONE);
  });

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

  it("applies rapid sleep navigation to the latest selected date", () => {
    const first = shiftSleepSelection("2024-01-15", "daily", -1, "2024-12-31");
    const second = shiftSleepSelection(first, "daily", -1, "2024-12-31");

    expect(first).toBe("2024-01-14");
    expect(second).toBe("2024-01-13");
  });

  it("keeps sleep controls mounted and hides chart data while the selected window loads", () => {
    const state = activeState({
      context: { date: "2024-01-15", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-15T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-15", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "loading", error: null, envelope: null }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, sleepDate: "2024-01-14", sleepRange: "daily", trendRanges: TREND_RANGES }} />);

    expect(markup).toContain('data-testid="sleep-trend-panel"');
    expect(markup).toContain('data-testid="sleep-trend-date"');
    expect(markup).toContain('value="2024-01-14"');
    expect(markup).toContain('data-testid="sleep-trend-body" aria-busy="true"');
    expect(markup).toContain("Cargando sueño para la fecha y ventana seleccionadas");
    expect(markup).not.toContain('data-testid="sleep-trend-schedule-chart"');
    expect(markup).not.toContain('data-testid="sleep-trend-duration-chart"');
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
    expect(trendAxisTicks(4000, "steps")).toEqual([4000, 2000, 0]);
    expect(trendAxisTicks(200, "distanceMeters")).toEqual([500, 0]);
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
      expect(markup).not.toContain('title="2024-01-02 · Pasos: 0 pasos · Estado: Parcial"');
      expect(markup).toContain('class="trend-bar trend-partial trend-bar-numeric chart-tooltip-target"');
      expect(markup).toContain('data-tooltip-primitive="chart"');
      expect(markup).toContain('data-tooltip="Pasos: 0 pasos · Estado: Parcial"');
      expect(markup).not.toContain('data-tooltip="2024-01-02 ·');
      expect(markup).toContain('aria-label="2024-01-02: 0 pasos; estado Parcial"');
      expect(markup).not.toContain('data-tooltip="Distancia: Fuente ambigua · Estado: Fuente ambigua"');
     expect(markup).not.toContain('tabindex="0" aria-label="2024-01-03: Fuente ambigua');
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
     expect(markup).toContain(">0</span>");
     expect(markup).toContain(">2 km</span><span>1,5 km</span><span>1 km</span><span>500 m</span><span>0 m</span>");
    expect(markup).toContain('class="trend-bar trend-zero trend-bar-numeric chart-tooltip-target"');
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

  it("renders sleep as a separate section with nap and accessible fallback semantics", () => {
    const points = [
      {
        date: "2024-01-02",
        nightSleepSeconds: { state: "value", value: 25200, unit: "seconds" },
        napsSeconds: { state: "zero", value: 0, unit: "seconds" },
        stages: {
          awakeSeconds: { state: "value", value: 2700, unit: "seconds" },
          lightSeconds: { state: "value", value: 15600, unit: "seconds" },
          deepSeconds: { state: "value", value: 6000, unit: "seconds" },
          remSeconds: { state: "value", value: 3600, unit: "seconds" }
        },
        bedtime: "2024-01-01T22:30:00Z",
        wakeTime: "2024-01-02T06:30:00Z"
      }
    ];
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: 2700, averageObserved: 2700, observedDays: 1, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: 15600, averageObserved: 15600, observedDays: 1, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: 6000, averageObserved: 6000, observedDays: 1, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: 3600, averageObserved: 3600, observedDays: 1, expectedDays: 1 }, observedDays: 1, points }, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, trendRange: "daily", trendRanges: TREND_RANGES }} />);
    expect(markup).toContain("Sueño por ventana");
    expect(markup).toContain("Siestas");
    expect(markup).toContain("Horario local");
     expect(markup).toContain("Promedio noche: <strong>7 h</strong>");
    expect(markup).toContain("Horario");
    expect(markup).toContain("Duración");
      expect(markup).toContain("20:00");
      expect(markup).toContain("06:00");
    expect(markup).toContain("class=\"trend-bar sleep-bar sleep-night sleep-value trend-bar-numeric sleep-bar-numeric sleep-composition-bar chart-tooltip-target\"");
     expect(markup).not.toContain("sleep-segment-nap");
     expect(markup).not.toContain("class=\"sleep-bar sleep-nap");
    expect(markup).toContain("etapas específicas observadas");
    expect(markup).not.toContain("Etapas: awakeSeconds");
  });

  it("renders daily stages vertically in schedule and duration bars without visible timeline labels", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value", value: 25200, unit: "seconds" },
      napsSeconds: { state: "zero", value: 0, unit: "seconds" },
      stages: {
        awakeSeconds: { state: "value", value: 1800, unit: "seconds" },
        lightSeconds: { state: "value", value: 12600, unit: "seconds" },
        deepSeconds: { state: "value", value: 5400, unit: "seconds" },
        remSeconds: { state: "value", value: 7200, unit: "seconds" }
      },
      bedtime: "2024-01-01T23:00:00Z",
      wakeTime: "2024-01-02T06:00:00Z"
    };
    const trend = {
      logicalDate: "2024-01-02", range: "daily" as const, bucketMode: "daily" as const,
      nightSleepSeconds: { unit: "seconds" as const, totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 },
      napsSeconds: { unit: "seconds" as const, totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 1 },
      awakeSeconds: { unit: "seconds" as const, totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays: 1 },
      lightSeconds: { unit: "seconds" as const, totalObserved: 12600, averageObserved: 12600, observedDays: 1, expectedDays: 1 },
      deepSeconds: { unit: "seconds" as const, totalObserved: 5400, averageObserved: 5400, observedDays: 1, expectedDays: 1 },
      remSeconds: { unit: "seconds" as const, totalObserved: 7200, averageObserved: 7200, observedDays: 1, expectedDays: 1 },
      averageBedtime: point.bedtime, averageWakeTime: point.wakeTime, observedDays: 1, points: [point],
      intervals: [
        { start: "2024-01-01T23:00:00Z", end: "2024-01-02T02:30:00Z", category: "light" as const, isNap: false },
        { start: "2024-01-02T02:30:00Z", end: "2024-01-02T04:00:00Z", category: "deep" as const, isNap: false },
        { start: "2024-01-02T04:00:00Z", end: "2024-01-02T06:00:00Z", category: "rem" as const, isNap: false }
      ]
    };
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: trend, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);

    expect(markup).not.toContain('class="sleep-schedule-segments"');
    expect(markup).toContain('class="sleep-segment sleep-segment-awake chart-tooltip-target"');
    expect(markup).toContain('data-stage-orientation="composition-only"');
    expect(markup).toContain('data-tooltip-primitive="chart"');
    expect(markup).toContain('class="sleep-event-timeline"');
    expect(markup).toContain('class="sleep-event-track"');
    expect(markup.match(/class="sleep-event sleep-event-(light|deep|rem) chart-tooltip-target"/g)?.length).toBe(3);
    expect(markup.match(/class="sleep-event sleep-event-(light|deep|rem) chart-tooltip-target"[^>]*tabindex="0"[^>]*data-tooltip="[^"]+"[^>]*data-tooltip-primitive="chart"[^>]*data-tooltip-delay="immediate"[^>]*aria-label="[^"]+"/g)?.length).toBe(3);
    expect(markup).toContain('data-tooltip-delay="immediate"');
    expect(markup).toContain('data-stage-index="0"');
    expect(markup).not.toContain('title="Ligero:');
    expect(markup).not.toContain('>Ligero</span>');
    expect(markup).not.toContain('aria-label="Leyenda del sueño"');
    expect(markup).not.toContain('class="sleep-stage-card');
    expect(markup).not.toContain('class="sleep-event-tooltip');
    expect(markup).not.toContain('title="2024-01-02"');
  });

  it("keeps naps separate from both schedule and night duration bars", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value", value: 25200, unit: "seconds" },
      napsSeconds: { state: "value", value: 1800, unit: "seconds" },
      stages: {
        awakeSeconds: { state: "unsupported", value: null, unit: null },
        lightSeconds: { state: "unsupported", value: null, unit: null },
        deepSeconds: { state: "unsupported", value: null, unit: null },
        remSeconds: { state: "unsupported", value: null, unit: null }
      }, bedtime: "2024-01-01T22:30:00Z", wakeTime: "2024-01-02T06:30:00Z"
    } as const;
    expect(sleepDurationSegments(point as never)).toEqual([{ kind: "night", seconds: 25200 }]);
    const absent = { ...point, napsSeconds: { state: "empty", value: null, unit: null } };
    expect(sleepDurationSegments(absent as never)).toEqual([{ kind: "night", seconds: 25200 }]);
  });

  it("makes every sleep state marker focusable with honest tooltip detail", () => {
    const states = ["null", "empty", "unsupported", "inconclusive", "source_ambiguous"] as const;
    const points = states.map((state, index) => ({
      date: `2024-01-0${index + 2}`,
      nightSleepSeconds: { state, value: null, unit: null },
      napsSeconds: { state, value: null, unit: null },
      stages: {
        awakeSeconds: { state: "unsupported", value: null, unit: null },
        lightSeconds: { state: "unsupported", value: null, unit: null },
        deepSeconds: { state: "unsupported", value: null, unit: null },
        remSeconds: { state: "unsupported", value: null, unit: null }
      },
      bedtime: null,
      wakeTime: null
    }));
    const trend = {
      logicalDate: "2024-01-06", range: "7d" as const, bucketMode: "daily" as const,
      nightSleepSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      napsSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      awakeSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      lightSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      deepSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      remSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 5 },
      observedDays: 0, points
    };
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-06T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-06", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-06T12:30:00Z", timezone: "UTC", data: trend, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={state} actions={actions} />);
    expect(markup.match(/class="trend-bar sleep-bar sleep-night sleep-(null|empty|unsupported|inconclusive|source_ambiguous) chart-tooltip-target"[^>]*tabindex="0"/g)?.length).toBe(5);
    expect(markup).toContain("Noche · Horario no disponible · Duración: Sin medición · Estado: Sin medición");
     expect(markup).not.toContain("class=\"sleep-bar sleep-nap");
  });

  it("keeps nap tooltip semantics honest when the BFF has no nap timestamps", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "value" as const, value: 1800, unit: "seconds" as const },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      },
      bedtime: "2024-01-01T22:30:00Z",
      wakeTime: "2024-01-02T06:30:00Z"
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      context: { date: "2024-01-02", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point] }, coverage: {}, warnings: [], extensions: {} } }
    })} actions={actions} />);
     expect(markup).not.toContain('data-tooltip="Siesta · Horario no disponible · Duración: 30 min · Estado: Observado"');
    expect(markup).not.toContain("Siesta · 01/02");
  });

  it("uses the night-only scale and excludes naps from duration bar height", () => {
    const points = [
      { nightSleepSeconds: { state: "value", value: 25200 }, napsSeconds: { state: "value", value: 3600 } },
      { nightSleepSeconds: { state: "value", value: 21600 }, napsSeconds: { state: "value", value: 28800 } }
    ] as Parameters<typeof sleepDurationMaximum>[0];
    expect(sleepDurationMaximum(points)).toBe(1);
    expect(sleepNightDurationMaximum(points)).toBe(28800);
    expect(sleepDurationBarHeight([{ kind: "night", seconds: 21600 }], sleepNightDurationMaximum(points))).toBe("75%");
  });

  it("maps overnight UTC intervals to local floating schedule positions", () => {
    expect(sleepSchedulePosition("2024-01-01T22:30:00Z", "2024-01-02T06:30:00Z", "Europe/Madrid")).toMatchObject({ height: "16.666666666666664%" });
    expect(sleepSchedulePosition("2024-01-01T23:30:00Z", "2024-01-02T07:30:00Z", "America/New_York")).toMatchObject({ height: "16.666666666666664%" });
  });

  it("uses compact schedule bounds and h:min sleep values", () => {
    const points = [{ bedtime: "2024-01-01T22:30:00Z", wakeTime: "2024-01-02T06:30:00Z" }];
    expect(sleepHourBounds(points, "UTC")).toEqual({ min: 20, max: 34 });
    expect(sleepValue(25_200)).toBe("7 h");
    expect(sleepValue(0)).toBe("0 h");
    expect(sleepValue(null)).toBe("Sin medición");
  });

  it("keeps the full overnight interval in safe schedule bounds", () => {
    const points = [{ bedtime: "2024-01-01T23:30:00Z", wakeTime: "2024-01-02T07:30:00Z" }];
    expect(sleepHourBounds(points, "UTC")).toEqual({ min: 20, max: 34 });
    expect(sleepSchedulePosition(points[0].bedtime, points[0].wakeTime, "UTC", { min: 23, max: 35 })).toEqual({ top: "29.166666666666657%", height: "66.66666666666666%" });
  });

  it("preserves midnight as a valid average guide position", () => {
    const guide = renderToStaticMarkup(<AppView state={activeState({ context: { date: "2024-01-02", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 1, averageObserved: 1, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, averageBedtime: "2024-01-02T00:00:00Z", averageWakeTime: null, points: [{ date: "2024-01-02", nightSleepSeconds: { state: "value", value: 1, unit: "seconds" }, napsSeconds: { state: "empty", value: null, unit: null }, stages: { awakeSeconds: { state: "unsupported", value: null, unit: null }, lightSeconds: { state: "unsupported", value: null, unit: null }, deepSeconds: { state: "unsupported", value: null, unit: null } , remSeconds: { state: "unsupported", value: null, unit: null } }, bedtime: null, wakeTime: null }] }, coverage: {}, warnings: [], extensions: {} } }
    })} actions={actions} />);
    expect(sleepGuidePosition(0, 22, { min: 23, max: 35 })).toBe("91.66666666666667%");
    expect(guide).toContain('class="sleep-average-guide sleep-average-bedtime"');
    expect(guide).not.toContain("top: NaN");
  });

  it("keeps morning average guides within the normalized schedule domain", () => {
    expect(sleepGuidePosition(6, 22, { min: 23, max: 35 })).toBe("41.666666666666664%");
    expect(sleepGuidePosition(11, 22, { min: 23, max: 35 })).toBe("0%");
    expect(Number.parseFloat(sleepGuidePosition(0, 22, { min: 23, max: 35 }) || "-1")).toBeGreaterThanOrEqual(0);
    expect(Number.parseFloat(sleepGuidePosition(11, 22, { min: 23, max: 35 }) || "101")).toBeLessThanOrEqual(100);
  });

  it("keeps only the comparable average guide in a mixed schedule response", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "empty" as const, value: null, unit: null },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      },
      bedtime: "2024-01-01T23:00:00Z",
      wakeTime: "2024-01-02T07:00:00Z"
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      context: { date: "2024-01-02", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "7d", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 7 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, observedDays: 1, points: [point], averageBedtime: "2024-01-01T15:00:00Z", averageWakeTime: "2024-01-02T06:00:00Z" }, coverage: {}, warnings: [], extensions: {} } }
    })} actions={actions} />);
    expect(markup).not.toContain("sleep-guide-key-bedtime");
    expect(markup).toContain("sleep-guide-key-wake");
    expect(markup).not.toContain("sleep-average-bedtime");
    expect(markup).toContain('class="sleep-average-guide sleep-average-wake"');
  });

  it("does not render schedule guide legend entries when averages are absent", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "empty" as const, value: null, unit: null },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      },
      bedtime: "2024-01-01T23:00:00Z",
      wakeTime: "2024-01-02T07:00:00Z"
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point], averageBedtime: null, averageWakeTime: null }, coverage: {}, warnings: [], extensions: {} } }
    })} actions={actions} />);
    expect(markup).not.toContain("sleep-guide-key-bedtime");
    expect(markup).not.toContain("sleep-guide-key-wake");
  });

  it("renders duration ticks with h/min units and only existing sleep guides", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "empty" as const, value: null, unit: null },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null }, lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null }, remSeconds: { state: "unsupported" as const, value: null, unit: null }
      }, bedtime: "2024-01-01T22:30:00Z", wakeTime: "2024-01-02T06:30:00Z"
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      context: { date: "2024-01-02", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point] } , coverage: {}, warnings: [], extensions: {} } }
    })} actions={{ ...actions, trendRange: "7d", trendRanges: TREND_RANGES }} />);
    expect(renderToStaticMarkup(sleepDurationAxis(25200))).toContain('aria-label="Escala de duración del sueño"');
    expect(renderToStaticMarkup(sleepDurationAxis(25200))).toContain("6 h");
    expect(markup).not.toContain("Hora media de despertarse</span>");
    expect(markup).toContain("Promedio noche:");
  });

  it("renders the average night duration guide in duration mode", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "empty" as const, value: null, unit: null },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      },
      bedtime: "2024-01-01T22:30:00Z",
      wakeTime: "2024-01-02T06:30:00Z"
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      context: { date: "2024-01-02", timezone: "UTC" },
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point] } , coverage: {}, warnings: [], extensions: {} } }
    })} actions={{ ...actions, sleepMode: "duration" } as typeof actions & { sleepMode: "duration" }} />);
    expect(sleepDurationGuidePosition(25200, 25200)).toBe("100%");
    expect(markup).toContain('class="sleep-average-guide sleep-average-duration"');
    expect(markup).toContain('data-testid="sleep-trend-duration-chart"');
  });

  it("uses the duration composition categories inside non-daily schedule bars without chronology claims", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "zero" as const, value: 0, unit: "seconds" as const },
      unclassifiedSeconds: { state: "value" as const, value: 3600, unit: "seconds" as const },
      stages: {
        awakeSeconds: { state: "value" as const, value: 1800, unit: "seconds" as const },
        lightSeconds: { state: "value" as const, value: 9000, unit: "seconds" as const },
        deepSeconds: { state: "value" as const, value: 5400, unit: "seconds" as const },
        remSeconds: { state: "value" as const, value: 7200, unit: "seconds" as const }
      },
      bedtime: "2024-01-01T23:00:00Z",
      wakeTime: "2024-01-02T06:00:00Z"
    };
    const trend = {
      logicalDate: "2024-01-02", range: "7d" as const, bucketMode: "daily" as const,
      nightSleepSeconds: { unit: "seconds" as const, totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 7 },
      napsSeconds: { unit: "seconds" as const, totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 7 },
      awakeSeconds: { unit: "seconds" as const, totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays: 7 },
      lightSeconds: { unit: "seconds" as const, totalObserved: 9000, averageObserved: 9000, observedDays: 1, expectedDays: 7 },
      deepSeconds: { unit: "seconds" as const, totalObserved: 5400, averageObserved: 5400, observedDays: 1, expectedDays: 7 },
      remSeconds: { unit: "seconds" as const, totalObserved: 7200, averageObserved: 7200, observedDays: 1, expectedDays: 7 },
      observedDays: 1,
      points: [point],
      intervals: []
    };
    const state = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: trend, coverage: {}, warnings: [], extensions: {} } }
    });
    const schedule = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, sleepMode: "schedule", sleepRange: "7d", trendRanges: TREND_RANGES }} />);
    const duration = renderToStaticMarkup(<AppView state={state} actions={{ ...actions, sleepMode: "duration", sleepRange: "7d", trendRanges: TREND_RANGES }} />);

    for (const category of ["awake", "unclassified", "light", "deep", "rem"]) {
      expect(schedule).toContain(`sleep-segment-${category}`);
      expect(duration).toContain(`sleep-segment-${category}`);
    }
    expect(schedule).toContain('data-stage-orientation="composition-only"');
    expect(schedule).toContain('aria-label="Sin clasificar · Duración: 1 h · Estado: Observado"');
    expect(schedule).toContain('aria-label="Despierto · Duración: 0 h 30 min · Estado: Observado"');
    expect(schedule).not.toContain("sleep-segment-in_bed");
    expect(schedule).not.toContain("sleep-segment-unknown");
    expect(schedule).not.toContain('data-stage-orientation="vertical-time"');

    const genericPoint = {
      ...point,
      unclassifiedSeconds: undefined,
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      }
    };
    const genericState = activeState({
      page: state.page,
      sleepTrend: { ...state.sleepTrend!, envelope: { ...state.sleepTrend!.envelope!, data: { ...trend, points: [genericPoint] } } }
    });
    const genericSchedule = renderToStaticMarkup(<AppView state={genericState} actions={{ ...actions, sleepMode: "schedule", sleepRange: "7d", trendRanges: TREND_RANGES }} />);
    const genericDuration = renderToStaticMarkup(<AppView state={genericState} actions={{ ...actions, sleepMode: "duration", sleepRange: "7d", trendRanges: TREND_RANGES }} />);
    expect(genericSchedule).not.toContain("sleep-segment-night");
    expect(genericDuration).not.toContain("sleep-segment-night");
    expect(genericSchedule).not.toContain('aria-label="Sueño genérico · Duración: 7 h · Estado: Observado"');
  });

  it("omits duration guides when the average is unavailable", () => {
    expect(sleepDurationGuidePosition(null, 25200)).toBe(null);
    expect(sleepDurationGuidePosition(25200, 25200)).toBe("100%");
  });

  it("keeps an overnight schedule inside a fixed local night window", () => {
    expect(sleepHourBounds([{ bedtime: "2024-01-02T01:30:00Z", wakeTime: "2024-01-02T09:00:00Z" }], "UTC")).toEqual({ min: 22, max: 36 });
    expect(sleepSchedulePosition("2024-01-02T01:30:00Z", "2024-01-02T09:00:00Z", "UTC", { min: 23, max: 35 })).toMatchObject({ height: "62.5%" });
  });

  it("renders generic sleep intervals in chronological order with explicit labels", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value" as const, value: 25200, unit: "seconds" as const },
      napsSeconds: { state: "zero" as const, value: 0, unit: "seconds" as const },
      stages: {
        awakeSeconds: { state: "unsupported" as const, value: null, unit: null },
        lightSeconds: { state: "unsupported" as const, value: null, unit: null },
        deepSeconds: { state: "unsupported" as const, value: null, unit: null },
        remSeconds: { state: "unsupported" as const, value: null, unit: null }
      }, bedtime: null, wakeTime: null
    };
    const trend = {
      logicalDate: "2024-01-02", range: "daily" as const, bucketMode: "daily" as const,
      nightSleepSeconds: { unit: "seconds" as const, totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 },
      napsSeconds: { unit: "seconds" as const, totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 1 },
      awakeSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds" as const, totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point], intervals: [
        { start: "2024-01-02T02:00:00Z", end: "2024-01-02T03:00:00Z", category: "unknown" as const, isNap: false },
        { start: "2024-01-02T00:00:00Z", end: "2024-01-02T01:00:00Z", category: "sleeping" as const, isNap: false }
      ]
    };
    const markup = renderToStaticMarkup(<AppView state={activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: trend, coverage: {}, warnings: [], extensions: {} } }
    })} actions={actions} />);
    expect(markup).toContain('aria-label="Sueño genérico · 1 ene 2024, 21:00 → 1 ene 2024, 22:00 · Duración: 1 h"');
    expect(markup).toContain('aria-label="Desconocido · 1 ene 2024, 23:00 → 2 ene 2024, 0:00 · Duración: 1 h"');
    expect(markup).not.toContain("sleep-event-rem");
  });

  it("formats duration axis ticks as hours and minutes", () => {
    const markup = renderToStaticMarkup(sleepDurationAxis(50400));
    expect(markup).toContain("15 h");
    expect(markup).toContain("10 h");
    expect(markup).toContain("5 h");
    expect(markup).toContain("0 h");
  });

  it("scales a duration bar by the maximum instead of the segment total", () => {
    expect(sleepDurationBarHeight([{ kind: "night", seconds: 25_200 }], 28_800)).toBe("87.5%");
  });

  it.each([
    ["value", "Observado"],
    ["zero", "Cero real"],
    ["partial", "Parcial"],
    ["empty", "Sin datos"],
    ["null", "Sin medición"],
    ["unsupported", "No soportado"],
    ["source_ambiguous", "Fuente ambigua"],
    ["inconclusive", "Inconclusa"]
  ])("includes the explicit sleep point state %s in accessible rows", (state, label) => {
    const metric = { state, value: state === "value" ? 25200 : state === "zero" ? 0 : null, unit: state === "value" || state === "zero" ? "seconds" : null };
    const points = [{
      date: "2024-01-02",
      nightSleepSeconds: metric,
      napsSeconds: metric,
      stages: {
        awakeSeconds: { state: "unsupported", value: null, unit: null },
        lightSeconds: { state: "unsupported", value: null, unit: null },
        deepSeconds: { state: "unsupported", value: null, unit: null },
        remSeconds: { state: "unsupported", value: null, unit: null }
      },
      bedtime: null,
      wakeTime: null
    }];
    const stateValue = activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "UTC", data: { logicalDate: "2024-01-02", range: "daily", bucketMode: "daily", nightSleepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 0, points }, coverage: {}, warnings: [], extensions: {} } }
    });
    const markup = renderToStaticMarkup(<AppView state={stateValue} actions={actions} />);
    expect(markup).toContain(`estado: ${label}`);
    expect(markup).toContain("no publica etapas");
  });

  it("rejects invalid UTC timestamps in the frontend presentation", () => {
    expect(formatTimestamp("2024-99-99T99:99:99Z", "UTC")).toBe("Fecha no disponible");
  });

  it("renders localized sleep times and preserves daily and calendar-month bucket modes", () => {
    const point = {
      date: "2024-01-02",
      nightSleepSeconds: { state: "value", value: 25200, unit: "seconds" },
      napsSeconds: { state: "zero", value: 0, unit: "seconds" },
      stages: {
        awakeSeconds: { state: "unsupported", value: null, unit: null },
        lightSeconds: { state: "unsupported", value: null, unit: null },
        deepSeconds: { state: "unsupported", value: null, unit: null },
        remSeconds: { state: "unsupported", value: null, unit: null }
      },
      bedtime: "2024-01-01T22:30:00Z",
      wakeTime: "2024-01-02T06:30:00Z"
    };
    const makeState = (range: "daily" | "annual", bucketMode: "daily" | "calendar-month") => activeState({
      page: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "Europe/Madrid", data: { logicalDate: "2024-01-02", summary: {} }, coverage: { availableDays: 1 }, warnings: [], extensions: {} } },
      context: { date: "2024-01-02", timezone: "Europe/Madrid" },
      sleepTrend: { status: "ready", error: null, envelope: { schemaVersion: "1", asOf: "2024-01-02T12:30:00Z", timezone: "Europe/Madrid", data: { logicalDate: "2024-01-02", range, bucketMode, nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 }, napsSeconds: { unit: "seconds", totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays: 1 }, awakeSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, lightSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, deepSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, remSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, observedDays: 1, points: [point] }, coverage: {}, warnings: [], extensions: {} } }
    });
    const dailyMarkup = renderToStaticMarkup(<AppView state={makeState("daily", "daily")} actions={actions} />);
    expect(dailyMarkup).toContain("Horario local");
    expect(dailyMarkup).toContain("23:30");
    expect(dailyMarkup).toContain("23:30");
    expect(dailyMarkup).toContain("7:30");
    expect(dailyMarkup).toContain("Diario");
    const annualMarkup = renderToStaticMarkup(<AppView state={makeState("annual", "calendar-month")} actions={actions} />);
    expect(annualMarkup).toContain("Anual");
    expect(annualMarkup).toContain('aria-label="Resumen mensual de duración del sueño"');
    expect(annualMarkup).toContain(">ene</span>");
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
