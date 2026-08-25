# OW Readback Validation

**Captured:** 2026-08-17
**Evidence source:** completed disposable-wave handoff, sanitized
**Document status:** [PENDING] integration gates remain open

This document records a disposable, synthetic validation wave. It is not an OW
release note, a deployment reference, or authorization to connect the BFF to OW.
The wave evidence is separated from the documentation-only checks performed for
this file.

## Scope

- [FIXED] Scope was limited to synthetic local OW behavior and disposable local
  infrastructure.
- [FIXED] The tested OW branch/head was mutable development state, not a release,
  immutable checkpoint, or production reference.
- [FIXED] No BFF live adapter was enabled. The browser-facing first slice remains
  fixture-based and read-only with respect to OW, with the BFF-owned
  `VerificationRun` as its only permitted write.
- [VERIFIED] The disposable-wave results below were taken only from the completed
  sanitized handoff. The wave was not rerun for this documentation-only change.
- [FIXED] This documentation-only task did not start services, query databases,
  run migrations, access real data, or use network.
- [FIXED] No real data, production account, private export, raw payload, or
  deployment environment is represented here.

Relevant public boundaries are [`OW_READ_CONTRACT.md`](../contracts/OW_READ_CONTRACT.md),
[`BFF_UI_CONTRACT.md`](../contracts/BFF_UI_CONTRACT.md), and the synthetic
fixtures [`ow-read-v1.json`](../fixtures/ow-read-v1.json) and
[`ui-verification-v1.json`](../fixtures/ui-verification-v1.json).

## Baseline

- [RISK] The OW branch/head used for the wave was mutable. It must not be called
  upstream, a release, or a production contract.
- `unverified` / [PENDING] An immutable OW reference is still required: a clean
  commit, immutable tag or release, or image digest, together with compatibility
  evidence for the schema, migrations, importer, BFF, and contracts.
- [FIXED] Synthetic success in this wave does not promote a mutable branch,
  local extension, or synthetic fixture to production capability.
- [PENDING] The Gadgetbridge-OW baseline and its compatibility reference remain
  open as well. The API/SDK path is the intended integration boundary; its exact
  reproducible reference is not closed by this wave.

## Snapshot Reconciliation

- [VERIFIED] The earlier `docs/baselines/checkpoint-dev-2026-08-16.yaml` recorded the legacy direct OW database path as present at that historical snapshot.
- [VERIFIED] The current Gadgetbridge-OW development diff removes `--ow-db-url`, `ow_db_url`, the optional `psycopg2` dependency, direct OW database helpers, and legacy invocation/tests from the supported current source.
- [FIXED] Local SQLite remains source-input extraction and scoping only; it is not an OW destination and does not authorize direct SQL against OW.
- [RISK] The current patch is uncommitted and mutable development evidence, not a release or production migration. Historical deployments are not claimed migrated.
- [PENDING] API/SDK construction of route, segments, and hrZones and the disposable OW internal persistence/readback are bounded evidence layers. Public rich workout readback and production persistence remain pending or `future_contract`.
- [PENDING] Null, true zero, absence, and parser sentinel values remain distinct; this wave does not fix a public sentinel meaning.
- [RISK] The disposable wave showed a cross-user developer-key risk. Ownership/Auth, sanitization, and the live BFF adapter decision remain open.

## Disposable Environment

- [VERIFIED] The wave created a temporary Docker network and temporary Postgres
  and Redis containers using fixed, non-`latest` image tags.
- [VERIFIED] Databases were disposable and backed by tmpfs only. No volumes were
  created.
- [VERIFIED] Cleanup was verified after the checks.
- [VERIFIED] No existing resources were changed.
- [FIXED] This document deliberately omits resource names, container identifiers,
  host ports, credentials, passwords, and private environment details.

## Commands and Results

