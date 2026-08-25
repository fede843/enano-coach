# Legacy OW Database Path Disposition

**Status:** [PENDING] current source removal is verified; release and integration adoption remain open
**Captured:** 2026-08-17
**Production reference:** none
**Decision boundary:** This document reconciles a historical source observation with the current uncommitted API-only removal patch. It does not release the patch, migrate historical deployments, run a migration, access a database, or authorize real integration.

Current mutable OW and Gadgetbridge-OW branches are authoritative development baselines we will modify; they are development-only and are not releases or deployment references.

## Snapshot Reconciliation

- [VERIFIED] The earlier `docs/baselines/checkpoint-dev-2026-08-16.yaml` recorded `--ow-db-url`, `ow_db_url`, the optional `psycopg2` dependency, direct OW database helpers, and legacy invocation/tests as present at that historical snapshot.
- [VERIFIED] The current Gadgetbridge-OW development diff removes those items from the supported current source and keeps workout enrichment construction on the API/SDK path.
- [FIXED] Local SQLite remains source-input extraction and scoping only. It is not an OW destination and does not authorize external SQL against OW.
- [RISK] The current patch is uncommitted and mutable development evidence, not a release or production migration. Historical deployments are not claimed migrated.
- [PENDING] API/SDK construction of route, segments, and hrZones is bounded to request construction and targeted synthetic tests. Disposable OW internal persistence/readback is bounded internal evidence. Public rich workout readback and production persistence remain pending or `future_contract`.
- [PENDING] Null, true zero, absence, and parser sentinel values remain distinct; no sentinel is promoted to public OW meaning without fixed schema and readback evidence.
- [FIXED] Direct SQL against OW PostgreSQL remains prohibited for Enano Coach.

## Finding

The historical snapshot contained the legacy direct OW database path. The current uncommitted Gadgetbridge-OW patch removes `--ow-db-url`, `ow_db_url`, the optional `psycopg2` dependency, direct OW database helpers, and legacy invocation/tests from the supported current source. The normal API/SDK path constructs route, segments, and hrZones enrichments, but that construction does not prove authorized acceptance, canonical persistence, or public read-back.

Direct SQL against Open Wearables PostgreSQL is prohibited for Enano Coach. The BFF and any normal Enano Coach importer path must use an authenticated OW API/SDK boundary. The source-removal step is complete only as mutable development evidence; release/integration adoption remains a separate pending decision, and no historical deployment is claimed migrated.

Technical class for the historical path: `persisted_internal`. Technical class for the current source change: `fork_extension`.

Documentary status: [VERIFIED] for the current static removal check and targeted tests; [PENDING] for fixed-reference adoption, production persistence, and public rich readback.

## Observed Evidence

| Claim | Relative evidence | Classification | Marker | Limit |
|---|---|---|---|---|
| Historical legacy option and plumbing | `docs/baselines/checkpoint-dev-2026-08-16.yaml`; historical source evidence named there | `persisted_internal` | [VERIFIED] | Historical observation only; it is not a claim about the current source or a deployment. |
| Current option/dependency/helper removal | `../gadgetbridge-ow/pyproject.toml`; `../gadgetbridge-ow/src/gadgetbridge_ow/cli.py`; `../gadgetbridge-ow/src/gadgetbridge_ow/sync.py` | `fork_extension` | [VERIFIED] | Current-source static scan and targeted synthetic tests passed; the patch is uncommitted and mutable. |
| Legacy invocation/test removal | `../gadgetbridge-ow/tests/test_cli.py:57-83`; `../gadgetbridge-ow/tests/test_sync.py:456-466`, `:981-1054` | `fork_extension` | [VERIFIED] | Tests reject the removed option/keyword and exercise API/SDK enrichment construction; no service, database, network, or real data. |
| Local SQLite source extraction | `../gadgetbridge-ow/src/gadgetbridge_ow/sync.py:240-706` | `fork_extension` | [FIXED] | Source-input extraction and scoping only; no OW destination is implied. |
| API/SDK workout enrichment construction | `../gadgetbridge-ow/src/gadgetbridge_ow/sync.py:1133-1316`; `../gadgetbridge-ow/tests/test_sync.py:981-1054` | `accepted_not_persisted` | [PENDING] | Request construction and synthetic tests do not prove authorized acceptance, canonical persistence, ownership, or public readback. |
| Disposable internal OW persistence/readback | `docs/phase-next/ow-readback-validation-2026-08-17.md:106-127` | `persisted_internal` | [VERIFIED] | Historical disposable synthetic aggregate evidence only; it is not a public response or a BFF health-data store. |
| SDK client terminal correlation | `../gadgetbridge-ow/src/gadgetbridge_ow/client.py:17-35`, `:550-677`; `../gadgetbridge-ow/tests/test_client.py:128-204` | `unverified` | [PENDING] | Mocked/local control flow only; no authorized response, fixed reference, ownership, or production read-back evidence. |
| Normalizer can emit `route`, `segments`, and `hrZones` | `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py:373-460` | `fork_extension` | [PROPOSED] | Generated SDK input does not prove canonical OW persistence. |

