# Development Compatibility Matrix

**Status:** [PROPOSED] evidence package for the next phase
**Captured:** 2026-08-17
**Production reference:** none
**Boundary:** Current branches and the current Gadgetbridge-OW patch are mutable development evidence. They are not releases, production migrations, public deployment references, or permission to connect to real data.

## Snapshot Reconciliation

- [VERIFIED] The earlier `docs/baselines/checkpoint-dev-2026-08-16.yaml` recorded the legacy direct OW database path as present at that historical snapshot.
- [VERIFIED] The current Gadgetbridge-OW development diff removes `--ow-db-url`, `ow_db_url`, the optional `psycopg2` dependency, direct OW database helpers, and legacy invocation/tests from the supported current source.
- [FIXED] Local SQLite remains source-input extraction and scoping only. It is not an OW destination and is not an Enano Coach integration path.
- [RISK] The current patch is uncommitted and mutable development evidence. It is not a release or production migration, and no historical deployment is claimed migrated.
- [PENDING] API/SDK construction of `route`, `segments`, and `hrZones` is bounded to request construction and targeted synthetic tests. Disposable OW internal persistence/readback is bounded internal evidence only. Public rich workout readback and production persistence remain pending or `future_contract` as classified below.
- [PENDING] Null, true zero, absence, and parser sentinel values remain distinct. The current local extraction/test behavior does not promote a sentinel to public OW meaning without source, schema, and readback evidence.
- [FIXED] Direct SQL against OW PostgreSQL remains prohibited for the Enano Coach BFF and normal importer path.
- [RISK] The disposable wave showed a cross-user developer-key risk. Ownership/Auth, sanitization, and the live BFF adapter decision remain gated.

## Baseline State

The checkpoint is the only document that retains exact development refs. This matrix intentionally omits repository-management metadata. Current mutable OW and Gadgetbridge-OW branches are authoritative development baselines we will modify; they are development-only and are not releases or deployment references.

| Repository | Relative checkout | Classification | Marker |
|---|---|---|---|
| Enano Coach | `.` | `unverified` | [PENDING] |
| Open Wearables | `../open-wearables` | `unverified` | [PENDING] |
| Gadgetbridge-OW | `../gadgetbridge-ow` | `unverified` | [PENDING] |

Unassigned development artifacts are deliberately excluded from this delivery; their contents were not copied into this document.

## Contract And Fixture Crosswalk

| Boundary | Reference | Version or shape | Classification | Marker | Compatibility limit |
|---|---|---|---|---|---|
| OW reads | `docs/contracts/OW_READ_CONTRACT.md` | `ow-read-v1` | `unverified` | [PROPOSED] | Observed local read baseline; no authorized response, fixed reference, ownership, or read-back evidence is recorded here. |
| BFF to UI | `docs/contracts/BFF_UI_CONTRACT.md` | `bff-ui-v1`, `schemaVersion: "1"` | `public_api` | [FIXED] | Stable synthetic UI boundary; not evidence of a real OW runtime. |
| Local date-window crosswalk | `apps/bff/src/bff/service.py`, `apps/bff/src/adapter/live.py`, `docs/contracts/OW_READ_CONTRACT.md` | Public `YYYY-MM-DD` logical day -> local fork `start_date`/`end_date` UTC RFC3339 `Z` values | `fork_extension` | [PROPOSED] | Development evidence for the observed mutable fork only; the wire encoding is not a universal OW public claim and remains pending an immutable reference. |
| First-slice build order | `docs/MVP_UI_BUILD_BRIEF.md` | fixture -> BFF -> UI | `future_contract` | [PROPOSED] | Does not add OW routes or authorize direct SQL. |
| OW fixture | `docs/fixtures/ow-read-v1.json` | snake_case, `synthetic: true` | `public_api` | [VERIFIED] | Synthetic/local-only adapter evidence; paginated wrappers intentionally omit optional `metadata`, while the live adapter accepts and drops allowlisted local metadata. No real authorization or persistence proof. Its `timeseries_value_null` case preserves null/zero semantics but is not literal local OW response evidence because the local response schema declares a non-null value. |
| BFF/UI fixture | `docs/fixtures/ui-verification-v1.json` | camelCase, `synthetic: true` | `public_api` | [VERIFIED] | Synthetic/local-only contract evidence; covers contractual shapes and negative cases, not live transport or a real OW runtime. |
| Evidence rules | `AGENTS.md`, `docs/PROJECT_PLAN.md` | taxonomy and markers | `unverified` | [FIXED] | All local implementation claims remain bounded by the source and pin state. |

