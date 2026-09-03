import { describe, expect, it } from "vitest";

import { filterRequestHeaders, filterResponseHeaders, generatedProxyErrorHeaders, isAllowlistedApiRoute, parseProxyTarget } from "../scripts/proxy-policy";

describe("development proxy boundary", () => {
  it("accepts only local loopback HTTP targets", () => {
    expect(parseProxyTarget("http://127.0.0.1:8000").hostname).toBe("127.0.0.1");
    expect(parseProxyTarget("http://localhost:8000").port).toBe("8000");
    expect(() => parseProxyTarget("https://127.0.0.1:8000")).toThrow();
    expect(() => parseProxyTarget("http://192.0.2.10:8000")).toThrow();
    expect(() => parseProxyTarget("http://user:pass@127.0.0.1:8000")).toThrow();
  });

  it("preserves no-store on successful BFF responses and forwards only allowlisted headers", () => {
    expect(filterRequestHeaders({ accept: "application/json", cookie: "session=synthetic", authorization: "not-forwarded", "x-open-wearables-api-key": "not-forwarded", "idempotency-key": "verify-demo-key", "x-forwarded-for": "not-forwarded" })).toEqual({ accept: "application/json", cookie: "session=synthetic", "idempotency-key": "verify-demo-key" });
    expect(filterResponseHeaders({ "content-type": "application/json", "retry-after": "5", "set-cookie": "not-forwarded", "cache-control": "no-store", authorization: "not-forwarded", "x-request-id": "not-forwarded", location: "http://internal.example.test/private" })).toEqual({ "content-type": "application/json", "cache-control": "no-store", "retry-after": "5" });
    expect(filterResponseHeaders({ "cache-control": "private, max-age=60" })).toEqual({});
  });

  it("marks generated 404 and unavailable-target responses as no-store", () => {
    expect(generatedProxyErrorHeaders()).toEqual({
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    });
  });

  it("restricts the development proxy to the fixed BFF routes", () => {
    expect(isAllowlistedApiRoute("GET", "/api/v1/session")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/overview")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/activity-trend")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/sleep-trend")).toBe(true);
    expect(isAllowlistedApiRoute("POST", "/api/v1/me/verify/sleep-trend")).toBe(false);
    expect(isAllowlistedApiRoute("POST", "/api/v1/me/verify/activity-trend")).toBe(false);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/sources")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/settings")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/runs")).toBe(true);
    expect(isAllowlistedApiRoute("POST", "/api/v1/me/verify/runs")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/me/verify/runs/verify-demo-01")).toBe(true);
    expect(isAllowlistedApiRoute("GET", "/api/v1/users/not-browser-data")).toBe(false);
  });

  it("does not classify Vite development tooling as an app API route", () => {
    expect(isAllowlistedApiRoute("GET", "/@vite/client")).toBe(false);
  });
});