## Path Comparison

| Property | Normal API/SDK path | Legacy direct-SQL path |
|---|---|---|
| Activation | Current `run_sync` has no `ow_db_url` parameter and uses the API/SDK path | Recorded in the 2026-08-16 snapshot; absent from the current supported source |
| Transport | `OpenWearablesClient` over the SDK route | `psycopg2` connection from importer code |
| Workout enrichments | Current SDK request construction can send `route`, `segments`, and `hrZones` when valid | Historical legacy mode suppressed SDK enrichments before its internal fallback |
| Correlation | POST response `batch_id` is matched to sync status `run_id`/batch identifier | Internal rows are matched using importer-side queries and internal event identifiers |
| Completion rule | Poll until correlated terminal `completed` + `success`; reject partial, error, dropped, ambiguous, or timed-out outcomes | Helper success is coupled to direct internal writes and importer state rollback |
| Canonical boundary | OW authenticated API/SDK contract | OW internal PostgreSQL schema |
| Enano Coach use | [PROPOSED] required integration direction | [FIXED] prohibited normal path |
| Classification | `accepted_not_persisted` | `persisted_internal` for the historical observation; current source status is `fork_extension` |
| Current marker | [PENDING] | [VERIFIED] for current source removal; [PENDING] for adoption and historical deployment status |

The API/SDK path is the only compatible direction for Enano Coach. The BFF must not call the SDK ingestion route from the browser, and the BFF must not issue SQL against OW. The first slice remains read-only with respect to OW; its only write is a BFF-owned `VerificationRun` control record. The current removal patch does not change that boundary.

## API Evidence

### SDK input and enrichment shape

The local OW SDK schema accepts `WorkoutRoutePoint`, `segments`, `hrZones`, `laps`, `route`, `samples`, and metadata in `../open-wearables/backend/app/schemas/providers/mobile_sdk/sync_request.py:115-151`. The local migration adds internal workout detail JSON fields in `../open-wearables/backend/migrations/versions/2026_05_27_1356-2d316787b998_workout_details_jsonb_update.py:21-49`.

Gadgetbridge normalizes parser data to the SDK wire shape in `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py:373-460`. The current `run_sync` path constructs the three relevant enrichment names when the input passes validation, and targeted synthetic tests assert the resulting API payload in `../gadgetbridge-ow/tests/test_sync.py:981-1054`.

Classification: `accepted_not_persisted` for current request construction, documentary marker [PENDING]. The generated request shape and targeted tests are not enough to claim public persistence.

### Terminal state and correlation

`OpenWearablesClient.sync` posts the SDK route and handles `200`, `201`, and `202` responses. It extracts a submitted batch identifier when available, polls the user sync-runs route, correlates the returned run, and requires a consistent terminal `completed` plus `success` result. The relevant code is `../gadgetbridge-ow/src/gadgetbridge_ow/client.py:550-677`, with synthetic tests in `../gadgetbridge-ow/tests/test_client.py:128-204`, `:282-379`, and `:390-457`.

Classification: `unverified`, documentary marker [PENDING]. A `202 Accepted` or active state is not terminal persistence, and the test doubles do not establish production compatibility, ownership, or read-back.

## Schema Gaps Blocking Rich Readback And Adoption