The first slice remains read-only with respect to OW. The only write in that slice is the BFF-owned idempotent `VerificationRun`; it does not mutate OW health facts. The BFF currently demonstrates that path against an offline fixture and an in-memory control store in `apps/bff/src/adapter/offline.py:1-17` and `apps/bff/src/bff/store.py:100-102`.

## Trust Boundary

```text
synthetic OW fixture or later pinned OW API
                    |
                    v
          server-side adapter / BFF
                    |
                    v
             BFF-UI view model
                    |
                    v
             browser through /api
```

The browser must not choose `user_id`, receive an OW credential, call an OW URL, receive an OW cursor, read SQL, or see raw payloads. The current frontend uses relative allowlisted routes in `apps/web/src/api.ts:27-43` and `apps/web/scripts/proxy-policy.ts:92-106`. The service worker makes `/api` network-only in `apps/web/public/sw.js:34-47`.

## OW Route Matrix

These are local source observations from the OW fork and the proposed `ow-read-v1` contract. A route observed only in source is `unverified`; it is not `public_api` without an authorized HTTP response, fixed reference, ownership check, and read-back evidence.

| Domain | Observed route | Schema or source evidence | Class | Marker | BFF/UI use | Limit |
|---|---|---|---|---|---|---|
| Source inventory | `GET /api/v1/users/{user_id}/data-sources` | `docs/contracts/OW_READ_CONTRACT.md:80-83`; registration `../open-wearables/backend/app/api/routes/v1/__init__.py:57`; route `../open-wearables/backend/app/api/routes/v1/data_sources.py:17-25` | `unverified` | [PENDING] | Candidate sanitized sources and provenance | Source registration only; no authorized response/read-back evidence. |
| Capability inventory | `GET /api/v1/meta/coverage` | `../open-wearables/backend/app/api/routes/v1/meta.py:121-127` | `unverified` | [PENDING] | Candidate theoretical capabilities | Does not prove user data or coverage; HTTP behavior is unverified. |
| Timeseries | `GET /api/v1/users/{user_id}/timeseries` | `../open-wearables/backend/app/api/routes/v1/timeseries.py:17-36`; `../open-wearables/backend/app/schemas/responses/activity/data_point_responses.py:11-20` | `unverified` | [PENDING] | Candidate read samples with server-side pagination | Local source declares a non-null `value`; `resolution` acceptance does not prove downsampling or response semantics. |
| Activity summary | `GET /api/v1/users/{user_id}/summaries/activity` | `../open-wearables/backend/app/api/routes/v1/summaries.py:22-41`; `../open-wearables/backend/app/schemas/responses/activity/summaries.py:22-40` | `unverified` | [PENDING] | Candidate daily activity aggregates | No authorized response/read-back evidence; do not sum it again with samples. |
| Sleep summary | `GET /api/v1/users/{user_id}/summaries/sleep` | `../open-wearables/backend/app/api/routes/v1/summaries.py:44-58`; `../open-wearables/backend/app/schemas/responses/activity/summaries.py:63-87` | `unverified` | [PENDING] | Candidate main sleep/naps/stages | No authorized response/read-back evidence; generic `sleeping` is not a specific stage. |
| Recovery summary | `GET /api/v1/users/{user_id}/summaries/recovery` | `../open-wearables/backend/app/api/routes/v1/summaries.py:60-73`; `../open-wearables/backend/app/schemas/responses/activity/summaries.py:174-182` | `unverified` | [PENDING] | Candidate recovery fields preserving null | No authorized response/read-back evidence; null is not score zero. |
| Body summary | `GET /api/v1/users/{user_id}/summaries/body` | `../open-wearables/backend/app/api/routes/v1/summaries.py:76-98`; `docs/contracts/OW_READ_CONTRACT.md:210-224` | `unverified` | [PENDING] | Candidate query-relative body view | No selected-day historical body filter or authorized response/read-back evidence. |
| Data inventory | `GET /api/v1/users/{user_id}/summaries/data` | `../open-wearables/backend/app/api/routes/v1/summaries.py:101-116` | `unverified` | [PENDING] | Candidate aggregate inventory | No authorized response/read-back evidence; no cursor and not a sample query. |
| Workout aggregate | `GET /api/v1/users/{user_id}/events/workouts` | `../open-wearables/backend/app/api/routes/v1/events.py:21-40`; `../open-wearables/backend/app/schemas/responses/activity/events.py:14-29` | `unverified` | [PENDING] | Candidate aggregate workout list | No authorized response/read-back evidence; no public detail, route, laps, samples, `segments`, or `hrZones` GET route. |
| Sleep events | `GET /api/v1/users/{user_id}/events/sleep` | `../open-wearables/backend/app/api/routes/v1/events.py:43-67`; `../open-wearables/backend/app/schemas/responses/activity/events.py:61-73` | `unverified` | [PENDING] | Candidate published sessions and intervals | No authorized response/read-back evidence; retention, priority, and overnight date policy remain bounded by the contract. |
| Sync runs | `GET /api/v1/users/{user_id}/sync/runs` | `../open-wearables/backend/app/api/routes/v1/sync_status.py:118-131`; `../open-wearables/backend/app/schemas/sync_status.py:83-104` | `unverified` | [PENDING] | Candidate sanitized run state | No authorized response/read-back evidence; bounded array and no real cursor. |
| Recent sync | `GET /api/v1/users/{user_id}/sync/recent` | `../open-wearables/backend/app/api/routes/v1/sync_status.py:98-115`; `../open-wearables/backend/app/schemas/sync_status.py:56-80` | `unverified` | [PENDING] | Candidate sanitized recent state | No authorized response/read-back evidence; retention is limited and raw fields are not public. |
| Sync stream | `GET /api/v1/users/{user_id}/sync/stream` | `../open-wearables/backend/app/api/routes/v1/sync_status.py:56-95` | `unverified` | [PENDING] | Candidate server-side SSE consumption | No authorized response/read-back evidence; SSE is not pagination and raw frames remain `raw_not_public`. |
| SDK ingestion | `POST /api/v1/sdk/users/{user_id}/sync` | `../open-wearables/backend/app/api/routes/v1/sdk_sync.py:19-34`; `../open-wearables/backend/app/schemas/responses/upload/upload_response.py:34-41` | `unverified` | [PENDING] | Candidate importer-only API path | Local route construction and a `202` shape do not prove authorized acceptance or persistence. |

