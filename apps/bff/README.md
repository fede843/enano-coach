# Enano Coach BFF

This is a local, offline FastAPI BFF for the first verification slice.

- It reads only the approved `OfflineFixtureAdapter`.
- Its `VerificationRun` records are in-memory control-plane aggregates.
- Its synthetic session mode is selected by server configuration, not by a browser request.
- Every browser-facing `/api` success and error response is marked
  `Cache-Control: no-store`; health responses and verification records are not cached.
- It does not call Open Wearables, use SQL, persist data, or make outbound requests.
- The BFF owns explicit, route-specific response models and projections. Adapter
  envelopes are never returned directly to the browser.
- Synthetic session modes are local development fixtures, not production
  authentication. They do not implement OIDC, real cookie sessions, ownership
  storage, or rate limiting. Origin checking is only a local mutation guard and
  must not be described as CSRF completion.
- The active synthetic session is permitted only when server configuration
  explicitly uses `BFF_ENVIRONMENT=local`, `development`, or `test`; a missing
  environment never defaults to local and fails active application creation.
  Module import falls back to an anonymous, non-active local process only so an
  unconfigured development import cannot enable protected access. This guard
  does not implement OIDC or cookie authentication.
- POST request bodies are bounded by a receive wrapper before JSON accumulation;
  the focused unit test exercises chunked ASGI receives because `TestClient`
  normally presents a complete body in one transport message.
- Unsupported trailing-slash paths return a JSON `404` envelope without a
  redirect. `HEAD` is not part of the seven-route contract and returns a JSON
  `405` envelope rather than an empty `RUN_NOT_FOUND` response.
- Verification runs are in-memory and disappear when the process stops.
- JSON object keys, scalar query names, `Origin`, and `Idempotency-Key` inputs are
  rejected when duplicated; the BFF never selects a last value for them.
- Raw ASGI `Content-Length` and `Content-Type` duplicates, including comma-joined
  values and mixed casing, are rejected before body reads or route logic. A single
  `Content-Length` must contain only ASCII decimal digits. This is an application
  boundary check only: `[PENDING]` a production server or proxy must also reject
  ambiguous headers before normalizing them away.
- The package ranges in `pyproject.toml` are intentional development bounds;
  this repository has no Python package lockfile. A pinned, reviewed lock is
  `[PENDING]` before deployment or real OW integration.

## Boundary Decisions

- `[FIXED]` The daily overview request window is derived from the validated route
  `date` and `timezone`. The synthetic adapter's fixed `coverage.requested`
  envelope is server-side fixture evidence: its shape, ordering, and values are
  validated, but it is not forwarded when it contradicts the route. The public
  envelope uses the BFF-derived logical date, IANA timezone, and UTC window.
  An omitted or malformed adapter request envelope is still `502
  UPSTREAM_INVALID`.
- `[FIXED]` This timezone projection changes BFF request metadata only. It does
  not rebucket or reinterpret synthetic metric values, does not claim that the
  fixture was queried at the requested timezone, and does not perform a real OW
  query.
- `[FIXED]` Daily overview coverage requires `expectedDays: 1`,
  `availableDays: 0..1`, and coherent empty/partial/complete semantics. Metric
  coverage on this daily route uses the same `expectedDays: 1` and
  `availableDays: 0..1` bounds, plus a finite fraction in `0..1` and
  state-compatible values. The BFF intentionally derives the public request
  envelope from the validated route date/timezone; it validates, but does not
  copy, an adapter-provided requested envelope. Metric, domain, date-identity,
  and coverage semantics remain strict and fail closed.
- `[FIXED]` `recoveryScore` is the only numeric overview metric allowed to carry
  a value with `unit: null`; its value is an integer from `0` to `100`. Other
  numeric value states retain their declared units, while null and unsupported
  states retain null values and units.