[VERIFIED] The rows below, except the explicitly labeled current Gadgetbridge
row, are historical results from the sanitized disposable-wave handoff. They
are recorded at the level needed for public evidence and are not a new
disposable-wave execution log. The current Gadgetbridge row records fresh,
targeted source-patch evidence for this reconciliation.

| Check | Result | Boundary and limit |
|---|---|---|
| `alembic heads` against the online empty disposable database | [VERIFIED] PASS | Empty disposable database only; no production schema claim. |
| `alembic upgrade head` | [VERIFIED] PASS | Initial upgrade succeeded in the disposable database. |
| Alembic upgrade rerun | [VERIFIED] PASS | Safe rerun succeeded in the same disposable scope. |
| `alembic current` | [VERIFIED] PASS | Current migration state was readable after upgrade and rerun. |
| Targeted OW test selection | [VERIFIED] PASS: 187 tests passed | Targeted OW tests only; not the complete product or release test suite. |
| Ruff and formatter checks | [VERIFIED] PASS | Checks covered the disposable-wave OW scope. |
| Synthetic API flow through the documented SDK sync route | [VERIFIED] PASS: HTTP `202` returned | Acceptance only; `202` is not persistence or terminal success. |
| Direct synthetic worker path | [VERIFIED] PASS: terminal success reached | Synthetic direct worker only; no real queue worker was run. |
| Auth, status, and error observations | [VERIFIED] PASS | Only safe, generic observations were retained; raw payloads, credentials, and provider details are not reproduced. |
| Current Gadgetbridge API-only removal tests | [VERIFIED] PASS: 4 passed in 0.08s | Targeted synthetic tests for the removed option/keyword and API/SDK enrichment construction; no service, database, network, or real data. |
| Real queue worker | NOT RUN | Outside the disposable evidence; worker, retry, timeout, and rollback behavior remain pending. |

The documented SDK sync route is referenced by the OW read contract. Its
acceptance response and the later synthetic terminal observation are separate
facts and must not be collapsed into a persistence claim.

## API and Ownership

- [VERIFIED] The synthetic API flow used the documented SDK sync route and
  returned `202 Accepted`.
- [FIXED] `202 Accepted` means accepted or queued. It does not prove that health
  facts were validated, durably persisted, or readable through a public route.
- [VERIFIED] The direct synthetic worker reached a terminal success state after
  the accepted flow. This is disposable synthetic evidence, not proof of a live
  queue deployment.
- [RISK] The developer API key used by this branch was not user-scoped. The wave
  showed that a request could read another synthetic path user's data.
- [FIXED] This ownership failure is not hidden by the successful status checks.
  It blocks live adapter exposure.
- [PENDING] Implement server-side Auth and ownership before enabling the live
  adapter: resolve the authenticated identity, apply an explicit OW link, check
  ownership before every OW query, and keep the OW credential server-side.
- [PENDING] Add cross-user authorization tests that prove an authenticated user
  cannot select or read another user's OW data, including through runs and error
  paths. Do not use the developer key's behavior as a production authorization
  model.

The BFF remains the only intended browser intermediary. The browser must not
choose the OW user, receive a credential, call an OW URL, or receive raw upstream
content. See the ownership boundary in
[`BFF_UI_CONTRACT.md`](../contracts/BFF_UI_CONTRACT.md).

## Persistence and Readback

- [VERIFIED] Local ORM/readback evidence existed in the disposable synthetic
  database for sources, timeseries, workouts, sleep, daily-total behavior, route
  points, and workout details.
- [VERIFIED] The handoff retained only aggregate synthetic counts for this
  readback. It did not reproduce item values, raw records, route points, or
  internal identifiers.
- [FIXED] Internal ORM/readback evidence is not a public API response. It does
  not authorize the BFF to query OW PostgreSQL directly or to copy health facts
  into its control plane.
- [RISK] The `202` response alone is not persistence evidence. The terminal
  synthetic observation and internal readback are separate evidence layers.