## OW Schema And Migration Matrix

| Capability or field | Observed layer | Evidence | Class | Marker | Public conclusion |
|---|---|---|---|---|---|
| `isDailyTotal` | SDK schema alias, model, migration, tests | `../open-wearables/backend/app/schemas/providers/mobile_sdk/sync_request.py:71-90`; `../open-wearables/backend/app/models/data_point_series.py:31-38`; `../open-wearables/backend/migrations/versions/2026_06_24_1940-9f0940493a9b_data_point_is_daily_total.py:20-28`; `../open-wearables/backend/tests/schemas/test_mobile_sdk_sync_request.py:1-26` | `fork_extension` | [PROPOSED] | Preserve the flag; acceptance does not by itself prove a real public read. |
| Retry-safe daily-total storage | repository/integration tests | `docs/PROJECT_PLAN.md:1132-1135`; `../open-wearables/backend/tests/integrations/test_sdk_daily_total_import.py` | `persisted_internal` | [PENDING] | Do not re-sum in the BFF. |
| `DataPointSeries.value` precision | model and migration | `../open-wearables/backend/app/models/data_point_series.py:31-38`; `../open-wearables/backend/migrations/versions/2026_08_07_1200-f6a7b8c9d0e1_data_point_series_value_precision.py:20-38` | `fork_extension` | [PROPOSED] | Migration evidence only; backup/restore and live compatibility are unverified. |
| Workout `route` input | SDK schema | `../open-wearables/backend/app/schemas/providers/mobile_sdk/sync_request.py:115-149` | `fork_extension` | [PROPOSED] | Input shape is known; public association is not. |
| Workout `segments` and `hrZones` input | SDK schema, model, migration | `../open-wearables/backend/app/schemas/providers/mobile_sdk/sync_request.py:144-151`; `../open-wearables/backend/app/models/workout_details.py:57-59`; `../open-wearables/backend/migrations/versions/2026_05_27_1356-2d316787b998_workout_details_jsonb_update.py:21-49` | `fork_extension` | [PROPOSED] | No public GET contract. |
| Workout details internal fields | model and migration | `../open-wearables/backend/app/models/workout_details.py:11-59` | `persisted_internal` | [PENDING] | Internal storage cannot be exposed as a browser fact. |
| Workout `samples`, `laps`, notes, title, metadata | accepted SDK input | `../open-wearables/backend/app/schemas/providers/mobile_sdk/sync_request.py:128-151`; `docs/PROJECT_PLAN.md:1149` | `accepted_not_persisted` | [PENDING] | Do not claim complete canonical persistence. |
| Aggregate workout response | local authenticated route and response model | `../open-wearables/backend/app/api/routes/v1/events.py:21-40`; `../open-wearables/backend/app/schemas/responses/activity/events.py:14-29`; `../open-wearables/backend/tests/api/v1/test_workouts.py` | `unverified` | [PENDING] | Source shape only; no authorized HTTP response, fixed reference, ownership, or read-back evidence. |
| Sync `batch_id`/`run_id` and state fields | local SDK response and sync-status source | `../open-wearables/backend/app/api/routes/v1/sdk_sync.py:80-131`; `../open-wearables/backend/app/schemas/sync_status.py:56-104`; `../open-wearables/backend/tests/api/v1/test_sync_status.py` | `unverified` | [PENDING] | Local shape/tests only; BFF must keep correlation server-side and authorized terminal read-back remains pending. |
| Optional paginated `metadata` | live adapter boundary and synthetic wrapper shape | `apps/bff/src/adapter/live.py`; `docs/contracts/OW_READ_CONTRACT.md:105-125`; `docs/fixtures/ow-read-v1.json` | `unverified` | [PENDING] | The base fixture may omit it; when the local fork returns it, only `resolution`, `sample_count`, `start_time`, and `end_time` are validated and discarded. It is not a browser field or a universal OW capability. |
| Sync `metadata`, `message`, `error` | upstream schema | `../open-wearables/backend/app/schemas/sync_status.py:68-77`; `docs/contracts/BFF_UI_CONTRACT.md:527-542` | `unverified` | [PENDING] | `upstream_observed`; only tested `BFF_sanitized` fields may cross; raw is `raw_not_public`. |
| `timeseries_value_null` fixture mismatch | OW response schema versus BFF/fixture normalization | `docs/fixtures/ow-read-v1.json:142-163`; `docs/contracts/OW_READ_CONTRACT.md:291-300`; `../open-wearables/backend/app/schemas/responses/activity/data_point_responses.py:11-20` | `unverified` | [RISK] | [PENDING] Decide the contract/adapter treatment; the local OW schema declares a non-null value, so the fixture case is not literal OW response evidence. |

