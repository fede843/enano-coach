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

### Synthetic default

From the repository root, start the fixture-backed BFF in another terminal:

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

### Opt-in live local reads

The same UI can use the BFF's explicit local live-read mode without changing
browser code. Configure the BFF server with
`BFF_ENVIRONMENT` set to `development` or `test`,
`BFF_DEV_ACCESS_ENABLED=true`,
`BFF_LIVE_OW_ENABLED=true`, `BFF_SYNTHETIC_OWNER_KEY`,
`BFF_SYNTHETIC_OW_USER_KEY`, `OW_API_BASE_URL`, and either `OW_BEARER_TOKEN` or
the fallback `OW_API_KEY`. Values stay out of this repository and out of browser
requests.

The BFF accepts only loopback browser access in this mode. OW may be reached
directly at a loopback address or through an optional loopback tunnel to an
authorized instance; the tunnel remains server-side. The browser still calls
only relative `/api` paths, Vite still proxies only to the loopback BFF, and no
OW credential, owner/user reference, or internal URL enters frontend state.
The local defaults remain `http://localhost:5173` for Vite and
`http://localhost:8000` for the BFF; they are configurable development values,
not production endpoints.

## Checks

```bash
cd apps/web
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e -- e2e/verify.spec.ts
```

`npm run check` runs the first four checks. The focused Playwright command runs
the seven self-contained browser scenarios in `e2e/verify.spec.ts`; those
scenarios intercept BFF routes and do not require a running BFF or live sleep
data.

The two scenarios in `e2e/manual-validation.spec.ts` are a separate live browser
gate. They require the local Vite proxy and an already running, authorized BFF
whose selected test window contains a staged-sleep dataset with interval
chronology:

```bash
cd apps/web
npm run test:e2e -- e2e/manual-validation.spec.ts
```

Running bare `npm run test:e2e` selects all nine scenarios and therefore has the
same live staged-sleep prerequisite. The browser gate is local development
evidence only; it does not establish a reproducible OW release, production
authorization, or production readiness.

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

## Sleep Interaction Contract

- Aggregate sleep composition and exact interval chronology are separate. A
  valid aggregate-only response shows its summary/composition with no timeline;
  the UI never invents deep, light, REM, awake, or generic sleep chronology.
- The composition denominator includes awake as time in bed. Net sleep and its
  explicit unclassified remainder exclude awake, preventing double counting.
- A valid timeline may have a different specific-stage distribution from the
  aggregate composition. Malformed, overlapping, contradictory, or
  over-covering inputs fail closed instead of being clamped or rescaled.
- Sleep date/range controls remain mounted while loading. The result body is
  marked `aria-busy`, displays pending text, and hides stale chart data until
  the selected query resolves.
- Sleep and activity use independent query keys containing their date,
  timezone, range, and domain. Superseded sleep responses cannot replace a
  newer selection.
- Empty, partial, unsupported, and inconclusive states retain accessible copy
  and usable navigation rather than appearing as zero or a broken chart.

## Local Evidence

`[VERIFIED]` In a prior local validation, the BFF/adapter suite completed with
`688 passed, 213 subtests passed`; its live adapter used fake transport except
for a separately authorized read-only local smoke. The web unit suite completed
with `153 passed`. A fresh Playwright run completed all nine scenarios only while
an authorized live BFF supplied the staged-sleep dataset required by the two
manual viewport scenarios. The other seven scenarios were self-contained through
route interception. This historical result is not a guarantee that the current
synthetic BFF command can run the two live/manual scenarios.

The authorized local smoke was loopback-only and read-only. Any disposable
Docker service was local, retained no persistent health data after validation,
and does not establish deployment or production readiness. Real OIDC, an
immutable OW reference, production authorization, deployment, and release
evidence remain `[PENDING]`.

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

The Vite development client may request `/@vite/client`; that request is tooling,
not an application API call. It is intentionally outside the proxy allowlist, as
are all non-BFF API paths. The browser request regression checks both facts
without loosening the proxy boundary.
