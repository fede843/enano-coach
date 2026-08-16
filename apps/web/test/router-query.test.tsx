import { renderToStaticMarkup } from "react-dom/server";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../src/App";
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
});