## Gadgetbridge-OW Matrix

| Area | Observed behavior | Evidence | Class | Marker | Limit |
|---|---|---|---|---|---|
| Parser constants | Raw sport codes map to `outdoor_walking`, `outdoor_cycling`, `pool_swimming`, `elliptical`, and `freestyle`; SDK endpoint and metric names are defined. | `../gadgetbridge-ow/src/gadgetbridge_ow/constants.py:21-41`, `:66-89` | `fork_extension` | [PROPOSED] | Product equivalence and original-type policy remain open. |
| Normalizer activity | Creates SDK records, emits UTC ISO timestamps, and marks daily summary steps/calories with `isDailyTotal` when applicable. | `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py:55-74`, `:133-171`; `../gadgetbridge-ow/tests/test_normalizer.py:86-128` | `fork_extension` | [PROPOSED] | Parser behavior is not a production importer contract. |
| Normalizer sleep | Creates non-overlapping intervals; explicit or inferred gaps in an observed transition sequence remain `unknown`, while aggregate-only sessions remain generic `sleeping`; neither invents deep/light/rem. | `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py`; `../gadgetbridge-ow/tests/test_normalizer.py`; `../open-wearables/backend/app/services/apple/healthkit/sleep_service.py`; `../open-wearables/backend/tests/services/test_sleep_service.py` | `fork_extension` | [VERIFIED] | Local synthetic tests cover preservation through OW finalization/readback; the parser and OW references remain unpinned for production. |
| Normalizer workout | `normalize_workout` can emit `route`, `segments`, and `hrZones` when enrichments are enabled and valid. | `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py:373-460`; `../gadgetbridge-ow/tests/test_normalizer.py:243-313` | `fork_extension` | [PROPOSED] | Does not prove OW persistence or a public read association. |
| API/SDK enrichment path | The current uncommitted `run_sync` path constructs workout requests with valid route, segments, and hrZones enrichments without the legacy database switch. | `../gadgetbridge-ow/src/gadgetbridge_ow/sync.py:1133-1316`; `../gadgetbridge-ow/tests/test_sync.py:981-1054` | `accepted_not_persisted` | [PENDING] | Request construction and targeted synthetic tests only; no authorized acceptance, canonical persistence, or public read-back. |
| SDK client | Local client posts the SDK route, polls sync runs, correlates `batch_id`/`run_id`, and requires terminal `completed` plus `success`. | `../gadgetbridge-ow/src/gadgetbridge_ow/client.py:17-35`, `:550-677`; `../gadgetbridge-ow/tests/test_client.py:128-204` | `unverified` | [PENDING] | Mocked transport and local control flow only; no authorized HTTP response, fixed reference, ownership, or persistence/read-back evidence. |
| Historical legacy database switch and helpers | The 2026-08-16 snapshot recorded the CLI switch, optional dependency, direct helpers, and legacy tests; the current diff removes them from the supported source. | `docs/baselines/checkpoint-dev-2026-08-16.yaml`; current diff in `../gadgetbridge-ow/pyproject.toml`, `src/gadgetbridge_ow/cli.py`, `src/gadgetbridge_ow/sync.py`, `tests/test_cli.py`, and `tests/test_sync.py` | `fork_extension` | [VERIFIED] | Current-source removal was statically checked and targeted synthetic tests passed. The patch is uncommitted; no historical deployment migration is claimed. |