- `[FIXED]` Verification-run records are validated by state before they cross
  the browser boundary. Pending records have no finished timestamp or terminal
  findings; terminal states require ordered `requestedAt <= startedAt <=
  finishedAt` timestamps. Persisted runs contain only matches (or no results),
  partial runs preserve `PARTIAL_COVERAGE`, not-verifiable runs preserve their
  result/warning pair, inconclusive runs preserve their result/warning pair,
  and closed findings contain an unequal, unit-coherent mismatch with matching
  daily-total flags. A create serializes its candidate before committing the
  record or idempotency mapping; seed validation stages every candidate before
  installing any record. Seed installation and post-insertion create
  finalization restore records, idempotency mappings, cursors, and run-number
  state on failure.
- `[RISK]` These checks cover the synthetic adapter and in-memory store only.
  They do not prove a real OW response, durable persistence, production
  concurrency behavior, or a reproducible dependency installation.
- `[PENDING]` The synthetic catalog exposes `failed` only on the second list
  page and does not provide dedicated `cancelled` or `skipped` detail cases;
  the BFF preserves those states when records exist without inventing detail.
- `[PENDING]` The supplied `not_verifiable` and `inconclusive` fixtures include
  result/warning evidence. The serializer enforces that pairing but does not
  infer nullable timestamps or counts that the contract permits to remain null.
- `[PENDING]` Real OIDC, cookie sessions, ownership storage, CSRF tokens, rate
  limiting, a dependency lock, and an immutable OW reference remain outside
  this local correction.

Run the local checks from the repository root with an explicit synthetic
environment:

```bash
BFF_ENVIRONMENT=test PYTHONPATH=apps/bff/src pytest -q apps/bff/src/bff apps/bff/src/adapter
```

The first slice remains synthetic and offline. Real OIDC, cookie-session
authentication, CSRF, OW credentials, persistent control-plane storage,
production rate limiting, and deployment are outside this local limitation
boundary. Local verification covers the currently installed
FastAPI/Pydantic/Pytest/httpx environment only; dependency ranges are not a
reproducible installation lock. Adding a reviewed Python lock or equivalent
install artifact remains `[PENDING]`.

## Wave 2 Handoff

### 1. Identification

- Coordinating agent: Wave 2 BFF correction owner, build mode
- Subagents and roles: none spawned; the user explicitly prohibited spawning another agent
- Session date: 2026-08-16
- Wave: 2 BFF
- Task: correct cursor validation ordering before adapter seeding
- Overall status: PENDING independent review; implementation and local verification completed
- Approved scope: `apps/bff/src/bff/**`, `apps/bff/pyproject.toml`, and this README
- Uncompleted scope: adapter, fixtures, contracts, plan, UI, shared tests, real OW, real OIDC, and deployment
- Explicit user instruction required: yes: do not spawn another agent; preserve unrelated worktree changes

### 2. Executive Summary

The BFF now projects every successful route through explicit Pydantic models and
route-specific allowlists. Adapter envelopes, unknown nested keys, OW IDs,
metadata, raw errors, URLs, paths, credentials, rich workout fields, and
aggregate heart-rate children are not returned to the browser. Tainted semantic
values, negative scalar heart rate, non-finite numbers, arbitrary source labels,
provider narratives, and unknown route data fail closed as generic `502
UPSTREAM_INVALID` responses. Every `/api` response is centrally marked
`Cache-Control: no-store`, including handled and unhandled error paths.
Run pages and seeded in-memory records are validated through the same allowlist
before storage, and adapter error envelopes are checked before their codes are
mapped. Pending records are checked again at serialization, warning codes are
complete and code-specific declared domains are validated without inventing
domains omitted by the current run fixtures. Adapter coverage metadata is
validated, while the public overview request context is replaced with the
route-derived window. Seed and commit mutations are transactional.
Empty supplied query values, non-JSON POST bodies, oversized POST bodies, unsafe
synthetic origins, and unlisted or wrong-method routes are handled explicitly.
The server refuses the active synthetic session outside an explicitly configured
local development environment, including when `BFF_ENVIRONMENT` is missing;
client headers, query parameters, and bodies do not select a session mode or OW
user. Duplicate security-sensitive inputs are rejected rather than canonicalized
by last-value-wins. Request-ID generation is non-exhausting with a safe fallback.