| Gap | Classification | Marker | Why it blocks rich readback or adoption |
|---|---|---|---|
| No versioned public GET for workout detail | `future_contract` | [PENDING] | Internal `WorkoutDetails` fields cannot be read through the documented OW surface. |
| No versioned public GET for workout-associated route | `future_contract` | [PENDING] | Generic latitude/longitude series and timestamp overlap do not prove one workout relationship. |
| No versioned public GET for `segments` or `hrZones` | `future_contract` | [PENDING] | SDK input and internal JSON columns do not establish browser-readable capability. |
| No versioned public GET for laps or samples | `future_contract` | [PENDING] | Accepted input is not canonical public persistence. |
| Effective timeseries resolution is not proven | `unverified` | [PENDING] | A route accepting `resolution` does not prove that downsampling occurred. |
| Sync history retention/continuation is bounded | `unverified` | [PENDING] | An absent bounded run entry cannot prove that a sync never existed. |
| Exact OW auth header and deployment policy are not pinned | `unverified` | [PENDING] | The importer cannot rely on a local header observation as a release contract. |
| Gadgetbridge-OW has no immutable production reference | `unverified` | [PENDING] | A mutable branch cannot support a reproducible importer rollback. |
| Null, zero, and parser sentinel semantics | `unverified` | [PENDING] | Null and true zero are distinct; parser sentinel meaning still needs fixed source/schema/readback evidence. |

Until these gaps are resolved, the BFF/UI must keep rich workout data as `aggregate_only`, `unsupported`, or `not_verifiable` according to the relevant contract. It must not expose internal IDs, raw metadata, routes, coordinates, or SQL results.

## Adoption Gate

The source-removal step is present in the current uncommitted development diff and was independently static-checked with targeted synthetic tests. It is not yet a release or integration decision. Adoption still requires one owner per external source file, an independent review, and fixed compatibility evidence.

| Gate | Required evidence | Class | Marker | Failure action |
|---|---|---|---|---|
| A-01 immutable OW reference | Clean commit, immutable tag/release, or image digest plus compatible schema reference | `unverified` | [PENDING] | Stop; keep source as development evidence only. |
| A-02 immutable Gadgetbridge reference | Clean commit/tag/release and parser version recorded without private values | `unverified` | [PENDING] | Stop; do not call the checkout a release. |
| A-03 API contract for retained enrichments | Authorized route, schema, ownership, pagination/privacy policy, and tests for any field retained | `future_contract` | [PENDING] | Keep rich detail `not_verifiable` or `unsupported`; do not replace the API with SQL. |
| A-04 current removal verification | Current diff, static absence scan, targeted tests, lint, and independent privacy/final review | `fork_extension` | [VERIFIED] | The current source-removal check passed; keep adoption open if any review disagrees. |
| A-05 terminal confirmation | `202` remains pending; correlation is unique; terminal success is required; partial/error/timeout do not advance state | `unverified` | [PENDING] | Do not mark an import complete without authorized terminal evidence. |
| A-06 persistence and read-back proof | Fixed OW API response and authorized read-back prove required fields, not only input acceptance | `unverified` | [PENDING] | Keep capability `not_verifiable` or `accepted_not_persisted`. |
| A-07 replay/idempotency proof | Repeating synthetic input does not duplicate records or change daily-total semantics | `unverified` | [PENDING] | Do not promote API construction to persistence. |
| A-08 ownership and sanitization | Cross-user rejection, server-side ownership, and tested `BFF_sanitized` allowlist | `unverified` | [PENDING] | Do not enable a live BFF adapter. |
| A-09 release/integration adoption | Review the mutable removal patch against fixed compatible references and define rollback | `unverified` | [PENDING] | Keep the patch development-only. |
| A-10 historical deployment status | Evidence that would justify a migration claim, if one is ever needed | `unverified` | [PENDING] | Make no historical migration claim. |

The current state is after A-04 for the checked source-removal surface and before A-01, A-02, A-03, A-05, A-06, A-07, A-08, A-09, and A-10. The current patch is not a production migration, and public rich workout readback remains a future contract.

## Enano Coach Rules

These are fixed boundaries, not implementation shortcuts:

- OW is the canonical source of normalized health facts.
- The browser calls only relative BFF routes.
- The BFF resolves ownership server-side and never accepts a browser-selected `user_id`.
- The BFF is not a generic URL proxy.
- Direct SQL against OW PostgreSQL is prohibited for the BFF and normal importer path.
- The application control plane may store identities, sessions, roles, links, audit records, jobs, and technical import state, but not a parallel copy of health facts.
- Raw upstream `metadata`, `message`, `error`, and payloads are `raw_not_public`; only allowlisted `BFF_sanitized` fields may cross the browser boundary after tests.
- The first slice does not import, edit, delete, retry, map, or mutate OW health facts.