## API Versus SQL Path

### Current API/SDK Path

1. The parser discovers local export files and local SQLite source data; the normalizer creates activity, sleep, and workout SDK shapes.
2. The current `run_sync` path sends workout enrichments through the SDK request construction in `../gadgetbridge-ow/src/gadgetbridge_ow/sync.py:1133-1316`.
3. The client posts the SDK route and polls sync status in `../gadgetbridge-ow/src/gadgetbridge_ow/client.py:615-677`.
4. Targeted synthetic tests cover the removed option/keyword and selected API/SDK enrichment construction in `../gadgetbridge-ow/tests/test_cli.py:57-83` and `../gadgetbridge-ow/tests/test_sync.py:456-466`, `:981-1054`.
5. `202 Accepted`, a non-terminal state, a partial result, dropped items, an error, or an ambiguous correlation does not establish persistence.

Classification: `accepted_not_persisted`, documentary marker [PENDING]. Current request construction and targeted tests do not establish authorized API acceptance, canonical persistence, ownership, public rich readback, or production compatibility.

### Historical Direct OW Database Path And Current Disposition

1. The 2026-08-16 checkpoint recorded the legacy CLI option, optional driver, direct helpers, and fallback tests as present at that historical snapshot.
2. The current uncommitted diff removes that option, `ow_db_url` plumbing, optional dependency, direct helpers, fallback branch, and legacy invocation/tests from the supported current source.
3. Independent static inspection and targeted synthetic tests verified the current removal surface; no service, database, migration, network, or real data was used for this documentation wave.
4. This is mutable development evidence, not a release or production migration. Historical deployments are not claimed migrated.

Classification: `fork_extension`, documentary marker [VERIFIED] for the current source-removal check. Direct SQL remains prohibited for Enano Coach; release/integration adoption of the patch is [PENDING]. The BFF must use the OW HTTP/API boundary and must never become an external SQL client.

## Compatibility Decisions