The result is verified only against the local synthetic adapter. Synthetic
session state is not authentication; real OIDC, cookie sessions, and ownership
remain `[PENDING]`. The Origin check is only a local mutation guard, not
complete CSRF; rate limiting is not implemented; and verification runs remain
in-memory and non-durable. Real OW integration and a dependency lock remain
`[PENDING]`.

### 2.1 Findings Fixed

- `[FIXED]` All seven browser routes use BFF-owned models and explicit projections; seeded run records are validated before entering the store and again when serialized.
- `[FIXED]` Unknown nested keys, internal identifiers, raw metadata/messages/errors, URLs, paths, credentials, payloads, rich workout fields, and aggregate heart-rate children fail closed as `502 UPSTREAM_INVALID`.
- `[FIXED]` Source labels and warning/error copy are derived from exact synthetic allowlists; provider-controlled narrative is never forwarded.
- `[FIXED]` Metric state, unit, zero/null semantics, finite-number checks, coverage bounds, cursor shape, source-ambiguity warning completeness, and the body-relative warning are enforced at the BFF boundary.
- `[FIXED]` Scalar fixture-only heart rate rejects negative and non-finite numbers while preserving null, unsupported, ambiguous, and scalar-shape semantics.
- `[FIXED]` A centralized middleware marks every `/api` success and error response `Cache-Control: no-store`, including `404`, `405`, and `500` responses.
- `[FIXED]` Active synthetic sessions require an explicit `BFF_ENVIRONMENT=local|development|test`; missing or other environments cannot enable active access. This remains a configuration guard, not real authentication.
- `[FIXED]` The POST body is bounded at the ASGI receive layer before downstream JSON accumulation; a focused chunked-receive test documents the `TestClient` limitation.
- `[FIXED]` Duplicate JSON keys, scalar query names, `Origin`, and `Idempotency-Key` headers fail safely before a last value can be selected.
- `[FIXED]` Daily overview coverage validates the adapter's applicable requested
  envelope, then replaces only its public request context with the route-derived
  UTC window; omissions and malformed metric/domain/coverage content remain
  `UPSTREAM_INVALID`.
- `[FIXED]` Seed installation and commit finalization restore all prior in-memory state after forced failures, including cursors, idempotency mappings, and run numbering.
- `[FIXED]` Request IDs use a non-exhausting synthetic counter and return a safe fallback envelope when the counter fails.
- `[FIXED]` Run-list cursor format, session/context binding, expiration, filters, limit, ordering, schema, and timezone are checked before store seeding, dependency-case checks, or adapter responses; malformed, expired, and context-mismatched cursors do not call the adapter.
- `[FIXED]` Trailing slashes, `HEAD`, unlisted routes, and wrong methods return deliberate JSON `404`/`405` envelopes without `RUN_NOT_FOUND` remapping.

### 3. Files and Ownership

Files changed in the current cursor-order correction: `apps/bff/src/bff/service.py`,
`apps/bff/src/bff/store.py`, `apps/bff/src/bff/test_app.py`, and
`apps/bff/README.md`. The broader Wave 2 BFF implementation files remain listed
below for ownership and evidence context.

| Action | Relative path | Owner | Reason | Status |
|---|---|---|---|---|
| modified | `apps/bff/src/bff/config.py` | Wave 2 BFF owner | Local-only synthetic-origin and environment guard | DONE |
| modified | `apps/bff/src/bff/main.py` | Wave 2 BFF owner | Request validation and error routing | DONE |
| modified | `apps/bff/src/bff/serializers.py` | Wave 2 BFF owner | BFF-owned projections and allowlists | DONE |
| modified | `apps/bff/src/bff/store.py` | Wave 2 BFF owner | Transactional seed and create finalization | DONE |
| modified | `apps/bff/src/bff/test_app.py` | Wave 2 BFF owner | Taint, transport, query, and error regressions | DONE |
| modified | `apps/bff/README.md` | Wave 2 BFF owner | Local limitations and this handoff | DONE |
| reviewed | `apps/bff/src/bff/errors.py` | Wave 2 BFF owner | Existing safe error catalog | DONE |
| reviewed | `apps/bff/src/bff/models.py` | Wave 2 BFF owner | Existing strict route models | DONE |
| modified | `apps/bff/src/bff/service.py` | Wave 2 BFF owner | Cursor validation ordering before store seeding and adapter access | DONE |
| reviewed | `apps/bff/pyproject.toml` | Wave 2 BFF owner | Existing dependency ranges and test configuration | DONE |

