import { expect, test } from "@playwright/test";

test.describe("fresh browser validation", () => {
  test.use({ storageState: undefined });

  for (const [name, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]] as const) {
    test(`validates ${name} viewport`, async ({ browser }) => {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const consoleErrors: string[] = [];
      const failedRequests: string[] = [];
      const apiRequests: string[] = [];
      const devtoolRequests: string[] = [];
      page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
      page.on("requestfailed", (request) => {
        if (request.failure()?.errorText !== "net::ERR_ABORTED") failedRequests.push(request.method());
      });
      page.on("request", (request) => {
        const url = new URL(request.url());
        if (url.pathname.startsWith("/api/")) apiRequests.push(`${request.method()} ${url.pathname}`);
        if (url.pathname === "/@vite/client") devtoolRequests.push(`${request.method()} ${url.pathname}`);
      });
      await page.goto("/verify");
      await page.waitForLoadState("networkidle");
      await page.locator("#context-date").fill("2026-08-03");
      const activityResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/api/v1/me/verify/activity-trend" && url.searchParams.get("date") === "2026-08-03";
      });
      const sleepResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/api/v1/me/verify/sleep-trend" && url.searchParams.get("date") === "2026-08-03";
      });
      await page.getByRole("button", { name: "Consultar", exact: true }).click();
      const activityStatus = (await activityResponse).status();
      const sleepStatus = (await sleepResponse).status();
      expect(activityStatus, "activity trend response must succeed before asserting its section").toBe(200);
      expect(sleepStatus, "sleep trend response must succeed before asserting its section").toBe(200);
      await expect(page.locator("#activity-trend-title")).toContainText("Actividad por ventana", { timeout: 15_000 });
      await expect(page.locator("#sleep-trend-title")).toContainText("Sueño por ventana", { timeout: 15_000 });
      await page.getByRole("button", { name: "Seleccionar ventana Diario" }).click();
      await page.getByRole("button", { name: "Seleccionar ventana de sueño Diario" }).click();
      await page.getByRole("button", { name: "Duración" }).click();
      await expect(page.getByTestId("sleep-trend-duration-chart")).toBeVisible();
      await expect(page.locator(".sleep-duration-bar")).not.toHaveCount(0);
      const liveStageSegments = page.locator(".sleep-duration-bar .sleep-segment");
      expect(await liveStageSegments.count()).toBeGreaterThan(0);
      const liveDurationBar = liveStageSegments.first().locator("..");
      await expect(liveDurationBar).toHaveAttribute("data-stage-orientation", "vertical-stack");
      expect(await liveDurationBar.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(0);
      await liveDurationBar.locator(".sleep-segment-light").hover();
      expect(await liveDurationBar.locator("xpath=. | .//*[@data-tooltip]").evaluateAll((elements) => elements.filter((element) => {
        const style = getComputedStyle(element, "::after");
        return style.opacity === "1" && style.visibility === "visible";
      }).length)).toBe(1);
      await expect(page.locator(".sleep-stage-card")).toHaveCount(0);
      await expect(page.locator(".sleep-duration-bar")).not.toHaveCount(0);
      await expect(page.getByRole("group", { name: "Controles de ventana de sueño" })).toHaveAttribute("aria-labelledby", "sleep-controls-title");
      await page.getByRole("button", { name: "Horario" }).click();
      await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
      const liveScheduleSegments = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-segment");
      expect(await liveScheduleSegments.count()).toBeGreaterThan(0);
      expect(await liveScheduleSegments.evaluateAll((elements) => elements.every((element) => element.tabIndex === 0))).toBe(true);
      expect(await liveScheduleSegments.evaluateAll((elements) => new Set(elements.map((element) => getComputedStyle(element).backgroundColor)).size)).toBeGreaterThan(1);
      await expect(page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-segment-awake")).not.toHaveCount(0);
      await expect(page.locator("body")).toContainText("Fin lógico seleccionado: 2026-08-03");
      await expect(page.locator(".trend-axis")).toHaveCount(2);
      const activityAverageGuides = page.locator("[data-testid=activity-trend-panel] .trend-average-guide");
      expect(await activityAverageGuides.count()).toBeLessThanOrEqual(2);
      const scheduleGrid = page.locator("[data-testid=sleep-trend-schedule-chart] .sleep-grid span");
      const scheduleAxis = page.locator("[data-testid=sleep-trend-schedule-chart] .sleep-hour-axis span");
      expect(await scheduleGrid.count()).toBe(await scheduleAxis.count());
      expect(await page.locator("[data-testid=activity-trend-panel] .trend-bar-numeric").count()).toBeLessThanOrEqual(2);
      const sevenDayResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/api/v1/me/verify/sleep-trend" && url.searchParams.get("range") === "7d";
      });
      await page.getByRole("button", { name: "Seleccionar ventana de sueño 7D" }).click();
      expect((await sevenDayResponse).status()).toBe(200);
      const sevenDayScheduleBar = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-composition-bar").first();
      await expect(sevenDayScheduleBar).toHaveAttribute("data-stage-orientation", "composition-only");
       const sevenDayScheduleCategories = await sevenDayScheduleBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
        expect(sevenDayScheduleCategories).toEqual(expect.arrayContaining(["deep", "light", "rem"]));
        expect(sevenDayScheduleCategories.every((category) => ["awake", "deep", "light", "rem", "unclassified"].includes(category || ""))).toBe(true);
       expect(sevenDayScheduleCategories.filter((category) => category === "awake").length).toBeLessThanOrEqual(1);
      expect(sevenDayScheduleCategories).not.toContain("in_bed");
      expect(sevenDayScheduleCategories).not.toContain("unknown");
       expect(await sevenDayScheduleBar.locator(".sleep-segment").evaluateAll((elements) => elements.every((element) => !/[→]|Horario/.test(element.getAttribute("aria-label") || "")))).toBe(true);
       const sevenDayScheduleSegment = sevenDayScheduleBar.locator(".sleep-segment").first();
       await sevenDayScheduleSegment.hover();
       expect(await sevenDayScheduleSegment.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("visible");
       await sevenDayScheduleSegment.focus();
       await page.keyboard.press("Shift+Tab");
       await page.keyboard.press("Tab");
       expect(await sevenDayScheduleSegment.evaluate((element) => ({
         outline: getComputedStyle(element).outlineStyle,
         tooltip: getComputedStyle(element, "::after").visibility,
         overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
       }))).toEqual({ outline: "solid", tooltip: "visible", overflow: 0 });
       const sevenDayScheduleWidth = await sevenDayScheduleBar.evaluate((element) => element.getBoundingClientRect().width);
      await page.getByRole("button", { name: "Duración" }).click();
      const sevenDayDurationBars = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-bar");
      await expect(sevenDayDurationBars).toHaveCount(7);
      const sevenDayDurationBar = sevenDayDurationBars.filter({ has: page.locator(".sleep-segment") }).first();
      const sevenDayDurationCategories = await sevenDayDurationBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
      expect(sevenDayScheduleCategories).toEqual(sevenDayDurationCategories);
      expect(Math.abs(sevenDayScheduleWidth - await sevenDayDurationBar.evaluate((element) => element.getBoundingClientRect().width))).toBeLessThanOrEqual(0.5);
      const monthlyResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/api/v1/me/verify/sleep-trend" && url.searchParams.get("range") === "monthly";
      });
      await page.getByRole("button", { name: "Seleccionar ventana de sueño 1M" }).click();
      expect((await monthlyResponse).status()).toBe(200);
      const monthlyDurationBars = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-bar");
      await expect(monthlyDurationBars).toHaveCount(31);
       const monthlyDurationBar = monthlyDurationBars.filter({ has: page.locator(".sleep-segment") }).first();
       const monthlyDurationCategories = await monthlyDurationBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
        expect(monthlyDurationCategories).toEqual(expect.arrayContaining(["deep", "light", "rem"]));
         expect(monthlyDurationCategories.every((category) => ["awake", "deep", "light", "rem", "unclassified"].includes(category || ""))).toBe(true);
       const monthlyDurationWidth = await monthlyDurationBar.evaluate((element) => element.getBoundingClientRect().width);
      await page.getByRole("button", { name: "Horario" }).click();
      const monthlyScheduleBar = page.getByTestId("sleep-trend-schedule-chart").locator(".sleep-composition-bar").first();
      const monthlyScheduleCategories = await monthlyScheduleBar.locator(".sleep-segment").evaluateAll((elements) => elements.map((element) => Array.from(element.classList).find((name) => name.startsWith("sleep-segment-"))?.replace("sleep-segment-", "")).filter(Boolean).sort());
      expect(monthlyScheduleCategories).toEqual(monthlyDurationCategories);
      expect(Math.abs(await monthlyScheduleBar.evaluate((element) => element.getBoundingClientRect().width) - monthlyDurationWidth)).toBeLessThanOrEqual(0.5);
      await page.getByTestId("sleep-trend-date").fill("2026-08-02");
      await expect(page.getByRole("button", { name: "Horario" })).toHaveAttribute("aria-pressed", "true");
      await page.getByTestId("sleep-trend-date").fill("2026-08-03");
      await expect(page.getByRole("button", { name: "Horario" })).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator(".sleep-summary")).not.toContainText(/Ligero|Profundo|REM|Despierto/);
      await page.getByRole("button", { name: "Seleccionar ventana de sueño Diario" }).click();
      await page.getByTestId("sleep-trend-previous").click();
      await page.getByTestId("sleep-trend-previous").click();
      await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-08-01");
      await expect(page.getByTestId("sleep-trend-body")).toHaveAttribute("aria-busy", "false", { timeout: 15_000 });
      await expect(page.getByTestId("sleep-trend-context")).toContainText("2026-08-01");
      await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
      await page.getByRole("button", { name: "Seleccionar ventana de sueño 7D" }).click();
      await page.getByTestId("sleep-trend-previous").click();
      await page.getByTestId("sleep-trend-previous").click();
      await expect(page.getByTestId("sleep-trend-date")).toHaveValue("2026-07-18");
      await expect(page.getByTestId("sleep-trend-body")).toHaveAttribute("aria-busy", "false", { timeout: 15_000 });
      await expect(page.getByTestId("sleep-trend-context")).toContainText("2026-07-18");
      await expect(page.getByTestId("sleep-trend-schedule-chart")).toBeVisible();
      const activityRanges = page.getByRole("group", { name: "Seleccionar ventana", exact: true });
      for (const [rangeName, rangeValue] of [["7D", "7d"], ["180D", "180d"], ["Anual", "annual"]] as const) {
        const response = page.waitForResponse((candidate) => {
          const url = new URL(candidate.url());
          return url.pathname === "/api/v1/me/verify/activity-trend" && url.searchParams.get("range") === rangeValue;
        });
        const button = activityRanges.getByRole("button", { name: `Seleccionar ventana ${rangeName}` });
        await button.click();
        expect((await response).status()).toBe(200);
        await expect(button).toHaveAttribute("aria-pressed", "true");
        for (const axis of await page.getByTestId("activity-trend-panel").locator(".trend-axis").all()) {
          const tickRects = await axis.locator("span").evaluateAll((ticks) => ticks.map((tick) => {
            const rect = tick.getBoundingClientRect();
            return { top: rect.top, bottom: rect.bottom, finite: [rect.top, rect.bottom, rect.left, rect.right].every(Number.isFinite) };
          }));
          expect(tickRects.length).toBeGreaterThanOrEqual(4);
          expect(tickRects.length).toBeLessThanOrEqual(6);
          expect(tickRects.every((tick) => tick.finite)).toBe(true);
          expect(tickRects.every((tick, index) => index === 0 || tick.top >= tickRects[index - 1].bottom)).toBe(true);
        }
      }
      const previousActivity = page.getByRole("button", { name: "Ventana anterior", exact: true });
      const nextActivity = page.getByRole("button", { name: "Ventana siguiente", exact: true });
      await previousActivity.click();
      await nextActivity.click();

      await page.getByRole("button", { name: "Duración" }).click();
      const sleepRanges = page.getByRole("group", { name: "Seleccionar ventana de sueño" });
      await sleepRanges.getByRole("button", { name: "Seleccionar ventana de sueño Diario" }).click();
      for (const [rangeName, rangeValue] of [["7D", "7d"], ["180D", "180d"], ["Anual", "annual"]] as const) {
        const response = page.waitForResponse((candidate) => {
          const url = new URL(candidate.url());
          return url.pathname === "/api/v1/me/verify/sleep-trend" && url.searchParams.get("range") === rangeValue;
        });
        const button = sleepRanges.getByRole("button", { name: `Seleccionar ventana de sueño ${rangeName}` });
        await button.click();
        expect((await response).status()).toBe(200);
        await expect(button).toHaveAttribute("aria-pressed", "true");
        const sleepTicks = page.getByTestId("sleep-trend-duration-chart").locator(".sleep-duration-axis span");
        expect(await sleepTicks.count()).toBeGreaterThanOrEqual(4);
        expect(await sleepTicks.count()).toBeLessThanOrEqual(6);
        const tickRects = await sleepTicks.evaluateAll((ticks) => ticks.map((tick) => {
          const rect = tick.getBoundingClientRect();
          return { top: rect.top, bottom: rect.bottom, finite: [rect.top, rect.bottom, rect.left, rect.right].every(Number.isFinite) };
        }));
        expect(tickRects.every((tick) => tick.finite)).toBe(true);
        expect(tickRects.every((tick, index) => index === 0 || tick.top >= tickRects[index - 1].bottom)).toBe(true);
      }
      await expect(page.locator("body")).not.toContainText("NaN");
      await expect(page.locator("body")).not.toContainText("Infinity");
      expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
      expect(apiRequests.every((request) => request.startsWith("GET /api/v1/session") || request.startsWith("GET /api/v1/me/verify/"))).toBe(true);
      expect(devtoolRequests.every((request) => request === "GET /@vite/client")).toBe(true);
      expect(consoleErrors).toEqual([]);
      expect(failedRequests).toEqual([]);
      await context.close();
    });
  }
});