- `persisted_internal` / [VERIFIED] The local database evidence supports only an
  internal disposable persistence observation for the listed entities and
  aggregate counts.
- `future_contract` / [PENDING] Public route, `segments`, and `hrZones` readback
  was not proven. No browser-facing detail or route capability may be inferred
  from internal storage or accepted input.
- `accepted_not_persisted` / [PENDING] The current Gadgetbridge API/SDK patch
  constructs route, `segments`, and `hrZones` request fields and has targeted
  synthetic coverage, but this does not prove authorized acceptance, canonical
  persistence, ownership, or public readback.
- [PENDING] Until a versioned, authorized, privacy-reviewed public extension and
  readback test exist, rich workout detail remains `not_verifiable` or
  `unsupported` in the BFF/UI boundary.

The current public read boundary remains the documented aggregate surface in
[`OW_READ_CONTRACT.md`](../contracts/OW_READ_CONTRACT.md). The existing
disposition of the legacy database path is recorded in
[`legacy-db-disposition.md`](./legacy-db-disposition.md).

## Replay and Terminality

- [VERIFIED] Replaying the same synthetic input kept aggregate readback counts
  stable while creating a second sync control event.
- [FIXED] Stable aggregate counts are not, by themselves, proof of public
  idempotency, durable deduplication, or production concurrency behavior.
- [VERIFIED] The direct synthetic worker produced a terminal success after the
  accepted request path.
- [FIXED] A pending or accepted state remains pending until a consistent terminal
  observation is available. Partial, failed, cancelled, skipped, or inconsistent
  states must not be presented as complete persistence.
- [PENDING] Run a real queue-worker wave later with explicit retry, timeout,
  correlation, idempotency, backup, and rollback evidence. No real queue worker
  was run in the disposable wave.

## SQL Boundary

- [VERIFIED] The earlier 2026-08-16 checkpoint recorded the legacy `--ow-db-url`
  path as present at that historical snapshot.
- [VERIFIED] The current uncommitted Gadgetbridge-OW diff removes `--ow-db-url`,
  `ow_db_url`, the optional `psycopg2` dependency, direct OW database helpers,
  and legacy invocation/tests from the supported current source.
- [VERIFIED] The current source removal was independently static-checked and the
  targeted synthetic option/keyword and API/SDK enrichment tests passed.
- [FIXED] The normal Enano Coach path must use the authenticated OW API/SDK
  boundary, never ordinary external SQL against OW PostgreSQL.
- `fork_extension` / [VERIFIED] The current source-removal patch is mutable
  development evidence, not a release or production migration.
- [RISK] No historical deployment is claimed migrated, and release/integration
  adoption of the current patch remains pending. See
  [`legacy-db-disposition.md`](./legacy-db-disposition.md).

## Capability Classifications

The only technical capability classifications used in this document are
`default`, `fork_extension`, `persisted_internal`, `public_api`,
`accepted_not_persisted`, `future_contract`, and `unverified`. The only
documentary markers used are [FIXED], [PROPOSED], [PENDING], [RISK], and
[VERIFIED]. A technical class and a documentary marker are separate dimensions.