The adapter, fixtures, contracts, plans, skills, lockfile, UI, and shared tests
were not edited.

Files deliberately not touched:

- `apps/bff/src/adapter/**`: existing adapter and adapter tests preserved.
- `docs/fixtures/**`: existing unrelated worktree changes preserved.
- Contracts, plan, prompt, handoff/checklist, skills, lockfile, UI, and shared tests: outside the approved scope.
- `AGENTS.md`: read and not touched.

`skills-lock.json` and all seven custom `enano-coach-*` skills were read. The
requested external skills were loaded without modifying the lock or skill files.

Ownership conflicts: none observed. The worktree already contained unrelated
untracked `apps/` and `.agents/` content and a modified synthetic fixture; none
was reverted or changed outside the approved scope.

### 4. Wave Status

| Wave or role | Role | Handoff received | Assigned files | Result |
|---|---|---|---|---|
| Wave 0 evidence | Prior independent findings | YES | Finding descriptions and project contracts | DONE |
| Wave 2 build | BFF correction owner | YES | Owned BFF files listed above | DONE |
| Independent reviewer | Diff and evidence review | NO | None; spawning prohibited in build mode | PENDING |
| Privacy reviewer | Separate handoff | NO | None; local scoped scan executed by owner | PENDING |
| Final validator | Separate closure handoff | NO | None; local final commands executed by owner | PENDING |

### 5. Decisions

