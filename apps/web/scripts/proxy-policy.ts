const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

const REQUEST_HEADER_ALLOWLIST = new Set([
  "accept",
  "accept-language",
  "content-length",
  "content-type",
  "cookie",
  "idempotency-key",
  "origin",
  "referer",
  "user-agent",
  "x-csrf-token"
]);

const RESPONSE_HEADER_ALLOWLIST = new Set([
  "content-encoding",
  "content-length",
  "content-type",
  "cache-control",
  "location",
  "retry-after",
  "vary"
]);

const JSON_CONTENT_TYPE = "application/json; charset=utf-8";

const RUNS_PATH = "/api/v1/me/verify/runs";
const ACTIVITY_TREND_PATH = "/api/v1/me/verify/activity-trend";
const SLEEP_TREND_PATH = "/api/v1/me/verify/sleep-trend";
const RUN_DETAIL_PATH = /^\/api\/v1\/me\/verify\/runs\/verify-demo-[a-z0-9-]+$/;

function filterHeaders(
  headers: Record<string, string | string[] | undefined>,
  allowlist: Set<string>
): Record<string, string> {
  const filtered: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    const normalizedName = name.toLowerCase();
    if (!allowlist.has(normalizedName) || typeof value !== "string") {
      continue;
    }
    filtered[normalizedName] = value;
  }
  return filtered;
}

export function parseProxyTarget(value: string): URL {
  let target: URL;
  try {
    target = new URL(value);
  } catch {
    throw new Error("BFF_PROXY_TARGET must be a local HTTP target");
  }
  if (
    target.protocol !== "http:"
    || !LOOPBACK_HOSTS.has(target.hostname)
    || target.username
    || target.password
    || (target.pathname !== "/" && target.pathname !== "")
    || target.search
    || target.hash
  ) {
    throw new Error("BFF_PROXY_TARGET must be a local HTTP target");
  }
  if (target.port && (!/^\d+$/.test(target.port) || Number(target.port) < 1 || Number(target.port) > 65535)) {
    throw new Error("BFF_PROXY_TARGET must use a valid local port");
  }
  return target;
}

export function filterRequestHeaders(headers: Record<string, string | string[] | undefined>): Record<string, string> {
  return filterHeaders(headers, REQUEST_HEADER_ALLOWLIST);
}

export function filterResponseHeaders(headers: Record<string, string | string[] | undefined>): Record<string, string> {
  const filtered = filterHeaders(headers, RESPONSE_HEADER_ALLOWLIST);
  if (filtered["cache-control"]?.trim().toLowerCase() !== "no-store") {
    delete filtered["cache-control"];
  }
  if (filtered.location && (!filtered.location.startsWith("/") || filtered.location.startsWith("//"))) {
    delete filtered.location;
  }
  return filtered;
}

export function generatedProxyErrorHeaders(): Record<string, string> {
  return {
    "Content-Type": JSON_CONTENT_TYPE,
    "Cache-Control": "no-store"
  };
}

export function isAllowlistedApiRoute(method: string, pathname: string): boolean {
  if (method === "GET" && [
    "/api/v1/session",
    "/api/v1/me/verify/overview",
    ACTIVITY_TREND_PATH,
    SLEEP_TREND_PATH,
    "/api/v1/me/verify/sources",
    "/api/v1/me/verify/settings",
    RUNS_PATH
  ].includes(pathname)) {
    return true;
  }
  if ((method === "GET" || method === "POST") && pathname === RUNS_PATH) {
    return true;
  }
  return method === "GET" && RUN_DETAIL_PATH.test(pathname);
}
