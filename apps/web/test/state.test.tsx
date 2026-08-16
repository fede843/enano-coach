import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api";
import { initialState, routeFromPath } from "../src/App";
import { isRetryBlocked, retryGateRemaining, retryRequestKind, shouldHandleRouteClick } from "../src/controller-state";
import { formatMetricDetail, formatMetricValue, stateLabel, warningText } from "../src/format";
import { focusInvalidField, validationFieldId } from "../src/validation";
import { AppView, renderErrorPanel } from "../src/view";
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
