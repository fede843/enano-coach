import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

describe("PWA and browser privacy boundary", () => {
  it("declares an installable shell without a private query", () => {
    const manifest = JSON.parse(readFileSync(resolve(appRoot, "public/manifest.webmanifest"), "utf8")) as Record<string, unknown>;
    expect(manifest.start_url).toBe("/verify");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(manifest.icons).toEqual([{ src: "/icons/mark.svg", sizes: "any", type: "image/svg+xml", purpose: "any maskable" }]);
  });

  it("caches only static shell assets and makes every API request network-only", () => {
    const worker = readFileSync(resolve(appRoot, "public/sw.js"), "utf8");
    expect(worker).toContain("enano-coach-shell-v3");
    expect(worker).toContain("/assets/app.js");
    expect(worker).toContain("/assets/index.css");
    expect(worker).toContain('url.pathname === "/api"');
    expect(worker).toContain('url.pathname.startsWith("/api/")');
    expect(worker).toContain("event.respondWith(fetch(request))");
    expect(worker).toContain('caches.match("/offline.html")');
    expect(worker).not.toMatch(/cache\.(?:put|add)\([^)]*\/api/);
  });

  it("keeps offline copy and safe-area layout markers", () => {
    const offline = readFileSync(resolve(appRoot, "public/offline.html"), "utf8");
    const styles = readFileSync(resolve(appRoot, "src/styles.css"), "utf8");
    expect(offline).toContain("Sin conexión");
    expect(styles).toContain("safe-area-inset-top");
    expect(styles).toContain("prefers-reduced-motion");
  });

  it("keeps browser source free from persistence APIs and absolute destinations", () => {
    const source = readFileSync(resolve(appRoot, "src/main.tsx"), "utf8");
    const api = readFileSync(resolve(appRoot, "src/api.ts"), "utf8");
    expect(`${source}\n${api}`).not.toMatch(/localStorage|sessionStorage|indexedDB|https?:\/\//i);
    expect(api).toContain('credentials: "same-origin"');
    expect(api).toContain('cache: "no-store"');
  });
});
