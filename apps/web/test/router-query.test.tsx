import { renderToStaticMarkup } from "react-dom/server";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App, { refetchOverviewQueries } from "../src/App";
import { createAppQueryClient, queryKeys } from "../src/queries";

describe("React Router and TanStack Query boundary", () => {
  it("owns all five UI routes, including a direct detail deep link", () => {
    const entries = [
      "/verify",
      "/verify/sources",
      "/verify/runs",
      "/verify/runs/verify-demo-01",
      "/verify/settings"
    ];

    for (const entry of entries) {
      const queryClient = createAppQueryClient();
      const markup = renderToStaticMarkup(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[entry]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      );
      expect(markup).toContain("<main");
      expect(markup).toContain("Abriendo sesión");
    }
  });

  it("uses primitive non-payload query keys and an ephemeral non-persistent client", () => {
    const runsKey = queryKeys.runs("2024-01-01", "2024-01-02", "pending", "UTC");
    expect(runsKey).toEqual(["verification-runs", "2024-01-01", "2024-01-02", "pending", "UTC", 2]);
    expect(runsKey.every((part) => ["string", "number"].includes(typeof part))).toBe(true);

    const queryClient = createAppQueryClient();
    expect(queryClient.getDefaultOptions().queries?.gcTime).toBe(0);
    expect(queryClient.getDefaultOptions().queries?.retry).toBe(false);
    expect(queryClient.getDefaultOptions().mutations?.retry).toBe(false);
  });

  it("refetches overview, activity, and sleep trends for an overview retry", () => {
    const queries = {
      overview: vi.fn().mockResolvedValue(undefined),
      activity: vi.fn().mockResolvedValue(undefined),
      sleep: vi.fn().mockResolvedValue(undefined)
    };

    refetchOverviewQueries(queries);

    expect(queries.overview).toHaveBeenCalledTimes(1);
    expect(queries.activity).toHaveBeenCalledTimes(1);
    expect(queries.sleep).toHaveBeenCalledTimes(1);
  });

  it("uses the independent sleep range and date in the sleep query key", async () => {
    const { queryKeys } = await import("../src/queries");
    expect(queryKeys.sleepTrend("2024-01-02", "UTC", "daily")).not.toEqual(
      queryKeys.sleepTrend("2024-01-02", "UTC", "7d")
    );
    expect(queryKeys.sleepTrend("2024-01-02", "UTC", "7d")).not.toEqual(
      queryKeys.sleepTrend("2024-01-03", "UTC", "7d")
    );
    expect(queryKeys.activityTrend("2024-01-02", "UTC", "7d")).not.toEqual(
      queryKeys.sleepTrend("2024-01-02", "UTC", "daily")
    );
  });

  it("keeps each trend request tied to its current query key", async () => {
    const activity = await import("../src/api");
    const sleep = await import("../src/api");
    const activitySpy = vi.spyOn(activity, "getActivityTrend").mockResolvedValue({} as never);
    const sleepSpy = vi.spyOn(sleep, "getSleepTrend").mockResolvedValue({} as never);
    const queryClient = createAppQueryClient();
    const activityKey = queryKeys.activityTrend("2024-01-03", "UTC", "daily");
    const sleepKey = queryKeys.sleepTrend("2024-01-04", "UTC", "7d");

    await queryClient.fetchQuery({ queryKey: activityKey, queryFn: ({ queryKey }) => activity.getActivityTrend({ date: queryKey[1], timezone: queryKey[2], range: queryKey[3] }) });
    await queryClient.fetchQuery({ queryKey: sleepKey, queryFn: ({ queryKey }) => sleep.getSleepTrend({ date: queryKey[1], timezone: queryKey[2], range: queryKey[3] }) });

    expect(activitySpy).toHaveBeenCalledWith({ date: "2024-01-03", timezone: "UTC", range: "daily" });
    expect(sleepSpy).toHaveBeenCalledWith({ date: "2024-01-04", timezone: "UTC", range: "7d" });
  });

});