| Capability or observation | Class | Marker | Evidence boundary | Public conclusion |
|---|---|---|---|---|
| OW normalized read baseline | `default` | [PENDING] | Documented read contract plus synthetic disposable evidence | Candidate base behavior only; mutable branch and authorization remain open. |
| Local OW schema and migration extensions | `fork_extension` | [PROPOSED] | Mutable branch implementation and disposable migration checks | Development evidence only; no production pin. |
| SDK sync acceptance route | `unverified` | [VERIFIED] | Documented local route returned synthetic HTTP `202`; local route/acceptance evidence only, without authorized ownership or an immutable reference | Local route observed only; not production `public_api` and not persistence proof. |
| SDK acceptance without terminal readback | `accepted_not_persisted` | [VERIFIED] | `202` acceptance is distinct from terminal success/readback | Do not mark data persisted from acceptance. |
| Current API/SDK route, `segments`, and `hrZones` construction | `accepted_not_persisted` | [PENDING] | Current uncommitted source and targeted synthetic payload tests | Request construction only; no authorized acceptance, canonical persistence, ownership, or public rich readback. |
| Sources, timeseries, workouts, sleep, daily-total, route-point, and workout-detail ORM/readback counts | `persisted_internal` | [VERIFIED] | Disposable synthetic database and aggregate-only readback | Internal evidence only; no public response or BFF health-data copy. |
| Public route, `segments`, and `hrZones` readback | `future_contract` | [PENDING] | No proven public readback in the wave | Keep out of the browser; use `not_verifiable` or `unsupported`. |
| Developer-key ownership isolation | `unverified` | [RISK] | Key was not user-scoped and could cross synthetic path users | Block live adapter exposure until Auth and ownership are implemented and tested. |
| Terminal worker, replay, and retry semantics | `unverified` | [PENDING] | Direct synthetic worker and replay observations only | A real queue worker, retries, and rollback remain unproven. |
| Historical legacy `--ow-db-url` SQL path and current removal | `fork_extension` | [VERIFIED] | Historical checkpoint recorded presence; current uncommitted diff removes the option, dependency, helpers, and legacy tests | Direct SQL remains prohibited; release/integration adoption is pending and no historical deployment migration is claimed. |

For sync content, `upstream_observed` means an open upstream shape, only
`BFF_sanitized` allowlisted aggregates may cross the browser boundary, and
`raw_not_public` content must not enter public fixtures or responses. These are
sync-flow labels, not additional capability classifications.

## Risks

| Risk | Class | Marker | Impact | Required mitigation |
|---|---|---|---|---|
| Developer API key is not user-scoped | `unverified` | [RISK] | Another synthetic path user's data could be read | Implement explicit Auth, OW linking, server-side ownership checks, and cross-user tests before live adapter exposure. |
| Mutable OW branch/head | `unverified` | [RISK] | Schema and behavior can drift; rollback is not reproducible | Create and review an immutable checkpoint before real integration or deployment. |
| Internal readback mistaken for public capability | `persisted_internal` | [RISK] | ORM evidence could leak into a browser contract | Require an authorized public route, schema, ownership, privacy policy, and tests. |
| Accepted `202` mistaken for terminal persistence | `accepted_not_persisted` | [RISK] | Import state or UI could report false completion | Require consistent terminal observation and retain pending state otherwise. |
| Public route/detail readback absent | `future_contract` | [RISK] | Route points, `segments`, and `hrZones` could be exposed without association or privacy controls | Keep rich detail out of the BFF/UI until a formal extension is approved. |
| Real worker and rollback behavior not exercised | `unverified` | [RISK] | Retries, timeouts, and recovery may diverge from the synthetic path | Run a separately authorized worker/retry/backup/rollback wave. |
| Historical SQL path and mutable source removal | `unverified` | [RISK] | The historical path bypassed the OW API boundary; current removal is not an immutable release and does not prove historical deployments migrated | Keep direct SQL prohibited; pin references and complete the adoption decision. |

## Pending Gates

The explicit gate order is:
`ownership/auth -> immutable OW/Gadgetbridge references -> live sanitization and authorized persistence/readback -> release/integration adoption -> BFF live adapter decision`.

The gates are ordered. The BFF live adapter must not be enabled before they are
closed.

1. [PENDING] **ownership/auth.** Implement server-side identity resolution,
   explicit OW linking, per-query ownership checks, credential isolation, and
   cross-user `401`/`403` tests without an ownership oracle.
2. [PENDING] **immutable OW/Gadgetbridge references.** Fix the OW and
   Gadgetbridge-OW references to clean, auditable commits, immutable
   tags/releases, or image digests and verify compatibility.