| Decision | Class | Marker | Current decision | Required before real integration |
|---|---|---|---|---|
| OW source of normalized health facts | `default` | [FIXED] | OW remains canonical; the app does not copy health facts. | None for the fixture slice; pin OW for real use. |
| BFF/UI first slice | `public_api` | [VERIFIED] | Use synthetic fixture -> adapter/BFF -> BFF view model -> UI. | Real BFF runtime, ownership, OIDC, and sanitization tests remain pending. |
| OW read route set | `unverified` | [PENDING] | Treat local route observations as candidates only; use the `ow-read-v1` shapes without claiming runtime availability. | Authorized checks against an immutable reference. |
| `isDailyTotal` semantics | `fork_extension` | [PROPOSED] | Preserve true/false/null; never infer or double-sum. | Verify persistence and response semantics on a pinned OW. |
| Rich workout detail | `future_contract` | [PENDING] | Aggregate-only; `segments`, `hrZones`, route, laps, and samples are not browser capabilities. | Versioned endpoint, schema, ownership, pagination, privacy, and tests. |
| Sync metadata | `unverified` | [PENDING] | `upstream_observed` server-side; `BFF_sanitized` only after allowlist/tests; `raw_not_public` always. | Real BFF sanitization and rejection tests. |
| Gadgetbridge baseline | `unverified` | [PENDING] | Current checkout is development evidence only. | Immutable commit/tag/release and replay tests. |
| Current API-only SQL disposition | `fork_extension` | [VERIFIED] | Removed in the current uncommitted development patch and independently static-verified; the historical snapshot remains historical. | Immutable reference, compatibility review, release/integration adoption, and no historical migration claim. |

## Known Gaps

| Gap | Class | Marker | Evidence | Effect |
|---|---|---|---|---|
| No public workout detail/route/laps/samples/`segments`/`hrZones` GET schema | `future_contract` | [PENDING] | `docs/contracts/OW_READ_CONTRACT.md:96-99`, `:500-517` | UI uses `aggregate_only`, `unsupported`, or `not_verifiable`. |
| Generic GPS series has no proven workout relationship | `future_contract` | [RISK] | `../open-wearables/backend/app/models/data_point_series.py:18-38`; `docs/contracts/OW_READ_CONTRACT.md:500-517` | Do not draw routes from timestamp coincidence. |
| Body summary has query-relative `latest` semantics | `unverified` | [FIXED] | `../open-wearables/backend/app/api/routes/v1/summaries.py:76-98`; `docs/contracts/OW_READ_CONTRACT.md:210-224` | Emit `BODY_RELATIVE_TO_NOW` when shown; local route behavior still needs authorized response evidence. |
| `resolution` may be accepted without being applied | `unverified` | [PENDING] | `../open-wearables/backend/app/api/routes/v1/timeseries.py:17-36`; `docs/contracts/OW_READ_CONTRACT.md:180-183` | Do not advertise downsampling yet. |
| `timeseries_value_null` fixture mismatch | `unverified` | [RISK] | `docs/fixtures/ow-read-v1.json:142-163`; `docs/contracts/OW_READ_CONTRACT.md:291-300`; `../open-wearables/backend/app/schemas/responses/activity/data_point_responses.py:11-20` | [PENDING] Decide the contract/adapter treatment; the fixture null is not literal OW response evidence while the local schema declares a non-null value. |
| Sync history is bounded and metadata is open | `unverified` | [PENDING] | `../open-wearables/backend/app/api/routes/v1/sync_status.py:98-131`; `../open-wearables/backend/app/schemas/sync_status.py:68-104` | BFF must sanitize and report `UPSTREAM_LIMITED` when closure is impossible. |
| Disposable OW internal persistence/readback | `persisted_internal` | [VERIFIED] | `docs/phase-next/ow-readback-validation-2026-08-17.md:106-127` | Synthetic internal aggregate evidence only; it is not a public rich workout response or permission for direct SQL. |
| Null, zero, and parser sentinel semantics | `unverified` | [PENDING] | `docs/contracts/OW_READ_CONTRACT.md:554-575`; current Gadgetbridge parser/normalizer tests | Preserve null and true zero; do not infer public sentinel meaning without a fixed schema and readback check. |
| Mapping semantics and sleep gap policy remain open | `unverified` | [PENDING] | `../gadgetbridge-ow/src/gadgetbridge_ow/constants.py:119-137`; `../gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py:174-242` | Do not close product comparison semantics from parser labels alone. |