| ID | Marker | Decision | Reason | Evidence | Impact |
|---|---|---|---|---|---|
| D-21 | [FIXED] | The BFF is the browser boundary and owns explicit route serializers. | Adapter shape is not a browser contract. | `src/bff/models.py`, `src/bff/serializers.py`, taint tests | All seven routes |
| D-22 | [FIXED] | Strict models use `extra="forbid"`; projection functions copy only allowlisted fields. | Prevent nested unknown-field pass-through. | `src/bff/models.py`, `src/bff/serializers.py` | Successful and error responses |
| D-23 | [FIXED] | `data.summary.heartRate` remains the scalar fixture shape with `state`, `value`, `unit`, and `isDailyTotal` only. | Preserve accepted synthetic semantics; do not describe it as average/min/max. | `HeartRateMetric`, taint test | Overview |
| D-24 | [FIXED] | Explicit empty query values are invalid; only absent optional source values receive local defaults. | Distinguish omission from `?date=` and `?timezone=`. | `_reject_query_params`, empty-query tests | Sources and runs |
| D-25 | [FIXED] | POST requires `application/json` with optional parameters, a 16 KiB receive-enforced body limit, and bounded domains. | Reject unsafe media types and oversized input before model parsing. | `main.py`, content-type/chunked-body tests | Verification-run creation |
| D-26 | [FIXED] | Synthetic session modes are local-only server configuration. | They are not production authentication. | `config.py`, origin tests, README | Local development only |
| D-27 | [FIXED] | Unknown routes and methods map to generic `NOT_FOUND`/`METHOD_NOT_ALLOWED`; unexpected exceptions map to generic `INTERNAL_ERROR`. | Avoid `RUN_NOT_FOUND` confusion and exception leakage. | `main.py`, route/error tests | HTTP errors |
| D-28 | [FIXED] | Trailing slashes do not redirect, and `HEAD` is rejected with a JSON `405` envelope. | Preserve one explicit JSON boundary for unlisted route forms. | `main.py`, route-variant tests | HTTP transport |
| D-29 | [FIXED] | BFF serializers and store seeding fail closed on unknown fields, tainted semantics, non-finite numbers, and non-allowlisted free text. | Adapter validation is independent and may not be the browser boundary. | `serializers.py`, `store.py`, taint/semantic tests | All successful routes |
| D-30 | [VERIFIED] | Offline BFF and adapter checks pass with current evidence. | Fresh commands completed in this session. | Test and validation results below | Synthetic scope only |
| D-31 | [FIXED] | Scalar fixture-only heart rate accepts only finite, non-negative numeric values at the BFF boundary; null and non-value states retain their semantics. | Negative values are invalid bpm; the fixture remains scalar and does not gain aggregate children. | `serializers.py`, negative-HR regression | Overview |
| D-32 | [FIXED] | All browser-facing `/api` responses carry `Cache-Control: no-store`. | Health and verification responses must not be retained by browser caches; middleware covers route and error paths. | `main.py`, no-store header regression | All `/api` responses |
| D-33 | [FIXED] | Active synthetic sessions require an explicitly local development environment selected by server configuration. | Synthetic mode is a fixture guard, not OIDC or cookie authentication; missing configuration cannot enable active access. | `config.py`, environment regression | App startup |
| D-34 | [FIXED] | Warning codes required by partial, ambiguous, and relative-to-now states must be present and domain-correct at the BFF serializer boundary. `UNSUPPORTED` remains allowlisted but optional when the metric state is already `unsupported`; run warnings retain fixture-omitted domains and validate only declared code-specific domains. | A present warning is not enough when it is stale, incomplete, or scoped to another domain. | `serializers.py`, warning-removal/domain regressions | Overview and run detail |
| D-35 | [FIXED] | Adapter-requested daily coverage must be valid and ordered, while the public overview request context is derived from the validated route date/timezone; applicable omission or tainted metric/domain coverage is invalid. | The synthetic adapter response is fixed UTC fixture evidence, not a real timezone-specific OW query. | `serializers.py`, timezone/DST and coverage regressions | Overview |
| D-36 | [FIXED] | Seed and create commits restore all prior in-memory state when installation or finalization fails. | No ghost records, mappings, cursors, or consumed run numbers may remain after a failed operation. | `store.py`, forced-failure regressions | Control-plane store |
| D-37 | [FIXED] | Duplicate JSON keys, scalar query parameters, and security-sensitive headers are rejected; request IDs use a non-exhausting counter with a safe fallback. | Security-sensitive input must not use last-value-wins, and error envelopes remain JSON/no-store when correlation generation fails. | `main.py`, duplicate/request-ID regressions | HTTP boundary |

Unresolved decisions:

- `[PENDING]` Pin the OW release/commit/digest and verify real authorized schemas.
- `[PENDING]` Implement real OIDC, server-side cookie sessions, ownership, CSRF tokens, and rate limiting.
- `[PENDING]` Add a reviewed Python dependency lock or equivalent reproducible installation process.
- `[PENDING]` Obtain the required independent diff, privacy, and final-validation handoffs.

### 6. Test Evidence