Classification for the SQL prohibition: `future_contract` for any exception request, documentary marker [FIXED]. No exception is authorized by this document.

## Risks And Pending Decisions

| ID | Classification | Marker | Item | Owner or condition |
|---|---|---|---|---|
| R-DB-01 | `unverified` | [RISK] | The historical SQL path bypassed the OW API contract; the current removal is mutable and does not prove historical deployments migrated. | Import owner; keep direct SQL prohibited and complete A-01, A-02, A-09, and A-10. |
| R-DB-02 | `accepted_not_persisted` | [RISK] | SDK acceptance or a migration does not prove canonical read-back. | OW owner; require A-05 and A-06. |
| R-DB-03 | `future_contract` | [RISK] | GPS and rich workout fields can be sensitive and are not publicly associated. | BFF/OW owners; keep out of UI until A-03. |
| R-DB-04 | `unverified` | [RISK] | Mutable branches make rollback and compatibility non-reproducible. | Integration owner; require A-01, A-02, and A-09. |
| P-01 | `unverified` | [PENDING] | Exact compatible OW reference. | Required before real OW access. |
| P-03 | `unverified` | [PENDING] | Exact Gadgetbridge-OW reference and maintenance strategy. | Required before real importer access. |
| P-17 | `unverified` | [PENDING] | Release/integration adoption of the current API-only source removal. | Resolve after immutable references, compatibility review, ownership/sanitization, and rollback evidence; do not claim historical migration. |
| P-18 | `unverified` | [PENDING] | Exact OW auth header and ownership policy. | Required before authorized tests. |
| P-19 | `unverified` | [PENDING] | BFF sanitization allowlist for sync state and errors. | Required before real data crosses to UI. |

## Rollback

**Marker:** [PROPOSED]

- **Current wave:** This repository wave modifies documentation only. The external Gadgetbridge-OW source patch is observed, not edited by this task.
- **Rollback condition:** A reviewer finds an unsupported claim, a privacy leak, or evidence that conflicts with a pinned reference.
- **Reversible action now:** Revise or remove this document and the companion matrix/checkpoint in a reviewed documentation change. Do not alter source repositories or data.
- **Future adoption work:** If release/integration adoption fails, stop the adoption decision and retain the current source as mutable development evidence. Any source rollback belongs to a separately authorized external-repository change; do not re-enable direct SQL as an Enano Coach workaround.
- **Data impact:** None for this documentation wave; no database or migration command was run.
- **Post-rollback validation:** Re-run source inspection, API-path tests, YAML/Markdown checks, privacy scan, and `git diff --check`.

## Validation Evidence

| Check | Result | Scope and limit |
|---|---|---|
| CLI, dependency, parser, normalizer, client, sync, and tests inspected | [VERIFIED] | Read-only source inspection; no importer execution beyond targeted synthetic tests. |
| Current API-only removal | [VERIFIED] | Current source diff removes the option, dependency, direct helpers, fallback, and legacy invocation/tests; targeted tests passed 4/4 in 0.08s. |
| API/SDK enrichment construction | [PENDING] | Targeted synthetic construction tests passed, but authorized acceptance, persistence, ownership, and public readback remain unverified. |
| Disposable internal persistence/readback | [VERIFIED] | Historical sanitized disposable-wave evidence only; bounded internal aggregate evidence, not a public response. |
| YAML, JSON, Markdown, links, fences, privacy, and no-index whitespace | [VERIFIED] | Offline validation parsed the new checkpoint and both fixtures, checked permitted markers, balanced fences, relative links, privacy patterns, trailing whitespace, and all four no-index diff checks. |
| Services, database, migrations, network, and real data | [PENDING] | Explicitly not run by scope. |

## Next Action

[PENDING] Gate order is `ownership/auth -> immutable OW/Gadgetbridge references -> live sanitization and authorized persistence/readback -> BFF live adapter decision -> release/integration adoption`. Ownership/Auth still requires a synthetic cross-user test that fails closed; immutable references must precede live checks; current source removal is verified but remains uncommitted and no historical deployment migration is claimed. Keep direct SQL prohibited, do not enable the live BFF adapter, and do not claim public rich readback or production persistence until the gates close.
