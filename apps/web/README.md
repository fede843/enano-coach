# Enano Coach Web

React/Vite/TypeScript PWA shell for the Wave 3 verification console. The browser
uses only the versioned BFF routes under relative `/api` paths. It never calls
Open Wearables directly and has no health-data storage layer.

## Toolchain

The fixed frontend stack is React, Vite, and TypeScript. The package installs
only React, ReactDOM, Vite, TypeScript, React/Node type declarations, and
Vitest. The lockfile is maintained with the package manifest; no CDN imports or
runtime dependency download is used by the browser.

## Local Run

Node.js 20 or newer is required for the Vite development server, build, checks,
and tests.

From the repository root, start the synthetic BFF in another terminal:

```bash
BFF_ENVIRONMENT=test PYTHONPATH=apps/bff/src python -m uvicorn bff.main:app --port 8000
```

Then start the web shell:

```bash
cd apps/web
npm run dev
```

Open `http://localhost:5173/verify`. Vite serves the React shell and forwards
only the seven fixed BFF routes. The proxy target is server-only and can be
changed with `BFF_PROXY_TARGET` only to an HTTP loopback target (`localhost`,
`127.0.0.1`, or `::1`). Request and response headers are allowlisted;
credentials intended for other services, `Set-Cookie`, Authorization,
OW/internal headers, and arbitrary cache directives are not proxied. The safe
`Cache-Control: no-store` response directive is preserved for private
responses, and generated development-proxy `404`/unavailable-target `502`
responses are also marked `no-store`. Real cookie authentication and the
production proxy policy remain
`[PENDING]` and outside this slice.

## Checks

```bash
cd apps/web
npm run typecheck
npm run lint
npm test
npm run build
```

`npm run check` runs all four checks. They are install-free and offline.

## Contract Boundary

- UI routes are `/verify`, `/verify/sources`, `/verify/runs`,
  `/verify/runs/:runKey`, and `/verify/settings`.
- BFF routes are the seven endpoints in `BFF_UI_CONTRACT.md`; the client has a
  route allowlist and rejects unknown response fields before rendering.
- Dates and timezones remain in ephemeral React controller state. Cursors are kept in
  memory and forwarded opaquely only to the BFF.
- `VerificationRun` creation is the only UI mutation. It creates BFF control
  state and is never described as an Open Wearables import or health-fact write.
- Source keys and run keys are treated as opaque BFF values. OW identifiers,
  credentials, tokens, paths, provider payloads, and raw error content are not
  displayed or stored.
- `[PENDING]` `settings.versions.owReference` is currently normalized to the
  synthetic `not_pinned` value. A future pinned reference requires an explicit
  BFF-UI contract, parser, and rendering update; arbitrary URLs, paths, and
  credential-like text are not accepted as display values.

## PWA Boundary

The service worker precaches only the application shell, static CSS/JavaScript,
manifest, icon, and generic offline page. Requests beginning with `/api/` are
always sent to the network and are never put in a cache. Offline navigation
falls back to a generic screen without private data.

The shell is synthetic-fixture compatible only through the BFF. The OW pin,
production authentication/session policy, durable control-plane storage, and
real upstream integration remain pending outside this wave. Maps, GPS, routes,
rich workout details, imports, edits, deletes, automatic upstream retries,
coaching, and open-ended comparisons are intentionally absent.