| Area | Command or test | Result | Date | Public evidence | Limitation |
|---|---|---|---|---|---|
| Unit/contract/integration | `BFF_ENVIRONMENT=test PYTHONPATH=apps/bff/src pytest -q apps/bff/src/bff apps/bff/src/adapter` | PASS: 332 passed, 213 subtests passed; one existing Starlette/httpx deprecation warning | 2026-08-16 | BFF and adapter suites | Synthetic/offline only |
| Targeted duplicate-header/security regressions | `BFF_ENVIRONMENT=test PYTHONPATH=apps/bff/src pytest -q apps/bff/src/bff/test_app.py -k 'ambiguous_framing or duplicate_content_header or duplicate_json_body_keys or duplicate_scalar_query_parameters or duplicate_security_headers or missing_environment or request_id_counter'` | PASS: 14 passed, 247 deselected; one existing Starlette/httpx deprecation warning | 2026-08-16 | `src/bff/test_app.py` | Synthetic header, duplicate-input, environment-guard, and request-ID cases only |
| Ruff | `ruff check apps/bff/src/bff apps/bff/src/adapter` | PASS | 2026-08-16 | BFF and adapter source trees | No external lint service |
| Black | `black --check apps/bff/src/bff apps/bff/src/adapter` | PASS: 13 files unchanged | 2026-08-16 | BFF and adapter source trees | Formatter check only |
| Compile | `python -m compileall -q apps/bff/src` | PASS | 2026-08-16 | Owned source tree | Does not execute deployment |
| JSON | Python `json.loads` over both public fixtures | PASS | 2026-08-16 | `docs/fixtures/*.json` | Fixtures were not edited by this task |
| TOML/Markdown | Python TOML parse, README fence, and relative-link checks | PASS | 2026-08-16 | `apps/bff/pyproject.toml`, `apps/bff/README.md` | No site renderer run |
| Whitespace | `git diff --check` and untracked-text whitespace scan | PASS | 2026-08-16 | Worktree inspection | Existing unrelated changes retained |
| Security AST | Offline AST scan for network/SQL imports and dynamic/command calls over BFF and adapter Python | PASS: no findings | 2026-08-16 | `apps/bff/src/bff/*.py`, `apps/bff/src/adapter/*.py` | Pattern scan, not a full SAST product |
| Privacy/secrets | Scoped literal scan for credentials, private IPs, UUID/MAC/email-shaped values, and path-like strings | PASS: no credential-shaped, private-IP, UUID, MAC, or email-shaped values; two path-like synthetic taint inputs | 2026-08-16 | Owned BFF files and README | Taint inputs remain test-only and are not returned |
| UI/Playwright | Not run | NOT RUN: UI files and UI tests are outside scope | 2026-08-16 | N/A | UI behavior remains a separate wave |
| Accessibility/responsive | Not run | NOT RUN: UI files are outside scope | 2026-08-16 | N/A | Requires independent UI validation |
| Real OW/OIDC/deployment | Not run | NOT RUN: prohibited for this offline slice | 2026-08-16 | N/A | Production compatibility remains pending |

The suite was run again after the final source and test changes. No Docker,
Ansible, network access, real OW, SQL, migration, or deployment command was run.

### 7. Contract Claims

| Claim | Marker | Source | Evidence | Scope | Limit or warning |
|---|---|---|---|---|---|
| The seven documented BFF routes remain present and no UI shorthand route was added. | [VERIFIED] | `src/bff/main.py` and route test | 318-test run | Local FastAPI app | Not a production deployment contract |
| Successful route output is BFF-owned and rejects unknown model fields, semantic taints, negative scalar heart rate, non-finite numbers, and arbitrary free text. | [VERIFIED] | `src/bff/models.py`, `src/bff/serializers.py` | Tainted/semantic/finite/negative-HR route tests | Overview, sources, settings, runs, session | Uses synthetic adapter evidence |
| `user_id`, OW IDs, adapter mappings, raw metadata/errors, URLs, paths, credentials, and unknown nested fields do not cross the tested HTTP boundary. | [VERIFIED] | `src/bff/serializers.py`, taint tests | Tainted success/error smoke | Tested injected values only | Real OW output remains pending |
| Body data is not added to the overview and no workout collection is exposed by these serializers. | [FIXED] | BFF-UI and OW contracts; route serializers | Route models have no body/workout collection | First slice | Future contract may add explicit aggregate fields later |
| The POST creates only an in-memory BFF-owned verification record and returns pending. | [FIXED] | `src/bff/store.py`, `src/bff/service.py` | Existing idempotency tests | Local process | Not durable persistence and not OW mutation |
| Synthetic auth modes provide local test state only. | [FIXED] | `src/bff/config.py`, README | Server-selected mode and origin tests | Local process | No OIDC, secure production cookie, or complete CSRF |
| Browser-facing `/api` responses are not cached. | [VERIFIED] | `src/bff/main.py`, `src/bff/test_app.py` | Success, POST, auth, validation, `404`, `405`, and `500` header smoke | Local FastAPI app | Does not replace deployment/proxy cache policy |
| Active synthetic sessions refuse non-local server environments. | [VERIFIED] | `src/bff/config.py`, `src/bff/test_app.py` | Local allowed and non-local refused tests | App construction | Does not implement OIDC, cookie auth, ownership, CSRF, or rate limiting |
| Boundary serializers require state-driven warnings, validate declared warning domains, preserve omitted run domains, and project the public overview window from the route. | [VERIFIED] | `src/bff/serializers.py`, `src/bff/test_app.py` | Warning, taint, timezone/DST, and coverage regressions | Overview and run data | Synthetic adapter only; no real OW query |
| Seed and create state is restored after forced insertion/finalization failures. | [VERIFIED] | `src/bff/store.py`, `src/bff/test_app.py` | Fail-once atomicity regressions | In-memory store | No durable transaction or concurrency claim |
| Duplicate security-sensitive inputs and request-counter failures remain safe JSON/no-store errors. | [VERIFIED] | `src/bff/main.py`, `src/bff/test_app.py` | Duplicate and request-ID regressions | HTTP boundary | Synthetic transport only |
| Invalid, expired, and context-mismatched run cursors are rejected before adapter seeding. | [VERIFIED] | `src/bff/service.py`, `src/bff/store.py`, `src/bff/test_app.py` | Six cursor-order regressions, including a failing adapter spy | `GET /api/v1/me/verify/runs` | In-memory synthetic cursor state; real OW pagination remains pending |
| OW read fields and route names are production-compatible. | [PENDING] | `docs/contracts/OW_READ_CONTRACT.md` | Synthetic adapter only | None | Requires reproducible OW pin and authorized tests |