3. [PENDING] **live sanitization and authorized persistence/readback.** Implement
   and test the allowlist for status, aggregate counts, warning codes, and safe
   error summaries. Keep upstream metadata, messages, errors, and raw payloads
   `raw_not_public`.

   The public extension/readback limitation remains pending: decide whether
   route points, workout details, `segments`, and `hrZones` receive versioned
   authorized GET schemas with association, pagination, and privacy rules. Until
   then, retain `future_contract` and `not_verifiable` boundaries.

   Worker, retry, and rollback evidence also remains pending: verify a real queue
   worker, terminal state mapping after `202`, replay/idempotency behavior,
   timeout and partial handling, migration backup/restore, and non-destructive
   rollback.
 4. [PENDING] **release/integration adoption.** Review the current uncommitted
    API-only removal patch against fixed compatible references, record rollback,
    and do not infer any historical deployment migration.
 5. [PENDING] **BFF live adapter decision.** Only after the earlier gates, expose
    the allowlisted BFF adapter through relative browser routes with server-side
    ownership and tested sanitization. Do not expose the SDK sync route to the
    browser.

## Rollback

- **Rollback condition:** A reviewer finds an unsupported claim, a privacy leak,
  a broken relative link, or evidence that conflicts with the completed
  disposable-wave handoff.
- **Affected files:** The permitted phase-next documentation files only.
- **Reversible action:** Apply a reviewed inverse documentation patch or revise
  the affected evidence statement. Do not alter OW, Gadgetbridge-OW, application
  code, databases, containers, or migrations.
- **Data impact:** None for this documentation-only change. The disposable-wave
  resources were already cleaned, and no existing resources were changed.
- **Post-rollback validation:** Recheck Markdown structure, fenced blocks,
  relative links, privacy patterns, tracked `git diff --check`, and the
  untracked-file whitespace/no-index check for the owned files.
- [PENDING] No deployed rollback was tested; deployment is outside this scope.

## Next Action

- [PENDING] Gate order is `ownership/auth -> immutable OW/Gadgetbridge references -> live sanitization and authorized persistence/readback -> release/integration adoption -> BFF live adapter decision`. Ownership/Auth still requires a synthetic cross-user test that fails closed; immutable references must be established before live checks; the current source removal is verified but remains uncommitted, and no historical deployment migration is claimed.
- **Owner:** BFF/Auth implementation wave.
- **Dependency:** Immutable evidence boundary and the documented BFF/OW
  contracts.
- **Do not do yet:** Enable a live adapter, expose route/detail fields, run the
  historical SQL path, use real data, or treat the mutable patch as a release.

## Closure

- [VERIFIED] This file captures the sanitized disposable-wave results requested
  for 2026-08-17 and preserves the non-user-scoped developer-key risk.
- [FIXED] No production capability is claimed from the mutable branch, synthetic
  API response, internal ORM/readback evidence, or direct synthetic worker.
- [FIXED] Only the permitted phase-next documentation files are in scope.
  Existing contracts, fixtures, plans, skills, application code, OW checkout,
  and Gadgetbridge-OW checkout are not modified by this task.
- [PENDING] Integration remains blocked by the gates above, especially ownership
  and Auth, live sanitization, and the immutable checkpoint.

### Documentation-only validation

The following checks apply to this Markdown file, not to the disposable OW wave.

| Check | Result | Scope |
|---|---|---|
| Markdown structure and fenced blocks | [VERIFIED] PASS | Offline validation checked all three phase-next files; fences are balanced and permitted markers are used. |
| Relative links | [VERIFIED] PASS | Offline validation resolved every inline relative link in the three phase-next files. |
| Privacy scan | [VERIFIED] PASS | Offline validation found no absolute paths, private-network addresses, credential URLs, bearer values, private keys, or emails in the four owned files. |
| Whitespace checks | [VERIFIED] PASS | Trailing-whitespace scan and four `git diff --no-index --check` commands produced no diagnostics. |