## Risks And Pending Decisions

| ID | Class | Marker | Risk or decision | Mitigation or start condition |
|---|---|---|---|---|
| R-01 | `unverified` | [RISK] | Mutable branches can drift from the documented matrix. | Pin clean commit/tag/digest before real integration. |
| R-02 | `unverified` | [RISK] | The historical SQL path was outside the OW API boundary; the current removal is uncommitted and does not prove historical deployments migrated. | Keep direct SQL prohibited; pin the current source and complete the adoption decision in `legacy-db-disposition.md`. |
| R-03 | `accepted_not_persisted` | [RISK] | Accepted schema/input fields may not be canonically persisted. | Require authorized response and persistence/replay tests. |
| R-04 | `unverified` | [RISK] | Raw sync metadata or error text could leak upstream details. | Keep raw content server-side and test the BFF allowlist. |
| P-01 | `unverified` | [PENDING] | Exact OW production reference. | Must be fixed before real OW access. |
| P-03 | `unverified` | [PENDING] | Exact Gadgetbridge-OW production reference. | Must be fixed before real importer access. |
| P-12 | `unverified` | [PENDING] | Sleep nights crossing midnight. | Add decision and fixture before historical reconciliation. |
| P-17 | `unverified` | [PENDING] | Adopt the current API-only removal patch for a fixed integration/release reference. | Complete compatibility, ownership, sanitization, authorized persistence/readback, and rollback review; do not claim historical migration. |
| P-18 | `unverified` | [PENDING] | Exact server-side OW auth header/mechanism. | Confirm against pinned deployment without publishing credentials. |
| P-19 | `unverified` | [PENDING] | Sync sanitization allowlist and raw rejection tests. | Implement in BFF before real data crosses the boundary. |

## Rollback

**Marker:** [PROPOSED]

- **Condition:** The matrix contains an unsupported claim, leaks private information, or is incompatible with a later pinned reference.
- **Affected files:** `docs/baselines/checkpoint-dev-2026-08-17-api-only.yaml` and the three reconciled `docs/phase-next/` files only.
- **Reversible action:** Remove or revise those documentation files in a reviewed change. Do not alter source repositories or data, delete a database, or run a migration to resolve documentation drift.
- **Data impact:** None; no service, database, migration, network, or real-data operation was performed.
- **Post-rollback validation:** Parse YAML, validate relative Markdown links and fences, inspect the diff, and run `git diff --check`.

## Validation Evidence

The source audit used read-only file inspection. No service, database, migration, network, or real-data command was run.

| Check | Result | Scope and limit |
|---|---|---|
| Mandatory docs, fixtures, lockfile, seven custom skills, and relevant external skills read | [VERIFIED] | Read-only session scope; no claim about an external release. |
| Current Gadgetbridge API-only removal source inspection | [VERIFIED] | Current CLI, dependency, sync, and targeted tests were inspected; removed legacy symbols were absent from the checked files. |
| Targeted Gadgetbridge tests | [VERIFIED] | `pytest -q` over the removed option/keyword and selected API/SDK enrichment tests: 4 passed in 0.08s; no service, database, network, or real data. |
| Targeted Gadgetbridge lint | [VERIFIED] | Ruff check passed for the current dependency, CLI, sync, and targeted test files. |
| Gadgetbridge patch whitespace | [VERIFIED] | `git -C ../gadgetbridge-ow diff --check` produced no diagnostics. |
| YAML, JSON, Markdown, links, fences, privacy, and no-index whitespace | [VERIFIED] | Offline validation parsed the new checkpoint and both fixtures, checked permitted markers, balanced fences, relative links, privacy patterns, trailing whitespace, and all four no-index diff checks. |

## Next Action

[PENDING] Gate order is `ownership/auth -> immutable OW/Gadgetbridge references -> live sanitization and authorized persistence/readback -> BFF live adapter decision -> release/integration adoption`. Ownership/Auth still requires a synthetic cross-user test that fails closed; the developer-key cross-user risk remains open; immutable references must precede live checks. The current SQL removal is statically verified in mutable source, but no historical deployment migration is claimed and direct SQL remains prohibited. Do not connect Enano Coach to OW, run migrations, or use direct SQL before the gates close.