### 8. Capability Matrix

| Capability | Class | Public source | Route/schema | Exposed by BFF | UI presentation | Risk/pending |
|---|---|---|---|---|---|---|
| Synthetic session envelope | `public_api` | BFF-UI contract and local route tests | `GET /api/v1/session` | YES | Session/access state | `[PENDING]` replace with real OIDC/session implementation |
| Daily overview scalar metrics | `public_api` | BFF-UI contract and synthetic fixture | `GET /api/v1/me/verify/overview` | YES | Value, zero, null, partial, unsupported, ambiguous | OW pin and real authorization pending |
| Sanitized source inventory | `public_api` | BFF-UI contract and synthetic fixture | `GET /api/v1/me/verify/sources` | YES | Ready or source ambiguous | Source provenance against real OW pending |
| BFF settings metadata | `public_api` | BFF-UI contract | `GET /api/v1/me/verify/settings` | YES | Placeholder versions and capability states | OW reference remains `not_pinned` |
| BFF verification-run page/detail | `accepted_not_persisted` | BFF-UI contract and local store | `GET /api/v1/me/verify/runs`, `GET .../{runKey}` | YES | Aggregated run states and counts | In-memory only |
| BFF verification-run creation | `accepted_not_persisted` | BFF-UI contract and local store | `POST /api/v1/me/verify/runs` | YES | Pending request | `202` does not prove OW persistence |
| OW normalized read baseline | `default` | `docs/contracts/OW_READ_CONTRACT.md` | Server-side adapter boundary | Indirectly | Only through BFF projections | Reproducible OW pin/auth pending |
| Rich workout details, routes, GPS, laps, samples, `segments`, `hrZones` | `future_contract` | Contracts explicitly exclude them | None | NO | Unsupported/not verifiable | Requires endpoint, schema, privacy, and tests |
| Real OIDC, durable session, rate limiter, CSRF token, and persistent control plane | `future_contract` | Master plan and OIDC skill | None in this slice | NO | Local limitation only | Separate auth/control-plane wave |

Sync metadata classification is unchanged: upstream open metadata/messages/errors
remain `upstream_observed`; only BFF allowlisted output is `BFF_sanitized`; raw
values remain `raw_not_public`.

### 9. Risks

