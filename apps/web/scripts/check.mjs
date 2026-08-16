import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = resolve(new URL("..", import.meta.url).pathname);
const browserRoots = [join(appRoot, "src"), join(appRoot, "public")];

function filesUnder(directory) {
  const files = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      files.push(...filesUnder(path));
    } else {
      files.push(path);
    }
  }
  return files;
}

function textFiles(roots) {
  return roots.flatMap(filesUnder).filter((path) => /\.(ts|tsx|css|html|webmanifest|svg)$/.test(path));
}

function fail(message) {
  throw new Error(message);
}

function lint() {
  const browserText = [...textFiles(browserRoots), join(appRoot, "index.html")]
    .map((path) => ({ path, text: readFileSync(path, "utf8") }));
  for (const { path, text } of browserText) {
    if (/console\.(?:log|debug|info|warn|error)\s*\(/.test(text)) fail(`browser log found: ${path}`);
    if (/\beval\s*\(|new\s+Function\s*\(/.test(text)) fail(`dynamic code found: ${path}`);
    if (!path.endsWith(".svg") && /https?:\/\//i.test(text)) fail(`absolute URL found in browser artifact: ${path}`);
    if (/\b(?:localStorage|sessionStorage|indexedDB)\b|document\.cookie/i.test(text)) fail(`browser persistence found: ${path}`);
    if (/\b(?:user_id|ow_user_id|userId|owUserId|apiKey|OW_API_KEY|Authorization)\b/.test(text)) fail(`identity or credential field found in browser artifact: ${path}`);
  }
  const serviceWorker = readFileSync(join(appRoot, "public", "sw.js"), "utf8");
  if (/caches\.match\([^)]*\/api|cache\.put\([^)]*\/api/i.test(serviceWorker)) fail("service worker caches an API path");
  const apiSource = readFileSync(join(appRoot, "src", "api.ts"), "utf8");
  if (!apiSource.includes('credentials: "same-origin"') || !apiSource.includes('cache: "no-store"')) fail("API client lacks same-origin/no-store boundary");
  if (!apiSource.includes("queryUrl(API_ROUTES.overview") || !apiSource.includes("queryUrl(API_ROUTES.runs")) fail("API client route allowlist is incomplete");
  if (!apiSource.includes("/api/v1/session") || !apiSource.includes("/api/v1/me/verify/runs")) fail("API client route allowlist is incomplete");
  console.log("Lint passed: browser boundary and static safety checks are clean.");
}

if (process.argv[2] === "lint") {
  lint();
} else {
  fail("usage: node scripts/check.mjs lint");
}
