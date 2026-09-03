import { expect, test } from "@playwright/test";

const envelope = (data: unknown) => ({
  schemaVersion: "1",
  asOf: "2026-08-03T12:00:00Z",
  timezone: "UTC",
  data,
  coverage: {
    requested: {
      logicalDate: "2026-08-03",
      from: "2026-08-03T00:00:00Z",
      to: "2026-08-04T00:00:00Z",
      timezone: "UTC"
    },
    expectedDays: 1,
    availableDays: 1,
    isPartial: false,
    byDomain: { activity: { expectedDays: 1, availableDays: 1, state: "complete" }, sleep: { expectedDays: 1, availableDays: 1, state: "complete" } }
  },
  warnings: [],
  extensions: {}
});

const contextEnvelope = (data: unknown, logicalDate: string) => {
  const next = new Date(`${logicalDate}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return {
    ...envelope(data),
    coverage: {
      ...envelope(data).coverage,
      requested: { logicalDate, from: `${logicalDate}T00:00:00Z`, to: next.toISOString().replace(".000Z", "Z"), timezone: "UTC" }
    }
  };
};

const metric = (value: number, unit: "count" | "meters" | "seconds") => ({ state: "value", value, unit, isDailyTotal: unit !== "seconds" });
const trendMetric = (value: number, unit: "count" | "meters" | "seconds") => ({ state: "value", value, unit });
const point = (date: string, steps: number | null, distanceMeters: number | null) => ({
  date,
  steps: steps === null ? { state: "empty", value: null, unit: null } : trendMetric(steps, "count"),
  distanceMeters: distanceMeters === null ? { state: "empty", value: null, unit: null } : trendMetric(distanceMeters, "meters")
});

const trendDates = ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-01", "2026-08-02", "2026-08-03"];
const sevenDatesThrough = (date: string) => Array.from({ length: 7 }, (_, index) => {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - (6 - index));
  return value.toISOString().slice(0, 10);
});

const sleepPoint = (date: string, populated: boolean, napSeconds = 0, unclassifiedSeconds = 0) => ({
  date,
  nightSleepSeconds: populated ? trendMetric(25200, "seconds") : { state: "empty", value: null, unit: null },
  napsSeconds: populated ? trendMetric(napSeconds, "seconds") : { state: "empty", value: null, unit: null },
  stages: {
    awakeSeconds: populated ? trendMetric(1800, "seconds") : { state: "empty", value: null, unit: null },
    lightSeconds: populated ? trendMetric(12600 - unclassifiedSeconds, "seconds") : { state: "empty", value: null, unit: null },
    deepSeconds: populated ? trendMetric(5400, "seconds") : { state: "empty", value: null, unit: null },
    remSeconds: populated ? trendMetric(7200, "seconds") : { state: "empty", value: null, unit: null }
  },
  unclassifiedSeconds: populated ? trendMetric(unclassifiedSeconds, "seconds") : { state: "empty", value: null, unit: null },
  bedtime: populated ? "2026-08-03T23:00:00Z" : null,
  wakeTime: populated ? "2026-08-04T06:00:00Z" : null
});

const sleepTrendData = (date: string, populated: boolean) => ({
  logicalDate: date,
  range: "7d",
  bucketMode: "daily",
  nightSleepSeconds: { unit: "seconds", totalObserved: populated ? 25200 : null, averageObserved: populated ? 25200 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  napsSeconds: { unit: "seconds", totalObserved: populated ? 0 : null, averageObserved: populated ? 0 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  awakeSeconds: { unit: "seconds", totalObserved: populated ? 1800 : null, averageObserved: populated ? 1800 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  lightSeconds: { unit: "seconds", totalObserved: populated ? 9000 : null, averageObserved: populated ? 9000 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  deepSeconds: { unit: "seconds", totalObserved: populated ? 5400 : null, averageObserved: populated ? 5400 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  remSeconds: { unit: "seconds", totalObserved: populated ? 7200 : null, averageObserved: populated ? 7200 : null, observedDays: populated ? 1 : 0, expectedDays: 7 },
  observedDays: populated ? 1 : 0,
  points: sevenDatesThrough(date).map((pointDate) => sleepPoint(pointDate, populated && pointDate === date, 0, 3600))
});

async function installNavigationRoutes(page: import("@playwright/test").Page, sleepHandler: (route: import("@playwright/test").Route) => Promise<void>) {
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, summary: {} }, date) });
  });
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, range: "7d", bucketMode: "daily", steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, points: sevenDatesThrough(date).map((pointDate) => point(pointDate, null, null)) }, date) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", sleepHandler);
}

test("keeps sleep controls honest during a delayed navigation", async ({ page }) => {
  let releasePrevious: (() => void) | undefined;
  const previousPending = new Promise<void>((resolve) => { releasePrevious = resolve; });
  await installNavigationRoutes(page, async (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    if (date === "2026-07-27") await previousPending;
    await route.fulfill({ status: 200, json: contextEnvelope(sleepTrendData(date, true), date) });
  });

  await page.goto("/verify");
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
  await page.getByTestId("sleep-trend-previous").click();

  await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-07-27");
  await expect(page.getByTestId("sleep-trend-panel")).toBeVisible();
  await expect(page.getByTestId("sleep-trend-body")).toHaveAttribute("aria-busy", "true");
  await expect(page.getByTestId("sleep-trend-body")).toContainText("Cargando sueño para la fecha y ventana seleccionadas");
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toHaveCount(0);
  await expect(page.locator(".sleep-bar, .sleep-event, [data-tooltip]").filter({ visible: true })).toHaveCount(0);

  releasePrevious?.();
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
});

test("ignores superseded sleep responses after two rapid previous actions", async ({ page }) => {
  const releases = new Map<string, () => void>();
  const waits = new Map(["2026-07-27", "2026-07-20"].map((date) => [date, new Promise<void>((resolve) => releases.set(date, resolve))]));
  await installNavigationRoutes(page, async (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    await waits.get(date);
    await route.fulfill({ status: 200, json: contextEnvelope(sleepTrendData(date, true), date) });
  });

  await page.goto("/verify");
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
  await page.getByTestId("sleep-trend-previous").click();
  await page.getByTestId("sleep-trend-previous").click();
  await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-07-20");

  releases.get("2026-07-27")?.();
  await expect(page.getByTestId("sleep-trend-body")).toHaveAttribute("aria-busy", "true");
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toHaveCount(0);

  releases.get("2026-07-20")?.();
  await expect(page.getByTestId("sleep-trend-body")).toHaveAttribute("aria-busy", "false");
  await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-07-20");
  await expect(page.getByTestId("sleep-trend-context")).toContainText("2026-07-20");
  await expect(page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-day-label").last()).toContainText(/20|lun/i);
  await expect(page.getByTestId("sleep-trend-schedule-chart")).not.toContainText("2026-07-27");
});

test("renders the synthetic daily verification and independent trend controls", async ({ page }) => {
  test.setTimeout(90_000);
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));

  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => route.fulfill({
    status: 200,
    json: envelope({ logicalDate: "2026-08-03", summary: { steps: metric(8123, "count"), sleepDurationSeconds: metric(25200, "seconds") } })
  }));
  await page.route("**/api/v1/me/verify/activity-trend**", async (route) => {
    const url = new URL(route.request().url());
    const range = url.searchParams.get("range") || "7d";
    const timezone = url.searchParams.get("timezone") || "UTC";
    const dates = range === "daily" ? ["2026-08-03"] : trendDates;
    await route.fulfill({ status: 200, json: envelope({
      logicalDate: "2026-08-03",
      range,
      bucketMode: "daily",
       steps: { unit: "count", totalObserved: range === "daily" ? 8123 : 56892, averageObserved: range === "daily" ? 8123 : 8127.428, observedDays: dates.length, expectedDays: dates.length },
       distanceMeters: { unit: "meters", totalObserved: range === "daily" ? 5300 : 37100, averageObserved: 5300, observedDays: dates.length, expectedDays: dates.length },
       points: dates.map((date, index) => point(date, 8000 + index * 40, 5100 + index * 60))
    }, timezone) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", async (route) => {
    const url = new URL(route.request().url());
    const range = url.searchParams.get("range") || "7d";
    const timezone = url.searchParams.get("timezone") || "UTC";
    const expectedDays = range === "daily" ? 1 : range === "7d" ? 7 : range === "monthly" ? 31 : range === "180d" ? 180 : 365;
    if (range === "daily") {
      await route.fulfill({ status: 200, json: envelope({
        logicalDate: "2026-08-03",
        range,
        bucketMode: "daily",
       nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays },
       napsSeconds: { unit: "seconds", totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays },
       awakeSeconds: { unit: "seconds", totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays },
       lightSeconds: { unit: "seconds", totalObserved: 12600, averageObserved: 12600, observedDays: 1, expectedDays },
       deepSeconds: { unit: "seconds", totalObserved: 5400, averageObserved: 5400, observedDays: 1, expectedDays },
       remSeconds: { unit: "seconds", totalObserved: 7200, averageObserved: 7200, observedDays: 1, expectedDays },
       averageBedtime: "2026-08-03T23:00:00Z",
       averageWakeTime: "2026-08-04T06:00:00Z",
       observedDays: 1,
       points: [{ ...sleepPoint("2026-08-03", true, 1800), bedtime: "2026-08-03T22:00:00Z" }],
       intervals: [
         { start: "2026-08-03T22:00:00Z", end: "2026-08-03T22:15:00Z", category: "in_bed", isNap: false },
         { start: "2026-08-03T22:15:00Z", end: "2026-08-03T22:30:00Z", category: "unknown", isNap: false },
         { start: "2026-08-03T22:30:00Z", end: "2026-08-03T23:00:00Z", category: "awake", isNap: false },
         { start: "2026-08-03T23:00:00Z", end: "2026-08-04T02:30:00Z", category: "light", isNap: false },
         { start: "2026-08-04T02:30:00Z", end: "2026-08-04T04:00:00Z", category: "deep", isNap: false },
         { start: "2026-08-04T04:00:00Z", end: "2026-08-04T06:00:00Z", category: "rem", isNap: false },
         { start: "2026-08-04T13:00:00Z", end: "2026-08-04T13:30:00Z", category: "light", isNap: true }
       ]
      }, timezone) });
      return;
    }
    const dates = range === "7d"
      ? trendDates
      : range === "monthly"
        ? Array.from({ length: 31 }, (_, index) => `2026-08-${String(index + 1).padStart(2, "0")}`)
        : range === "180d"
          ? Array.from({ length: 7 }, (_, index) => `2026-${String(index + 2).padStart(2, "0")}-01`)
          : Array.from({ length: 12 }, (_, index) => `2026-${String(index + 1).padStart(2, "0")}-01`);
    await route.fulfill({ status: 200, json: envelope({
      logicalDate: "2026-08-03",
      range,
      bucketMode: range === "180d" || range === "annual" ? "calendar-month" : "daily",
       nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays },
       napsSeconds: { unit: "seconds", totalObserved: 0, averageObserved: 0, observedDays: 1, expectedDays },
       awakeSeconds: { unit: "seconds", totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays },
        lightSeconds: { unit: "seconds", totalObserved: 9000, averageObserved: 9000, observedDays: 1, expectedDays },
        deepSeconds: { unit: "seconds", totalObserved: 5400, averageObserved: 5400, observedDays: 1, expectedDays },
        remSeconds: { unit: "seconds", totalObserved: 7200, averageObserved: 7200, observedDays: 1, expectedDays },
      averageBedtime: "2026-08-03T23:00:00Z",
      averageWakeTime: "2026-08-04T06:00:00Z",
      observedDays: 1,
        points: dates.map((date) => sleepPoint(date, date === "2026-08-03" || (range !== "7d" && range !== "monthly" && date === dates[0]), 0, 3600))
    }, timezone) });
  });

  await page.goto("/verify");
  await expect(page).toHaveTitle(/Enano Coach/i);
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.locator("#activity-trend-title")).toContainText("Actividad por ventana", { timeout: 15_000 });
  await expect(page.locator("#sleep-trend-title")).toContainText("Sueño por ventana", { timeout: 15_000 });
   const activityCharts = page.getByTestId("activity-trend-charts");
   await expect(activityCharts.getByTestId("activity-trend-steps").locator(".trend-bar-numeric")).toHaveCount(7);
   await expect(activityCharts.getByTestId("activity-trend-distanceMeters").locator(".trend-bar-numeric")).toHaveCount(7);
  await expect(page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-bar-numeric')).toHaveCount(1);
  await expect(page.getByTestId("sleep-bedtime-guide")).toHaveCount(1);
  await expect(page.getByTestId("sleep-wake-guide")).toHaveCount(1);
  await expect(page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-grid span')).toHaveCount(7);
  await expect(page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-hour-axis span')).toHaveCount(7);
  await expect(page.getByTestId("sleep-trend-panel")).toHaveCSS("--sleep-bar-width", /.+/);
  const sleepControls = page.getByRole("group", { name: "Controles de ventana de sueño" });
  await expect(sleepControls).toBeVisible();
  await expect(sleepControls).toHaveAttribute("aria-labelledby", "sleep-controls-title");
  await page.getByRole("button", { name: "Duración" }).click();
  const initialDurationBar = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-bar").last();
  await expect(initialDurationBar.locator(".sleep-segment-unclassified")).toHaveCount(1);
  await expect(initialDurationBar.locator(".sleep-segment-awake")).toHaveCount(1);
  await expect(initialDurationBar.locator(".sleep-segment-light")).toHaveCount(1);
  await expect(initialDurationBar.locator(".sleep-segment-deep")).toHaveCount(1);
  await expect(initialDurationBar.locator(".sleep-segment-rem")).toHaveCount(1);
  const unclassifiedSegment = initialDurationBar.locator(".sleep-segment-unclassified");
  await expect(unclassifiedSegment).toHaveAttribute("data-tooltip", /Sin clasificar · Duración: 1 h · Estado: Observado/);
  await expect(unclassifiedSegment).not.toHaveAttribute("data-tooltip", /Sueño genérico|Ligero|Profundo|REM|Desconocido/);
  await page.getByTestId("sleep-trend-previous").click();
  await expect(page.getByRole("button", { name: "Duración" })).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("sleep-trend-next").click();
  await expect(page.getByRole("button", { name: "Duración" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Horario" }).click();

  const scheduleTicks = await page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-hour-axis span').evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    return { value: element.getAttribute("data-sleep-tick"), center: rect.top + rect.height / 2 };
  }));
  const scheduleGrid = await page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-grid span').evaluateAll((elements) => elements.map((element) => ({
    value: element.getAttribute("data-sleep-tick"),
    top: element.getBoundingClientRect().top
  })));
  expect(scheduleTicks).toHaveLength(scheduleGrid.length);
  scheduleTicks.forEach((tick, index) => {
    expect(tick.value).toBe(scheduleGrid[index].value);
    expect(Math.abs(tick.center - scheduleGrid[index].top)).toBeLessThanOrEqual(1);
  });
  await expect(page.locator("#activity-date")).toHaveValue("2026-08-03");

  const activityRange = page.getByRole("group", { name: "Seleccionar ventana" });
  const sleepRange = page.getByRole("group", { name: "Seleccionar ventana de sueño" });
  await activityRange.getByRole("button", { name: "Seleccionar ventana Diario" }).click();
  await expect(activityRange.getByRole("button", { name: "Seleccionar ventana Diario" })).toHaveAttribute("aria-pressed", "true");
  await expect(sleepRange.getByRole("button", { name: "Seleccionar ventana de sueño 7D" })).toHaveAttribute("aria-pressed", "true");

  await sleepRange.getByRole("button", { name: "Seleccionar ventana de sueño Diario" }).click();
  await expect(sleepRange.getByRole("button", { name: "Seleccionar ventana de sueño Diario" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
  await expect(page.getByLabel("Cronología de intervalos de sueño").locator(".sleep-event-light")).toHaveCount(2);
  await expect(page.getByLabel("Cronología de intervalos de sueño").locator(".sleep-event-deep")).toHaveCount(1);
  await expect(page.getByLabel("Cronología de intervalos de sueño").locator(".sleep-event-rem")).toHaveCount(1);
  await expect(page.getByLabel("Cronología de intervalos de sueño")).not.toContainText(/Ligero|Profundo|REM|Despierto/);
  const timelineSegments = page.getByLabel("Cronología de intervalos de sueño").locator(".sleep-event");
  await expect(timelineSegments).toHaveCount(7);
  let timelineHoverStyle: { opacity: string; fontFamily: string; zIndex: string; transitionDelay: string } | null = null;
  for (const timelineSegment of await timelineSegments.all()) {
    await expect(timelineSegment).toHaveClass(/chart-tooltip-target/);
    await expect(timelineSegment).toHaveAttribute("data-tooltip-primitive", "chart");
    await expect(timelineSegment).toHaveAttribute("data-tooltip-delay", "immediate");
    await expect(timelineSegment).toHaveAttribute("data-tooltip", /Duración:/);
    await expect(timelineSegment).toHaveAttribute("aria-label", /Duración:/);
    await timelineSegment.hover();
    const timelineTooltipState = await timelineSegment.evaluate((element) => {
      const style = getComputedStyle(element, "::after");
      return { content: style.content, dataTooltip: element.getAttribute("data-tooltip"), style: { opacity: style.opacity, fontFamily: style.fontFamily, zIndex: style.zIndex, transitionDelay: style.transitionDelay } };
    });
    expect(timelineTooltipState.content).toBe(`"${timelineTooltipState.dataTooltip}"`);
    timelineHoverStyle = timelineTooltipState.style;
    expect(timelineHoverStyle.opacity).toBe("1");
    await timelineSegment.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(timelineSegment).toBeFocused();
    const focusStyle = await timelineSegment.evaluate((element) => {
      const elementStyle = getComputedStyle(element);
      const tooltipStyle = getComputedStyle(element, "::after");
      return { outlineStyle: elementStyle.outlineStyle, outlineWidth: elementStyle.outlineWidth, tooltipOpacity: tooltipStyle.opacity };
    });
    expect(focusStyle).toEqual({ outlineStyle: "solid", outlineWidth: "3px", tooltipOpacity: "1" });
  }
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await expect(page.locator(".sleep-stage-card")).toHaveCount(0);
  const scheduleBar = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-composition-bar");
  const scheduleSegments = scheduleBar.locator(".sleep-segment");
  await expect(scheduleSegments).toHaveCount(4);
  const scheduleSleepingCategories = await scheduleSegments.evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter((name) => ["light", "deep", "rem"].includes(name || "")).sort());
  await expect(scheduleBar).toHaveAttribute("data-stage-orientation", "composition-only");
  await expect(scheduleSegments.first()).toHaveAttribute("data-tooltip-primitive", "chart");
  await expect(scheduleSegments.first()).toHaveAttribute("data-tooltip-delay", "immediate");
  await expect(scheduleBar.locator(".sleep-segment-awake")).toHaveAttribute("aria-label", /Despierto/);
  for (const scheduleSegment of await scheduleSegments.all()) {
    await scheduleSegment.hover();
    const scheduleBar = scheduleSegment.locator("xpath=ancestor::*[contains(@class, 'sleep-bar')][1]");
    const visibleTooltips = await scheduleBar.locator("xpath=. | .//*[@data-tooltip]").evaluateAll((elements) => elements.filter((element) => {
      const style = getComputedStyle(element, "::after");
      return style.opacity === "1" && style.visibility === "visible";
    }).length);
    expect(visibleTooltips).toBe(1);
  }
  await page.mouse.move(0, 0);
  await scheduleSegments.first().focus();
  await expect(scheduleSegments.first()).toBeFocused();
  const focusedScheduleTooltips = await scheduleSegments.first().locator("xpath=ancestor::*[contains(@class, 'sleep-bar')][1]").locator("xpath=. | .//*[@data-tooltip]").evaluateAll((elements) => elements.filter((element) => {
    const style = getComputedStyle(element, "::after");
    return style.opacity === "1" && style.visibility === "visible";
  }).length);
  expect(focusedScheduleTooltips).toBe(1);
  await expect(page.locator(".scope-note-inline")).toContainText("etapas específicas observadas");
  await expect(page.locator('[data-testid="sleep-trend-schedule-chart"] .sleep-bar-numeric')).toHaveCount(1);
  await expect(page.getByTestId("sleep-bedtime-guide")).toHaveCount(1);
  await expect(page.getByTestId("sleep-wake-guide")).toHaveCount(1);
  await page.getByTestId("sleep-trend-date").fill("2026-08-03");
  await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-08-03");
  await expect(activityRange.getByRole("button", { name: "Seleccionar ventana Diario" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Duración" }).click();
  await expect(page.getByTestId("sleep-trend-duration-chart")).toBeVisible();
  const durationBar = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-bar");
  await expect(durationBar).toHaveCount(1);
  await expect(durationBar.locator(".sleep-segment-night")).toHaveCount(0);
  await expect(durationBar.locator(".sleep-segment-light")).toHaveCount(1);
  await expect(durationBar.locator(".sleep-segment-awake")).toHaveCount(1);
  await expect(durationBar.locator(".sleep-segment-deep")).toHaveCount(1);
  await expect(durationBar.locator(".sleep-segment-rem")).toHaveCount(1);
  await expect(durationBar.locator(".sleep-segment-night, .sleep-segment-in_bed, .sleep-segment-unknown")).toHaveCount(0);
  const durationSleepingCategories = await durationBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter((name) => ["night", "light", "deep", "rem"].includes(name || "")).map((name) => name === "night" ? "sleeping" : name).sort());
  expect(scheduleSleepingCategories).toEqual(durationSleepingCategories);
  await expect(durationBar.locator(".sleep-segment-nap")).toHaveCount(0);
  await expect(durationBar).toHaveAttribute("data-tooltip", /Ligero.*Profundo.*REM/);
  await expect(durationBar).not.toHaveAttribute("data-tooltip", /Siesta/);
  await expect(durationBar).toHaveAttribute("data-stage-orientation", "vertical-stack");
  await expect(durationBar.locator(".sleep-segment-light")).toHaveAttribute("data-tooltip-primitive", "chart");
  await expect(durationBar.locator(".sleep-segment-light")).toHaveAttribute("data-tooltip-delay", "immediate");
  await durationBar.locator(".sleep-segment-light").focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(durationBar.locator(".sleep-segment-light")).toBeFocused();
  const focusedDurationTooltips = await durationBar.locator("xpath=. | .//*[@data-tooltip]").evaluateAll((elements) => elements.filter((element) => {
    const style = getComputedStyle(element, "::after");
    return style.opacity === "1" && style.visibility === "visible";
  }).length);
  expect(focusedDurationTooltips).toBe(1);
  await durationBar.locator(".sleep-segment-deep").hover();
  const visibleDurationTooltips = await durationBar.locator("xpath=. | .//*[@data-tooltip]").evaluateAll((elements) => elements.filter((element) => {
    const style = getComputedStyle(element, "::after");
    return style.opacity === "1" && style.visibility === "visible";
  }).length);
  expect(visibleDurationTooltips).toBe(1);
  expect(await durationBar.locator(".sleep-segment-light").evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("0");
  const tooltipStyle = await durationBar.locator(".sleep-segment-deep").evaluate((element) => {
    const style = getComputedStyle(element, "::after");
    return { opacity: style.opacity, fontFamily: style.fontFamily, zIndex: style.zIndex, transitionDelay: style.transitionDelay };
  });
  expect(tooltipStyle.opacity).toBe("1");
  expect(tooltipStyle.fontFamily).toMatch(/IBM Plex Mono|monospace/);
  expect(Number(tooltipStyle.zIndex)).toBeGreaterThanOrEqual(20);
  expect(tooltipStyle.transitionDelay).toBe("0s");
  const activityBar = activityCharts.getByTestId("activity-trend-steps").locator(".trend-bar-numeric").first();
  await expect(activityBar).toHaveAttribute("data-tooltip-delay", "immediate");
  await activityBar.focus();
  await expect(activityBar).toBeFocused();
  await activityBar.hover();
  const activityTooltipStyle = await activityBar.evaluate((element) => {
    const style = getComputedStyle(element, "::after");
    return { opacity: style.opacity, fontFamily: style.fontFamily, zIndex: style.zIndex, transitionDelay: style.transitionDelay };
  });
  expect(activityTooltipStyle).toEqual(tooltipStyle);
  expect(timelineHoverStyle).toEqual(tooltipStyle);
  const obsoleteSelectors = await page.evaluate(() => Array.from(document.styleSheets).flatMap((sheet) => Array.from(sheet.cssRules)).map((rule) => rule instanceof CSSStyleRule ? rule.selectorText : "").filter((selector) => /sleep-nap|sleep-segment-nap|sleep-event-tooltip/.test(selector)));
  expect(obsoleteSelectors).toEqual([]);
  await expect(page.locator(".sleep-summary")).toContainText("Total siestas");
  const durationTicks = await page.locator('[data-testid="sleep-trend-duration-chart"] .sleep-duration-axis span').evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    return { value: element.getAttribute("data-sleep-tick"), center: rect.top + rect.height / 2 };
  }));
  const durationGrid = await page.locator('[data-testid="sleep-trend-duration-chart"] .sleep-grid span').evaluateAll((elements) => elements.map((element) => ({
    value: element.getAttribute("data-sleep-tick"),
    top: element.getBoundingClientRect().top
  })));
  expect(durationTicks).toHaveLength(durationGrid.length);
  durationTicks.forEach((tick, index) => {
    expect(tick.value).toBe(durationGrid[index].value);
    expect(Math.abs(tick.center - durationGrid[index].top)).toBeLessThanOrEqual(1);
  });
  await expect(page.getByRole("button", { name: "Duración" })).toHaveAttribute("aria-pressed", "true");
  const rangeButtons = page.getByRole("group", { name: "Seleccionar ventana de sueño" });
  for (const rangeName of ["Diario", "7D", "1M"] as const) {
    await rangeButtons.getByRole("button", { name: `Seleccionar ventana de sueño ${rangeName}` }).click();
    await expect(page.getByRole("button", { name: "Duración" })).toHaveAttribute("aria-pressed", "true");
    const currentDurationBar = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-bar-numeric").last();
    const durationWidth = await currentDurationBar.evaluate((element) => element.getBoundingClientRect().width);
    const durationCategories = await currentDurationBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
    await page.getByRole("button", { name: "Horario" }).click();
    const currentScheduleBar = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-bar-numeric").last();
    const scheduleWidth = await currentScheduleBar.evaluate((element) => element.getBoundingClientRect().width);
    expect(Math.abs(scheduleWidth - durationWidth), `${rangeName}: schedule ${scheduleWidth}px, duration ${durationWidth}px`).toBeLessThanOrEqual(0.5);
    if (rangeName !== "Diario") {
      const scheduleCategories = await currentScheduleBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
      expect(scheduleCategories).toEqual(durationCategories);
      expect(scheduleCategories).toEqual(["awake", "deep", "light", "rem", "unclassified"]);
      await expect(currentScheduleBar).toHaveAttribute("data-stage-orientation", "composition-only");
      await expect(currentScheduleBar.locator(".sleep-segment-unclassified")).toHaveAttribute("aria-label", /Sin clasificar · Duración: 1 h · Estado: Observado/);
      await expect(currentScheduleBar.locator(".sleep-segment-unclassified")).not.toHaveAttribute("aria-label", /→|Horario/);
      await expect(currentScheduleBar.locator(".sleep-segment-awake")).toHaveCount(1);
      await expect(currentScheduleBar.locator(".sleep-segment-in_bed, .sleep-segment-unknown")).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Duración" }).click();
  }
  for (const rangeName of ["180D", "Anual", "7D"] as const) {
    await rangeButtons.getByRole("button", { name: `Seleccionar ventana de sueño ${rangeName}` }).click();
    await expect(page.getByTestId("sleep-trend-duration-chart")).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Duración" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Horario" }).click();
  for (const rangeName of ["Diario", "1M", "180D", "Anual", "7D"] as const) {
    await rangeButtons.getByRole("button", { name: `Seleccionar ventana de sueño ${rangeName}` }).click();
  }
  await expect(page.getByRole("button", { name: "Horario" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
  await expect(page.getByTestId("sleep-bedtime-guide")).toHaveCount(1);
  await expect(page.getByTestId("sleep-wake-guide")).toHaveCount(1);
  await expect(page.locator('[aria-label="Escala de hora local"] span')).toHaveText(["08:00", "06:00", "04:00", "02:00", "00:00", "22:00", "20:00"]);

  await expect(page.locator("body")).toContainText("Fin lógico seleccionado: 2026-08-03");
  await expect(page.locator(".sleep-summary")).not.toContainText("2026-08-03");
  expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
  expect(failedRequests, `failed requests: ${failedRequests.join(" | ")}`).toEqual([]);
});

test("keeps each selected sleep mode through date loading, empty, error, refetch, and recovery", async ({ page }) => {
  let releaseLoading: (() => void) | null = null;
  let recoverError = false;
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, summary: {} }, date) });
  });
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, range: "7d", bucketMode: "daily", steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, points: sevenDatesThrough(date).map((pointDate) => point(pointDate, null, null)) }, date) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", async (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    if (date === "2026-08-02") await new Promise<void>((resolve) => { releaseLoading = resolve; });
    if (date === "2026-07-31" && !recoverError) {
      await route.fulfill({ status: 504, json: { ...contextEnvelope(null, date), error: { code: "UPSTREAM_TIMEOUT", message: "No se pudo completar la consulta.", requestId: "req-demo-mode", retryable: true, field: null } } });
      return;
    }
    await route.fulfill({ status: 200, json: contextEnvelope(sleepTrendData(date, date !== "2026-08-01"), date) });
  });

  for (const mode of ["Duración", "Horario"] as const) {
    recoverError = false;
    await page.goto("/verify");
    await page.locator("#context-date").fill("2026-08-03");
    await page.locator("#context-timezone").selectOption("UTC");
    await page.getByRole("button", { name: "Consultar", exact: true }).click();
    await expect(page.locator("#sleep-trend-title")).toBeVisible();
    if (mode === "Duración") await page.getByRole("button", { name: mode }).click();
    await expect(page.getByRole("button", { name: mode })).toHaveAttribute("aria-pressed", "true");

    await page.getByTestId("sleep-trend-date").fill("2026-08-02");
    await expect(page.getByTestId("sleep-trend-panel")).toBeVisible();
    await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-08-02");
    await expect(page.getByTestId("sleep-trend-previous")).toBeEnabled();
    releaseLoading?.();
    await expect(page.getByRole("button", { name: mode })).toHaveAttribute("aria-pressed", "true");

    await page.getByTestId("sleep-trend-date").fill("2026-08-01");
    await expect(page.getByTestId("sleep-trend-panel")).toContainText("No hay datos de sueño para esta ventana.");
    await expect(page.getByRole("button", { name: mode })).toHaveAttribute("aria-pressed", "true");

    await page.getByTestId("sleep-trend-date").fill("2026-07-31");
    await expect(page.getByText("No se pudo cargar el sueño para la fecha y ventana seleccionadas; los controles siguen disponibles.")).toBeVisible();
    recoverError = true;
    await page.locator("#context-date").fill("2026-07-30");
    await page.getByRole("button", { name: "Consultar", exact: true }).click();
    await expect(page.getByRole("button", { name: mode })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId(mode === "Duración" ? "sleep-trend-duration-chart" : "sleep-trend-schedule-chart")).toBeVisible();
  }
});

test("keeps sleep navigation mounted while a backward window is loading", async ({ page }) => {
  let releaseBackward: (() => void) | null = null;
  const requestedDates: string[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED") failedRequests.push(request.method());
  });
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, summary: {} }, date) });
  });
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, range: "7d", bucketMode: "daily", steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 }, points: sevenDatesThrough(date).map((pointDate) => point(pointDate, null, null)) }, date) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", async (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    requestedDates.push(date);
    if (date === "2026-07-27") await new Promise<void>((resolve) => { releaseBackward = resolve; });
    await route.fulfill({ status: 200, json: contextEnvelope(sleepTrendData(date, true), date) });
  });

  await page.goto("/verify");
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByTestId("sleep-trend-panel")).toBeVisible();
  await page.getByTestId("sleep-trend-previous").click();

  await expect(page.getByTestId("sleep-trend-panel")).toBeVisible();
  await expect(page.getByTestId("sleep-trend-previous")).toBeEnabled();
  await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-07-27");
  expect(requestedDates).toContain("2026-07-27");
  expect(await page.evaluate(() => document.documentElement.innerHTML.includes("NaN") || document.documentElement.innerHTML.includes("Infinity"))).toBe(false);

  releaseBackward?.();
  await expect(page.getByTestId("sleep-trend-panel")).toContainText("Sueño por ventana");
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("renders staged sleep without horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => route.fulfill({ status: 200, json: envelope({ logicalDate: "2026-08-03", summary: { sleepDurationSeconds: metric(25200, "seconds") } }) }));
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => route.fulfill({ status: 200, json: envelope({ logicalDate: "2026-08-03", range: "daily", bucketMode: "daily", steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 }, points: [point("2026-08-03", null, null)] }) }));
  await page.route("**/api/v1/me/verify/sleep-trend**", (route) => route.fulfill({ status: 200, json: envelope({
    logicalDate: "2026-08-03", range: "daily", bucketMode: "daily",
    nightSleepSeconds: { unit: "seconds", totalObserved: 25200, averageObserved: 25200, observedDays: 1, expectedDays: 1 },
    napsSeconds: { unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 1 },
    awakeSeconds: { unit: "seconds", totalObserved: 1800, averageObserved: 1800, observedDays: 1, expectedDays: 1 },
    lightSeconds: { unit: "seconds", totalObserved: 12600, averageObserved: 12600, observedDays: 1, expectedDays: 1 },
    deepSeconds: { unit: "seconds", totalObserved: 5400, averageObserved: 5400, observedDays: 1, expectedDays: 1 },
    remSeconds: { unit: "seconds", totalObserved: 7200, averageObserved: 7200, observedDays: 1, expectedDays: 1 },
    observedDays: 1,
    points: [sleepPoint("2026-08-03", true)],
    intervals: [
      { start: "2026-08-03T23:00:00Z", end: "2026-08-04T02:30:00Z", category: "light", isNap: false },
      { start: "2026-08-04T02:30:00Z", end: "2026-08-04T04:00:00Z", category: "deep", isNap: false },
      { start: "2026-08-04T04:00:00Z", end: "2026-08-04T06:00:00Z", category: "rem", isNap: false }
    ]
  }) }));

  await page.goto("/verify");
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await page.getByRole("button", { name: "Seleccionar ventana de sueño Diario" }).click();
  const previous = page.getByTestId("sleep-trend-previous");
  await previous.click({ trial: true });
  expect(await previous.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return target === element || element.contains(target);
  })).toBe(true);
  await expect(page.getByLabel("Cronología de intervalos de sueño")).toBeVisible();
  await expect(page.getByTestId("sleep-trend-panel")).toHaveCSS("--sleep-bar-width", /.+/);
  const mobileTimelineSegments = page.getByLabel("Cronología de intervalos de sueño").locator(".sleep-event");
  for (const mobileTimelineSegment of await mobileTimelineSegments.all()) {
    await mobileTimelineSegment.hover();
    expect(await mobileTimelineSegment.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("visible");
    await mobileTimelineSegment.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    expect(await mobileTimelineSegment.evaluate((element) => ({
      outline: getComputedStyle(element).outlineStyle,
      tooltip: getComputedStyle(element, "::after").visibility,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    }))).toEqual({ outline: "solid", tooltip: "visible", overflow: 0 });
  }
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await expect(page.locator(".sleep-stage-card")).toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("keeps every mobile activity range hit target clear of window navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requestedRanges: string[] = [];
  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope({ logicalDate: date, summary: {} }, date) });
  });
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => {
    const url = new URL(route.request().url());
    const date = url.searchParams.get("date") || "2026-08-03";
    const range = url.searchParams.get("range") || "7d";
    requestedRanges.push(range);
    const dates = range === "annual"
      ? Array.from({ length: 12 }, (_, index) => `${date.slice(0, 4)}-${String(index + 1).padStart(2, "0")}-01`)
      : sevenDatesThrough(date);
    return route.fulfill({ status: 200, json: contextEnvelope({
      logicalDate: date,
      range,
      bucketMode: range === "annual" ? "calendar-month" : "daily",
      steps: { unit: "count", totalObserved: 84000, averageObserved: 7000, observedDays: dates.length, expectedDays: range === "annual" ? 365 : 7 },
      distanceMeters: { unit: "meters", totalObserved: 50400, averageObserved: 4200, observedDays: dates.length, expectedDays: range === "annual" ? 365 : 7 },
      points: dates.map((pointDate, index) => point(pointDate, 7000 + index * 100, 4200 + index * 50))
    }, date) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", (route) => {
    const date = new URL(route.request().url()).searchParams.get("date") || "2026-08-03";
    return route.fulfill({ status: 200, json: contextEnvelope(sleepTrendData(date, true), date) });
  });

  await page.goto("/verify");
  await page.locator("#context-date").fill("2026-08-03");
  await page.locator("#context-timezone").selectOption("UTC");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByTestId("activity-trend-panel")).toBeVisible();

  const activityRanges = page.getByRole("group", { name: "Seleccionar ventana", exact: true });
  await activityRanges.scrollIntoViewIfNeeded();
  const rangeButtons = activityRanges.getByRole("button");
  const hitTargets = await rangeButtons.evaluateAll((buttons) => buttons.map((button) => {
    const rect = button.getBoundingClientRect();
    const owner = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      label: button.getAttribute("aria-label"),
      height: rect.height,
      centerOwner: owner instanceof HTMLElement ? `${owner.tagName}.${owner.className}` : null,
      ownsCenter: owner === button || button.contains(owner)
    };
  }));
  expect(hitTargets).toHaveLength(5);
  expect(hitTargets.filter((target) => !target.ownsCenter)).toEqual([]);
  expect(hitTargets.filter((target) => target.height < 43)).toEqual([]);

  const previous = page.getByRole("button", { name: "Ventana anterior", exact: true });
  const next = page.getByRole("button", { name: "Ventana siguiente", exact: true });
  for (const navigation of [previous, next]) {
    expect(await navigation.evaluate((button, ranges) => {
      const navigationRect = button.getBoundingClientRect();
      return Array.from(document.querySelectorAll(ranges)).every((rangeButton) => {
        const rangeRect = rangeButton.getBoundingClientRect();
        return navigationRect.right <= rangeRect.left
          || navigationRect.left >= rangeRect.right
          || navigationRect.bottom <= rangeRect.top
          || navigationRect.top >= rangeRect.bottom;
      });
    }, '[aria-label="Seleccionar ventana"] button')).toBe(true);
  }

  const annual = activityRanges.getByRole("button", { name: "Seleccionar ventana Anual" });
  const annualResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/me/verify/activity-trend" && url.searchParams.get("range") === "annual";
  });
  await annual.click();
  expect((await annualResponse).status()).toBe(200);
  await expect(annual).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("activity-trend-panel").locator(".section-aside")).toHaveText("Anual");
  await expect(page.getByTestId("activity-trend-charts").locator(".trend-bar-numeric")).toHaveCount(24);

  await previous.click();
  await expect(previous).toBeEnabled();
  await next.click();
  expect(requestedRanges.filter((range) => range === "annual").length).toBeGreaterThanOrEqual(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test("keeps an empty cold-open window selected and renders an honest empty month", async ({ page }) => {
  const requestedSleepDates: string[] = [];
  const dateRange = (end: string, count: number) => Array.from({ length: count }, (_, index) => {
    const value = new Date(`${end}T00:00:00Z`);
    value.setUTCDate(value.getUTCDate() - (count - 1 - index));
    return value.toISOString().slice(0, 10);
  });
  const scopedEnvelope = (data: unknown, logicalDate: string, expectedDays: number, timezone: string) => {
    const next = new Date(`${logicalDate}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    return {
      ...envelope(data),
      timezone,
      coverage: {
        requested: { logicalDate, from: `${logicalDate}T00:00:00Z`, to: next.toISOString().replace(".000Z", "Z"), timezone },
        expectedDays,
        availableDays: 0,
        isPartial: false,
        byDomain: { activity: { expectedDays, availableDays: 0, state: "empty" }, sleep: { expectedDays, availableDays: 0, state: "empty" } }
      }
    };
  };
  const emptyAggregate = (expectedDays: number) => ({ state: "empty", unit: "seconds", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays });

  await page.route("**/api/v1/session", (route) => route.fulfill({ status: 200, json: envelope({ authenticated: true, accessState: "active", canReadVerification: true }) }));
  await page.route("**/api/v1/me/verify/overview**", (route) => {
    const url = new URL(route.request().url());
    const logicalDate = url.searchParams.get("date") || "2026-08-03";
    const timezone = url.searchParams.get("timezone") || "UTC";
    return route.fulfill({ status: 200, json: scopedEnvelope({ logicalDate, summary: {} }, logicalDate, 1, timezone) });
  });
  await page.route("**/api/v1/me/verify/activity-trend**", (route) => {
    const url = new URL(route.request().url());
    const logicalDate = url.searchParams.get("date") || "2026-08-03";
    const timezone = url.searchParams.get("timezone") || "UTC";
    const dates = dateRange(logicalDate, 7);
    return route.fulfill({ status: 200, json: scopedEnvelope({
      logicalDate,
      range: "7d",
      bucketMode: "daily",
      steps: { unit: "count", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 },
      distanceMeters: { unit: "meters", totalObserved: null, averageObserved: null, observedDays: 0, expectedDays: 7 },
      points: dates.map((date) => point(date, null, null))
    }, logicalDate, 7, timezone) });
  });
  await page.route("**/api/v1/me/verify/sleep-trend**", (route) => {
    const url = new URL(route.request().url());
    const logicalDate = url.searchParams.get("date") || "2026-08-03";
    const timezone = url.searchParams.get("timezone") || "UTC";
    const range = url.searchParams.get("range") === "monthly" ? "monthly" : "7d";
    requestedSleepDates.push(logicalDate);
    const monthDays = new Date(Date.UTC(Number(logicalDate.slice(0, 4)), Number(logicalDate.slice(5, 7)), 0)).getUTCDate();
    const expectedDays = range === "monthly" ? monthDays : 7;
    const dates = range === "monthly"
      ? Array.from({ length: monthDays }, (_, index) => `${logicalDate.slice(0, 7)}-${String(index + 1).padStart(2, "0")}`)
      : dateRange(logicalDate, 7);
    return route.fulfill({ status: 200, json: scopedEnvelope({
      logicalDate,
      range,
      bucketMode: "daily",
      nightSleepSeconds: emptyAggregate(expectedDays),
      napsSeconds: emptyAggregate(expectedDays),
      awakeSeconds: emptyAggregate(expectedDays),
      lightSeconds: emptyAggregate(expectedDays),
      deepSeconds: emptyAggregate(expectedDays),
      remSeconds: emptyAggregate(expectedDays),
      observedDays: 0,
      averageBedtime: null,
      averageWakeTime: null,
      points: dates.map((date) => sleepPoint(date, false)),
      intervals: []
    }, logicalDate, expectedDays, timezone) });
  });

  await page.goto("/verify");
  const selectedDate = await page.getByTestId("sleep-trend-date").inputValue();
  await expect(page.getByTestId("sleep-trend-date")).toHaveValue(selectedDate);
  await expect(page.locator(".sleep-trend-panel .trend-coverage-note")).toContainText("No hay datos de sueño para esta ventana.");
  expect(new Set(requestedSleepDates)).toEqual(new Set([selectedDate]));

  await page.getByRole("button", { name: "Seleccionar ventana de sueño 1M" }).click();
  const emptyScheduleBars = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-bar");
  await expect(page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-bar-numeric")).toHaveCount(0);
  const emptyScheduleStyles = await emptyScheduleBars.evaluateAll((elements) => elements.map((element) => {
    const style = getComputedStyle(element);
    return { height: element.getBoundingClientRect().height, minHeight: style.minHeight, borderWidth: style.borderWidth };
  }));
  expect(emptyScheduleStyles.filter((style) => style.height !== 0 || style.minHeight !== "0px")).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "Duración" }).click();
  const emptyBars = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-bar");
  await expect(emptyBars).toHaveCount(new Date(Date.UTC(Number(selectedDate.slice(0, 4)), Number(selectedDate.slice(5, 7)), 0)).getUTCDate());
  await expect(page.getByTestId("sleep-trend-duration-chart").locator(".sleep-bar-numeric")).toHaveCount(0);
  expect(await emptyBars.evaluateAll((elements) => elements.every((element) => {
    const style = getComputedStyle(element);
    return element.getBoundingClientRect().height === 0 && style.minHeight === "0px";
  }))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  expect(new Set(requestedSleepDates)).toEqual(new Set([selectedDate]));
});