| ID | Marker | Risk | Probability/impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| R-21 | [RISK] | Synthetic modes can be mistaken for production auth. | Medium/high | Local-origin guard and explicit README limitation | Future auth owner | MITIGATED locally |
| R-22 | [RISK] | Origin validation alone could be mistaken for complete CSRF. | Medium/high | README explicitly states CSRF is pending; no claim of completion | Future auth owner | OPEN |
| R-23 | [RISK] | In-memory runs disappear on process restart. | High/medium | README and capability class `accepted_not_persisted` | Future control-plane owner | OPEN |
| R-24 | [RISK] | Unpinned OW or dependency ranges can change semantics. | Medium/high | Synthetic-only boundary and pending pin/lock | Integration owner | OPEN |
| R-25 | [RISK] | Strict projection can reject a future upstream shape. | Medium/medium | Fail closed and add a versioned serializer/test when contract changes | BFF owner | ACCEPTED |
| R-26 | [RISK] | Independent review handoff is unavailable in this build-mode turn. | Medium/high | Preserve PENDING closure and require review before integration | Coordinator/reviewer | OPEN |

### 10. Pending Items and Blockers

| ID | Pending item or blocker | Why it matters | Missing evidence | Owner | Start condition |
|---|---|---|---|---|---|
| P-21 | Reproducible OW pin | Prevents real compatibility claim | Release, tag, commit, or digest | OW integration owner | Pin selected and reviewable |
| P-22 | Real OIDC and cookie-session implementation | Synthetic mode is not auth | Provider, issuer, session, ownership, and revocation tests | Auth owner | Auth contract decision |
| P-23 | Complete cookie-mutation CSRF design | Origin check is not complete CSRF | CSRF token/session tests | Auth owner | Real cookie session exists |
| P-24 | Production rate limiting | Current BFF has no limiter | Per-session/IP policy and tests | Operations/auth owner | Runtime deployment design |
| P-25 | Durable control-plane persistence | Current runs are process memory | Storage schema, migration, backup, rollback | Control-plane owner | Database decision |
| P-26 | Python dependency lock | `pyproject.toml` uses bounded ranges | Reviewed lock/install evidence | Build owner | Package-management decision |
| P-27 | Independent diff/privacy/final review | Required closure evidence is absent in build mode | Separate handoffs | Coordinator | User permits a separate reviewer |

Inherited pending items remain: route/laps/samples/`segments`/`hrZones` public
schemas, Gadgetbridge-OW reproducible baseline and SQL-helper decision, raw
metadata/message/error sanitization against real OW, deployment, backup, and
restore policies.

### 11. Rollback

- Rollback condition: A reviewer finds a contract regression, a taint value reaches an HTTP response, or a local route no longer passes the required suite.
- Affected files or feature boundary: `apps/bff/src/bff/**`, `apps/bff/pyproject.toml`, and the BFF README only.
- Reversible action: Apply the reviewed inverse patch to these files or disable the local BFF process; do not reset or clean the worktree.
- Data impact: None; no OW or durable database was touched. Existing in-memory synthetic records are disposable process state.
- Post-rollback validation: Re-run the BFF/adapter pytest command, Ruff, Black, compile, and taint/error smoke checks.
- Unverified rollback: `[PENDING]` No deployed rollback was tested because deployment is outside this slice.

### 12. Next Action

- Concrete next action: An independent reviewer reads the complete BFF diff and reruns the listed offline commands, focusing on nested taint, error routes, and strict model projections.
- Owner: Coordinator assigns an independent reviewer when build-mode restrictions permit.
- Dependency: This handoff and the exact owned-file diff.
- May start when: The reviewer can work without overlapping edits.
- Do not do yet: Real OW/OIDC integration, Docker, Ansible, SQL, migrations, UI changes, maps/GPS, health-fact mutations, imports, AI, or comparisons.

### 13. Closure

- [x] Files and ownership are listed with relative paths.
- [x] Documentary markers and capability classes are separated.
- [x] The capability matrix does not present internal IDs or rich fields as public API.
- [x] Executed tests and scans have actual results; out-of-scope checks are `NOT RUN`.
- [x] Security, privacy, links/JSON/TOML, and reproducibility limits are recorded separately.
- [x] Rollback and next action are non-destructive and concrete.
- [ ] Independent reviewer confirms scope and findings.
- [ ] Independent privacy auditor provides a separate handoff.
- [ ] Independent final validator confirms closure.

Final result: `PENDING` until the required independent review handoffs exist.

Public signature of coordinator: Wave 2 BFF correction owner

Public signature of independent reviewer: `[PENDING]`
