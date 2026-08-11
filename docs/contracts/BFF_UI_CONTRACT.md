# BFF-UI Verification Contract

**Status:** [FIXED] minimum contract for read-only health reading from OW and the
BFF's own `VerificationRun`.
**Version:** `bff-ui-v1` (`schemaVersion: "1"`).
**Audience:** frontend, BFF, fixture adapter, and contract tests.
**Visibility:** [FIXED] public. The examples are synthetic and contain no
identities, credentials, file paths, or private payloads.

This document defines the boundary consumed by the Enano Coach UI. The BFF may
obtain facts from Open Wearables (OW), but it does not expose its routes,
credentials, or internal models. The observed OW read contract is in
[`OW_READ_CONTRACT.md`](./OW_READ_CONTRACT.md).

## Initial Local Development

[FIXED] Initial development runs directly on the laptop with a local BFF and
local frontend over fixtures. The proposed frontend default is
`http://localhost:5173` and the BFF default is `http://localhost:8000`. Ports are
configurable for development and are not a production contract.

[FIXED] The browser calls only relative `/api` routes. A development-server
proxy may forward `/api` to the local BFF; the UI must not know or embed the BFF
URL, internal OW URLs, or credentials.

[PENDING] Docker, Ansible, containerization, moving to another host, and remote
deployment belong to a later phase. They are not requirements or part of the
first fixture -> BFF -> UI contract slice.

## Markers And Scope

- `[FIXED]`: implementation must respect this shape or version the contract.
- `[PROPOSED]`: recommended shape for the first adapter; requires confirmation
  before production.
- `[PENDING]`: external decision that must not be invented in the frontend.
- `[RISK]`: limitation that may produce an incomplete or ambiguous conclusion.
- `[VERIFIED]`: check executed with recent evidence and explicit scope; by itself,
  it does not turn a proposal into a production contract.

`[FIXED]` The canonical strategy for the first slice is read-only health reading
from OW; the BFF may create its own idempotent `VerificationRun` without
mutating OW health facts. The MVP allows queries for normalized facts,
provenance, coverage, and verification state. Creating a `VerificationRun` only
creates a BFF verification request; it does not start a sync or mutate OW.

## 1. Trust Boundary

```text
Browser/PWA -- session cookie, same origin --> BFF
                                                     |
                                                     +-- API key and ow_user_id server-side --> OW
```

- `[FIXED]` The browser uses only same-origin relative routes, for example
  `/api/v1/me/verify/overview`.
- `[FIXED]` The BFF resolves the session, local-to-OW link, and authorization
  before every read.
- `[FIXED]` The browser never receives or can choose an OW `user_id`.
- `[FIXED]` The OW API key, persistent OIDC tokens, internal URL, file paths,
  SQL, and raw payloads exist only server-side.
- `[FIXED]` `runKey` and `sourceKey` are opaque BFF identifiers. They must not
  encode UUIDs, emails, `user_id`, paths, or filenames. `runKey` is the only
  browser-visible run identifier; it is not an OW `batch_id`, `run_id`, or
  `manifest_id`.
- `[FIXED]` `batch_id` is an observed/internal OW name or wire field. It is not a
  public BFF-UI field, and any server-side relationship to `runKey` remains
  opaque and internal to the BFF.
- `[FIXED]` The PWA may cache only the shell and a generic offline page; it does
  not cache private responses.
- `[PENDING]` Pin the OIDC provider, exact role attributes, and session-expiry
  policy before production.

## 2. Response Wrapper

All successful and error BFF JSON responses retain this wrapper. `data` may be
`null` on an error. Do not add a second parallel format per endpoint.

```json
{
  "schemaVersion": "1",
  "asOf": "2024-01-02T12:30:00Z",
  "timezone": "UTC",
  "data": {},
  "coverage": {},
  "warnings": [],
  "extensions": {}
}
```

| Field | Type | Rule |
|---|---|---|
| `schemaVersion` | string | BFF-UI contract version, not the OW version. |
| `asOf` | RFC3339 UTC | Instant when the BFF produced the response. Not the queried logical date. |
| `timezone` | IANA timezone | Validated timezone used to build the window and present dates. |
| `data` | object/null | Data allowed for the route. Never contains credentials or internal IDs. |
| `coverage` | object | Requested scope, available days, and known limitations. Non-applicable fields are `null`. |
| `warnings` | array | Human-readable warnings and stable codes; contains no OW body or secrets. |
| `extensions` | object | Additive fields under namespaces. The UI must ignore unknown namespaces. |

### 2.1 Coverage

The minimum `coverage` structure is:

```json
{
  "requested": {
    "logicalDate": "2024-01-02",
    "from": "2024-01-02T00:00:00Z",
    "to": "2024-01-03T00:00:00Z",
    "timezone": "UTC"
  },
  "expectedDays": 1,
  "availableDays": 1,
  "isPartial": false,
  "byDomain": {
    "activity": {
      "expectedDays": 1,
      "availableDays": 1,
      "state": "complete"
    }
  }
}
```

- `[FIXED]` For `GET /api/v1/me/verify/overview` of a logical date, `expectedDays` is `1`; it is not
  `2` because a window has two boundaries.
- `[FIXED]` `availableDays` counts days with a valid observation, not rows or
  samples.
- `[FIXED]` For a non-daily query, `expectedDays` and `availableDays` may be
  `null`; do not invent coverage from the row count.
- `[FIXED]` `isPartial: true` means the observed portion is known, but the full
  requested scope was not covered.
- `[FIXED]` A complete empty response has `isPartial: false`,
  `availableDays: 0`, and UI state `empty`; it is not zero.

### 2.2 Warnings

Each warning has at least:

```json
{
  "code": "PARTIAL_COVERAGE",
  "severity": "info",
  "message": "La ventana solo tiene observaciones parciales.",
  "domain": "activity"
}
```

The minimum codes are `PARTIAL_COVERAGE`, `SOURCE_AMBIGUOUS`, `NOT_VERIFIABLE`,
`INCONCLUSIVE`, `MISMATCH`, `UNSUPPORTED`, `BODY_RELATIVE_TO_NOW`,
`CURSOR_EXPIRED`, and `UPSTREAM_LIMITED`. Text may be localized; the code is the
stable signal for tests and telemetry.

## 3. BFF Endpoints

The following routes are the only ones needed for the MVP handoff. All require a
session except `GET /api/v1/session`. They are not a generic OW proxy.

`/api/v1/me/verify/...` is the complete BFF route prefix. This contract does not
define `/verify/...` as a public BFF route or endpoint shorthand.

| Method | Route | Query/body | Result |
|---|---|---|---|
| `GET` | `/api/v1/session` | none | Session and access state without `userId`. |
| `GET` | `/api/v1/me/verify/overview` | `date=YYYY-MM-DD`, `timezone=IANA` | Aggregated daily metrics, coverage, and warnings. |
| `GET` | `/api/v1/me/verify/sources` | optional `date` and `timezone` | Sanitized sources, capabilities, and ambiguities. |
| `GET` | `/api/v1/me/verify/settings` | none | `schemaVersion`, declared capabilities, and non-sensitive technical state. |
| `GET` | `/api/v1/me/verify/runs` | `from`, `to`, `state`, `limit`, `cursor` | BFF `VerificationRun` page. |
| `POST` | `/api/v1/me/verify/runs` | creation body | Creates a verification request; does not write OW data. |
| `GET` | `/api/v1/me/verify/runs/{runKey}` | none | State and aggregated result for an own run. |

Do not implement `PATCH`, `DELETE`, `retry`, `import`, or `sync` in this slice.
`POST` is the only mutation and only records a server-side verification.

### 3.1 Session

`GET /api/v1/session` returns `200` for both anonymous and authenticated
sessions. The following is an authenticated active-session example:

```json
{
  "schemaVersion": "1",
  "asOf": "2024-01-02T12:30:00Z",
  "timezone": "UTC",
  "data": {
    "authenticated": true,
    "accessState": "active",
    "canReadVerification": true
  },
  "coverage": {},
  "warnings": [],
  "extensions": {}
}
```

`accessState` may be `anonymous`, `pending`, `active`, or `blocked`.
`role` is not required by the UI and, if sent, must not become an ownership
decision. A `pending` or `blocked` user is authenticated but has no permission
to read OW.

#### 3.1.1 Minimum Validation

[FIXED] The BFF validates before querying OW: `date` must be `YYYY-MM-DD`,
`timezone` must be a valid IANA zone, `limit` must be between `1` and `100`,
and a `cursor` must belong to the current filter and session context. For
`POST /api/v1/me/verify/runs`, `date` and `timezone` are required and `domains`
must be a non-empty list of allowed values.

- `400 INVALID_QUERY` covers invalid dates, zones, or query parameters.
- `400 INVALID_CURSOR` and `400 CURSOR_CONTEXT_MISMATCH` cover missing,
  malformed, or reused cursors with another context.
- `422 INVALID_SCOPE` covers a creation body with empty or non-allowlisted
  `domains`.
- These validations do not call OW and never accept `userId`, `owUserId`, an API
  key, a URL, or a raw payload.

### 3.2 Overview

Minimum query:

```text
GET /api/v1/me/verify/overview?date=2024-01-02&timezone=UTC
```

The BFF validates the date and IANA zone, calculates `[local midnight, next
local midnight)`, converts its boundaries to UTC, and queries OW. The response
must not silently mix sources or convert `null` to zero.

A metric value may have this shape:

```json
{
  "state": "value",
  "value": 8240,
  "unit": "count",
  "isDailyTotal": true,
  "sourceKey": "source-demo-a"
}
```

`state` is one of the data states described in section 7. A confirmed `0` uses
`state: "zero"`; a capability without a contract uses `state: "unsupported"`;
a null field retains `value: null` and
`state: "null"`.

OW `summaries/body` does not represent the selected date: its `latest` is
relative to the server `now` and `averaged` uses `average_period`. The BFF may
display it in overview only as a state relative to `asOf`, with the
`BODY_RELATIVE_TO_NOW` warning, or exclude it from a daily card. It must not
present it as a measurement for the selected day.

For sleep, `sleepDurationSeconds` represents time in intervals with the
`sleeping` stage; it is not all time in bed. The synthetic `overview_mixed` case
uses `25200` seconds and retains `recoveryScore: null` to test the `null` state
without confusing it with an empty sleep session.

### 3.3 Settings

`GET /api/v1/me/verify/settings` returns public metadata and explicit placeholders
while no exact OW pin exists:

```json
{
  "contract": "bff-ui-v1",
  "versions": {
    "bffSchema": "1",
    "owReference": "not_pinned"
  },
  "capabilities": {
    "gps": "not_verifiable",
    "workoutDetails": "aggregate_only",
    "segments": "not_verifiable",
    "hrZones": "not_verifiable"
  },
  "technicalState": "ready"
}
```

`technicalState: "ready"` only indicates that the BFF can describe the
contract; it does not assert that OW has data for every capability.

### 3.4 Sources

`GET /api/v1/me/verify/sources?date=2024-01-02&timezone=UTC` returns:

```json
{
  "items": [
    {
      "sourceKey": "source-demo-a",
      "label": "Fuente sintética A",
      "state": "ready",
      "capabilities": ["activity", "sleep"],
      "lastObservedAt": "2024-01-02T12:00:00Z"
    }
  ]
}
```

`sourceKey` is a stable alias within the BFF. Do not expose
`user_connection_id`, OW IDs, MACs, serials, routes, or filenames. If two sources
can explain the same fact and no contractual priority rule exists, the item and
the affected data use `source_ambiguous`.

Use `state: "ready"` when one permitted source exists and its provenance is
sufficient for the queried scope. `ready` does not mean that data exists, that
the capability is complete, or that the fact was verified.

### 3.5 VerificationRun Creation

`VerificationRun` is a BFF control resource. It is not an OW `SyncRun` and does
not authorize an import.

```text
POST /api/v1/me/verify/runs
Content-Type: application/json
Idempotency-Key: verify-demo-key-01
```

Minimum body:

```json
{
  "date": "2024-01-02",
  "timezone": "UTC",
  "domains": ["activity", "sleep", "recovery", "body"]
}
```

- `date` and `timezone` are required.
- `domains` is a non-empty list of `activity`, `sleep`, `recovery`, `body`,
  `workouts`, or `sources`.
- `userId`, `owUserId`, an API key, URL, path, or raw payload is not accepted.
- `[FIXED]` The BFF may resolve the same `Idempotency-Key` to an existing
  `runKey` without duplicating the request.
- `201 Created` means the BFF record was created.
- `202 Accepted` means it was accepted for processing; the initial state is
  `pending` and it does not prove that OW persisted anything.
- Both responses contain `data.verificationRun` and may include
  `Location: /api/v1/me/verify/runs/{runKey}`.

Minimum shape of `data.verificationRun`:

```json
{
  "runKey": "verify-demo-05",
  "state": "pending",
  "requestedAt": "2024-01-02T12:30:00Z",
  "startedAt": null,
  "finishedAt": null,
  "scope": {
    "date": "2024-01-02",
    "timezone": "UTC",
    "domains": ["activity", "sleep"]
  },
  "counts": {
    "recordsSeen": null,
    "recordsAccepted": null,
    "recordsRejected": null,
    "recordsDuplicated": null,
    "fieldsUnsupported": null
  },
  "warnings": []
}
```

This minimum shape is also required for `not_verifiable` and `mismatch` result
cases, and for the global `completed_with_findings` state: do not omit
`requestedAt`, `startedAt`, `finishedAt`, `scope`, `counts`, or `warnings`.
`results` is optional for runs without findings and contains only permitted
aggregated results when a check exists.

### 3.6 VerificationRun Query

List:

```text
GET /api/v1/me/verify/runs?from=2024-01-01&to=2024-01-07&state=pending&limit=25
GET /api/v1/me/verify/runs?from=2024-01-01&to=2024-01-07&limit=25&cursor=<opaque>
```

Detail:

```text
GET /api/v1/me/verify/runs/verify-demo-02
```

The detail contains only the aggregated resource, coverage, warnings, and
permitted verification results. It contains no `user_id`, OW `run_id`, filenames,
payloads, raw samples, coordinates, or OW exception messages.

## 4. BFF Pagination

The BFF page shape lives inside `data`:

```json
{
  "items": [],
  "page": {
    "nextCursor": null,
    "hasNext": false,
    "totalCount": null
  }
}
```

- `[FIXED]` `limit` is an integer between 1 and 100; default `25` for runs and
  `50` for small lists.
- `[FIXED]` `nextCursor` is opaque, short, and bound to the session, filters,
  ordering, schema version, and expiration.
- `[FIXED]` The browser forwards the cursor exactly as received; it does not
  decode, manufacture, or combine it with offsets.
- `[FIXED]` Changing `from`, `to`, `state`, `limit`, ordering, or timezone resets
  the cursor.
- `[FIXED]` `hasNext: false` is the only normal end signal. `totalCount` may be
  `null` and never closes a page by itself.
- `[FIXED]` An expired cursor or one used with another filter produces
  `410 CURSOR_EXPIRED` or `400 CURSOR_CONTEXT_MISMATCH`; the UI restarts the
  list.
- `[RISK]` The BFF must not promise stable ordering if its source has no ordering
  key. For `VerificationRun`, use descending `requestedAt` plus a stable
  internal key.

### 4.1 Relationship To OW Pagination

OW paginated data routes (`timeseries`, `summaries/*`, and some `events/*`) have
`pagination.next_cursor`, `has_more`, and sometimes `total_count`. The BFF may
consume all their pages and translate the result to its own `page.nextCursor`,
but it never passes the OW cursor to the browser.

OW `/api/v1/users/{user_id}/sync/runs` and `sync/recent` do not provide a real
cursor: they receive `limit` and return an array; they provide no `next_cursor`,
`has_more`, or stable continuation. `sync/stream` is SSE, not pagination.

- `[FIXED]` Do not call OW's `limit` a cursor or create a fake `offset` to
  simulate one.
- `[FIXED]` The `VerificationRun` list must paginate over the BFF's own record
  or an explicit snapshot with documented limits.
- `[RISK]` If only the bounded `sync/runs` array was queried, the BFF must emit
  `UPSTREAM_LIMITED` and state `not_verifiable` for a completeness assertion;
  do not display "there are no more runs."
- `[PENDING]` The server-side relationship between a `VerificationRun` and an OW
  `SyncRun` is fixed when a stable key exists. Do not expose it as the same
  resource.

## 5. OW To BFF Crosswalk

The BFF transforms OW `snake_case` names into its own `camelCase` names.
Renaming does not authorize changing semantics or units. Unlisted fields are
dropped or placed under an explicit extension; they are never copied
accidentally.

| OW | BFF | Unit/semantics |
|---|---|---|
| `timestamp` | `timestamp` | RFC3339 UTC; same instant. |
| `zone_offset` | `zoneOffset` | Source offset; does not shift the instant. |
| `type` | `type` | OW-published metric code. |
| `value` | `value` | Numeric; `null` remains `null`. |
| `unit` | `unit` | Canonical unit, not localized text. |
| `is_daily_total` | `isDailyTotal` | Boolean or `null`; never inferred from the window. |
| `provider` | `provider` | Provider name allowed by the contract. |
| `source` | `source` | OW writer/source; may be reduced to `sourceKey`. |
| `device_type` | `deviceType` | Non-sensitive label, when allowed. |
| `device_model` | `deviceModel` | Sanitized model, when allowed. |
| `software_version` | `softwareVersion` | Non-secret version, when allowed. |
| `original_source_name` | `originalSourceName` | Sanitized public name; never a path. |
| `display_name` | `displayName` | UI label, never a personal name. |
| `start_time` | `startTime` | RFC3339 UTC. |
| `end_time` | `endTime` | RFC3339 UTC. |
| `date` | `date` | Logical date `YYYY-MM-DD`, not a timestamp. |
| `steps` | `steps` | `count`, integer or `null`. |
| `distance_meters` | `distanceMeters` | Meters; the UI may format km without changing the contract. |
| `floors_climbed` | `floorsClimbed` | `count`, integer or `null`. |
| `elevation_meters` | `elevationMeters` | Meters; not a route. |
| `active_calories_kcal` | `activeCaloriesKcal` | kcal, number or `null`. |
| `total_calories_kcal` | `totalCaloriesKcal` | kcal, number or `null`. |
| `active_minutes` | `activeMinutes` | Minutes, integer or `null`. |
| `sedentary_minutes` | `sedentaryMinutes` | Minutes, integer or `null`. |
| `intensity_minutes` | `intensityMinutes` | Minutes by intensity; do not sum blindly. |
| `heart_rate` | `heartRate` | Aggregate object; its children are also camelCase. |
| `avg_bpm` | `avgBpm` | bpm; not a sum. |
| `max_bpm` | `maxBpm` | bpm; not a sum. |
| `min_bpm` | `minBpm` | bpm; not a sum. |
| `duration_minutes` | `durationMinutes` | Summary minutes. |
| `total_duration_minutes` | `totalDurationMinutes` | Minutes. |
| `time_in_bed_minutes` | `timeInBedMinutes` | Minutes. |
| `efficiency_percent` | `efficiencyPercent` | Percentage 0..100. |
| `stages` | `stages` | Object; `*_minutes` retains the unit in camelCase. |
| `sleep_stage_intervals` | `sleepStageIntervals` | Public sleep intervals; `sleeping` is not specialized. |
| `is_nap` | `isNap` | Boolean. |
| `nap_count` | `napCount` | `count`. |
| `nap_duration_minutes` | `napDurationMinutes` | Minutes. |
| `avg_heart_rate_bpm` | `avgHeartRateBpm` | bpm. |
| `avg_hrv_sdnn_ms` | `avgHrvSdnnMs` | ms. |
| `avg_hrv_rmssd_ms` | `avgHrvRmssdMs` | ms. |
| `avg_respiratory_rate` | `avgRespiratoryRate` | Breaths per minute according to OW; do not infer another unit. |
| `avg_spo2_percent` | `avgSpo2Percent` | Percentage 0..100. |
| `resting_heart_rate_bpm` | `restingHeartRateBpm` | bpm. |
| `recovery_score` | `recoveryScore` | Score 0..100 or `null`; not diagnostic. |
| `sleep_duration_seconds` | `sleepDurationSeconds` | Seconds or `null`. |
| workout `type` | `type` | Normalized type; does not promise manufacturer detail. |
| `duration_seconds` | `durationSeconds` | Seconds. |
| `calories_kcal` | `caloriesKcal` | kcal. |
| `avg_heart_rate_bpm` | `avgHeartRateBpm` | bpm. |
| `max_heart_rate_bpm` | `maxHeartRateBpm` | bpm. |
| `avg_pace_sec_per_km` | `avgPaceSecPerKm` | Seconds per km. |
| `elevation_gain_meters` | `elevationGainMeters` | Meters; does not imply a route is available. |
| `items_processed` | `itemsProcessed` | Run count, may be `null`. |
| `items_total` | `itemsTotal` | Known count, may be `null`. |
| `metadata` | not exposed as an object | `upstream_observed`; only explicitly allowlisted `BFF_sanitized` fields. Raw data is `raw_not_public`. |
| `started_at` | `startedAt` | RFC3339 UTC or `null`. |
| `ended_at` | `endedAt` | RFC3339 UTC or `null`. |
| `last_update` | `lastUpdate` | RFC3339 UTC. |
| `next_cursor` | not exposed directly | Consumed server-side and, when applicable, wrapped as `page.nextCursor`. |
| `previous_cursor` | not exposed directly | Not part of the BFF minimum. |
| `has_more` | `page.hasNext` | BFF continuation signal, not a blind copy. |
| `total_count` | `page.totalCount` | Integer or `null`; never proves completeness. |
| `user_id` | omitted | Server-side link only; never leaves the browser. |
| `user_connection_id` | omitted | Internal OW identifier. |
| `batch_id` | omitted or internal reference | Observed/internal OW wire name; never a public BFF field. The BFF uses an opaque `runKey` and does not expose or derive it from `batch_id`. |
| `run_id` | omitted or internal reference | The BFF creates an opaque `runKey` and does not visibly derive it from OW. |

Names such as `data`, `pagination`, `providers`, and other objects without a
snake_case change are retained only when the shape is allowlisted. The BFF does
not forward arbitrary OW JSON or a complete upstream `metadata` object.

### 5.1 Sync Metadata Policy

OW may expose `metadata`, `message`, and `error` with open fields. The boundary
uses these labels, which are not capability classes:

`[FIXED]` None of these open objects is a safe `public_api`. Only an allowlisted
`BFF_sanitized` output with a schema and tests may be part of the BFF contract.

| Label | Treatment |
|---|---|
| `upstream_observed` | Evidence that the observed installation may return open metadata, messages, or errors; not a public API. |
| `BFF_sanitized` | Allowlisted, aggregated, PII-free copy, codes, and counts produced by the BFF. May cross to the browser only with a schema and tests. |
| `raw_not_public` | Unsanitized upstream metadata, message, error, or payload. Prohibited in the browser and public fixtures. |

`[PENDING]` Sanitization, the allowlist, and tests preventing raw metadata leaks
must be implemented and verified before real integration.

## 6. Errors, Session, And Authorization

### 6.1 HTTP Codes

| HTTP | BFF code | UI |
|---:|---|---|
| `400` | `INVALID_QUERY`, `INVALID_CURSOR`, `CURSOR_CONTEXT_MISMATCH` | Input error or list reset; do not retry in a loop. |
| `401` | `SESSION_REQUIRED`, `SESSION_EXPIRED` | Clear ephemeral state and go to login; do not query OW. |
| `403` | `ACCESS_PENDING`, `ACCESS_BLOCKED`, `FORBIDDEN` | Show pending/blocked access; do not reveal whether another user exists. |
| `404` | `RUN_NOT_FOUND` | Missing detail or detail not belonging to the session; do not leak ownership. |
| `409` | `IDEMPOTENCY_CONFLICT` | Show a recoverable conflict and query again with the permitted key. |
| `410` | `CURSOR_EXPIRED` | Restart the first page with the current filters. |
| `422` | `INVALID_SCOPE` | Show which request field is invalid, without OW data. |
| `429` | `RATE_LIMITED` | Wait for the interval indicated by `Retry-After`, when present. |
| `502` | `UPSTREAM_INVALID` | State `error` or `inconclusive`; do not show the OW body. |
| `503` | `UPSTREAM_UNAVAILABLE` | Recoverable technical error with a manual re-query. |
| `504` | `UPSTREAM_TIMEOUT` | Recoverable technical error; do not present it as empty. |
| `500` | `INTERNAL_ERROR` | Generic technical error with an untraceable `requestId`. |

The error body adds `error` to the wrapper:

```json
{
  "schemaVersion": "1",
  "asOf": "2024-01-02T12:30:00Z",
  "timezone": "UTC",
  "data": null,
  "coverage": {},
  "warnings": [],
  "extensions": {},
  "error": {
    "code": "UPSTREAM_TIMEOUT",
    "message": "No se pudo completar la consulta.",
    "requestId": "req-demo-001",
    "retryable": true,
    "field": null
  }
}
```

`message` is safe to display only when it is BFF-generated or BFF-allowlisted
`BFF_sanitized` copy. `requestId` is a synthetic correlation identifier and does
not contain a user, encoded timestamp, path, or secret. Never include a stack
trace, headers, internal URL, API key, `user_id`, SQL, raw payload, or literal
provider message.

### 6.2 Auth Rules

- `[FIXED]` A data endpoint without a valid session responds `401`; do not turn
  it into `empty`.
- `[FIXED]` A valid session without an OW link, or with `pending` or `blocked`
  access, responds `403`; do not query OW.
- `[FIXED]` The browser uses a secure `HttpOnly` session cookie according to the
  environment; it does not receive OIDC tokens.
- `[FIXED]` `POST /api/v1/me/verify/runs` validates `Origin`/CSRF under the cookie-based
  session policy. A CSRF token, if used, is never an OW API key.
- `[FIXED]` Authorization is also checked when querying `{runKey}`; knowing a
  `runKey` does not grant access.
- `[RISK]` Do not distinguish "run does not exist" from "run belongs to another
  session" in the public message, to avoid an ownership oracle.

## 7. UI States And Normalization

### 7.1 Data States

| UI state | Source/condition | Presentation and rule |
|---|---|---|
| `loading` | Request in progress | Accessible skeleton; do not reuse another date's value. |
| `empty` | Complete response without rows/observations | "No data for this window"; never show `0`. |
| `value` | Observed and attributed value | Show value and unit. |
| `zero` | Semantically confirmed numeric `0` | Show `0` and "real zero." |
| `null` | Null field or no reading | "No measurement"; never convert to zero. |
| `partial` | Known subset or incomplete coverage | Show value, proportion, and persistent warning. |
| `unsupported` | Capability/field outside the public contract | "Not supported by this source"; do not estimate or retry continuously. |
| `pending` | Non-terminal verification or processing | "Pending"; do not assert persistence. |
| `source_ambiguous` | More than one plausible source or insufficient provenance | Visible warning; do not choose a source silently. |
| `not_verifiable` | Contract cannot prove the requested fact | "Not verifiable with the available API"; do not turn it into absence. |
| `inconclusive` | Pagination, correlation, dependency, or comparison error preventing closure | "Inconclusive result"; retain the warning and allow a later query. |
| `error` | Invalid HTTP/validation/dependency result | Generic technical error and manual re-query; do not show payload. |

`partial`, `not_verifiable`, and `inconclusive` are not synonyms: the first knows
a valid part, the second lacks a proving capability, and the third could not
close the check.

### 7.2 Source State

| State | Condition | Rule |
|---|---|---|
| `ready` | One source and sufficient provenance for the scope | Does not imply observed data or complete coverage. |
| `source_ambiguous` | Multiple plausible sources or insufficient provenance | Do not choose a source silently. |

Source state is independent of metric state and `VerificationRun` state.

### 7.3 VerificationRun States

The UI uses `persisted` only for a verification that completed successfully, not
for an accepted request.

| OW `stage` | OW `status` | UI state | Rule |
|---|---|---|---|
| `queued`, `started`, `fetching`, `processing`, `saving` | `in_progress`, `accepted`, or `null` | `pending` | The process remains open. |
| `completed` | `success` and all findings are `match` | `persisted` | Terminal result confirmed by the BFF with no findings. |
| `completed` | `success` and at least one closed `mismatch` | `completed_with_findings` | The run completed and retains the finding; it is not `inconclusive`. |
| `completed` | `success` but the requested fact is not demonstrable by the contract | `not_verifiable` | Contractual limitation, not a transport failure. |
| `completed` | `partial` | `partial` | A result exists, but records/coverage are incomplete. |
| any active stage | `failed` | `failed` | The BFF retains the failure; do not render it as empty. |
| `failed` | any state | `failed` | Terminal failure stage. |
| any stage | `cancelled` | `cancelled` | Do not assert complete persistence. |
| `completed` | `skipped` | `skipped` | Operation did not run for the scope; it may produce `unsupported` or `not_verifiable`. |
| unknown stage or state | any uncovered combination | `inconclusive` | Warning `INCONCLUSIVE`; do not infer success. |
| `completed` | `in_progress` | `inconclusive` | Upstream inconsistency; do not assert terminality. |

The names `stage` and `status` are internal to OW; the browser receives
normalized `state` and, optionally, non-sensitive labels. `[PENDING]` If an OW
version adds states, add a row and a fixture before accepting them.

`[FIXED]` The `completed + in_progress` combination always maps to
`inconclusive`, even if another signal appears terminal. A `mismatch` finding
does not by itself imply inconclusiveness: if the comparison closed, the global
state is `completed_with_findings`; `inconclusive` is reserved for a check that
could not be closed.

## 8. Verification Rules

- `[FIXED]` `match` means the expected and observed facts coincide after
  normalizing instant, unit, source, and shape.
- `[FIXED]` `mismatch` means the same logical fact exists, but its value, unit,
  timestamp, stage, or type differs beyond the declared tolerance.
- `[FIXED]` A closed `mismatch` retains the result and leaves the global
  `VerificationRun` in `completed_with_findings`; do not promote it to
  `inconclusive`.
- `[FIXED]` `stage=completed` with `status=in_progress` is inconsistent and maps
  to `inconclusive`.
- `[FIXED]` `source_ambiguous` takes precedence over `match` when the fact cannot
  be attributed to one source.
- `[FIXED]` Use `not_verifiable` for a contractual limitation, such as
  `segments` or `hrZones` without a public GET or a `sync/runs` array without
  continuation.
- `[FIXED]` Use `inconclusive` for a broken query, unconsumed page, failed
  dependency, invalid cursor, or non-unique correlation.
- `[FIXED]` Use `partial` when the observed portion and its boundaries are known;
  do not hide the warning.
- `[FIXED]` `unsupported` does not mean OW confirmed absence; it means this
  contract does not offer the capability.
- `[FIXED]` Do not sum an `isDailyTotal: true` metric twice or interpret a
  `null` metric as zero.

## 9. Crosswalk Of Errors And Special Values

| OW/BFF situation | `data`/state | Warning or error |
|---|---|---|
| Complete list without rows | `{items: []}` | No technical warning; UI `empty`. |
| Numeric sample `0` with valid semantics | `state: "zero", value: 0` | Optional `ZERO_CONFIRMED`. |
| Field present as `null` | `state: "null", value: null` | Do not convert to zero. |
| Only part of the window available | `state: "partial"` | `PARTIAL_COVERAGE`. |
| Capability not published | `state: "unsupported"` | `UNSUPPORTED`. |
| Two sources without demonstrable priority | `state: "source_ambiguous"` | `SOURCE_AMBIGUOUS`. |
| Non-terminal sync/verification | `state: "pending"` | `PENDING_PROCESSING`. |
| `segments`/`hrZones` without a public GET | `state: "not_verifiable"` | `NOT_VERIFIABLE`. |
| Page could not be consumed or correlated | `state: "inconclusive"` | `INCONCLUSIVE`. |
| OW responds outside the contract | `data: null` or affected data `error` | `UPSTREAM_INVALID`. |

## 10. Synthetic Fixtures

The contracts are tested without the internet or real OW through:

- [`ow-read-v1.json`](../fixtures/ow-read-v1.json): minimal OW responses in
  snake_case, without UUIDs, coordinates, routes, MACs, tokens, or private names.
- [`ui-verification-v1.json`](../fixtures/ui-verification-v1.json): camelCase
  BFF responses and UI state cases.

Each fixture must declare `synthetic: true`, use `verify-demo-*` for synthetic
BFF run identifiers, and not be reusable as a credential or authorization.
`runKey` and the OW `batch_id`/`run_id` remain fields of distinct resources; the
OW names are server-side observed/internal references only. The adapter may
select `case` by scenario, but the UI sees only the BFF contract.

The BFF fixture may include synthetic, non-raw server-side `adapterMappings`
metadata to test the relationship between the two resources without returning it
to the browser:

```json
{
  "adapterMappings": {
    "verificationRuns": [
      {
        "runKey": "verify-demo-01",
        "owRunId": "ow-run-demo-01",
        "owStage": "completed",
        "owStatus": "success"
      },
      {
        "runKey": "verify-demo-02",
        "owRunId": "ow-run-demo-02",
        "owStage": "completed",
        "owStatus": "partial"
      }
    ]
  }
}
```

`owRunId`, `owStage`, and `owStatus` are adapter metadata, not fields of a BFF
response. The `verify-demo-01` case retains the `success`/`match` result and
`verify-demo-02` represents the terminal `completed`/`partial` result. Do not
add raw OW `metadata`, `message`, or `error` objects to this fixture. The OW
fixture omits them; any warning, state, or count crossing to the browser must be
a `BFF_sanitized` projection generated and tested by the BFF.

### 10.1 Minimum Synthetic Contracts

| Case | Must demonstrate |
|---|---|
| `match` | Same fact, unit, and semantics; `value` state or `match` result. |
| `empty` | Complete window without rows; `availableDays: 0`, not zero. |
| `zero` | `value: 0`, `isDailyTotal: true`, `zero` state. |
| `null` | Explicitly absent reading; `value: null`, `null` state. |
| `partial` | Coverage 1 of 2 or a known subset, with a warning. |
| `unsupported` | Unpublished capability or field outside the API. |
| `ready` | One source with sufficient provenance; does not guarantee data or coverage. |
| `source_ambiguous` | Two synthetic sources without priority. |
| `pending` | `202`/active run; not `persisted`. |
| `mismatch` | Observed fact with incompatible value/unit/instant. |
| `completed_with_findings` | The mismatch closed and remains as a run finding, not an inconclusion. |
| `not_verifiable` | `segments`/`hrZones` or `sync/runs` completeness not demonstrable. |
| `inconclusive` | Expired cursor, missing page, or unavailable dependency. |
| `auth_401` / `session_required_401` / `session_anonymous_401` | Missing session on a protected endpoint; HTTP `401` and `SESSION_REQUIRED`. |
| `auth_403` / `access_pending_403` | Authenticated session without access yet; HTTP `403` and `ACCESS_PENDING`. |
| `access_blocked_403` | Blocked link or ownership; HTTP `403` and `ACCESS_BLOCKED`, without revealing account details. |
| `idempotency_conflict_409` | Recoverable idempotency conflict; HTTP `409` and `IDEMPOTENCY_CONFLICT`. |
| `rate_limited_429` | Request limit reached; HTTP `429` and `RATE_LIMITED`. |
| `internal_error_500` | Generic internal error; HTTP `500` and `INTERNAL_ERROR`, without a raw exception. |

Additional UI cases are `overview_error`, `settings_capabilities`,
`run_not_found_404`, `upstream_invalid_502`, `upstream_unavailable_503`,
`upstream_timeout_504`, `validation_400_query`, `validation_400_cursor`,
`validation_422_scope`, `session_anonymous_401`, `access_blocked_403`,
`idempotency_conflict_409`, `rate_limited_429`, and `internal_error_500`. The
mismatch fixture must use the global `completed_with_findings` state;
`completed + in_progress` must use `inconclusive`.

`[FIXED]` `ui-verification-v1.json` covers the following cases with synthetic
responses:
`session_anonymous_401`, `access_blocked_403`, `idempotency_conflict_409`,
`rate_limited_429`, and `internal_error_500`. Their codes, states, and messages
are generic and contain no raw metadata.

`[PENDING]` The remaining work is to implement and test these behaviors in the
real BFF/UI runtime, including HTTP transport, sessions, ownership, idempotency,
rate limiting, and internal-error handling.

### 10.2 OW Integration Pending Items

- `[PENDING]` Exact OW reference: reproducible release, tag, commit, or digest.
- `[PENDING]` Exact server-side auth header and mechanism per deployment; the
  observed `X-Open-Wearables-API-Key` header is not fixed and does not appear in
  fixtures.
- `[PENDING]` `resolution` is not guaranteed: accepting the parameter does not
  demonstrate that OW applies downsampling.
- `[PENDING]` Retention and historical querying of `sync/runs`, `sync/recent`, and
  `sync/stream`.
- `[PENDING]` Reproducible Gadgetbridge-OW baseline: local state is development
  evidence, and a commit/tag/release must be pinned before integration.
- `[RISK]` Any existing SQL helper or `--ow-db-url` in Gadgetbridge-OW is outside
  the normal SDK/API path and must be removed or blocked; this does not claim it
  has already disappeared.
- `[PENDING]` Sanitization and allowlist for OW metadata, messages, and errors;
  until verified, upstream is `upstream_observed` and raw data is
  `raw_not_public`.
- `[PENDING]` Workout details are not public in this contract; route, laps,
  samples, `segments`, and `hrZones` require a versioned endpoint and schema.

## 11. Acceptance Criteria

The handoff is ready to build when an implementation and its tests meet all of
the following:

- [ ] The browser calls only the BFF through relative routes and never calls OW.
- [ ] No browser request or response contains an API key, `user_id`, OIDC token,
  internal URL, raw path, coordinates, or import payload.
- [ ] Valid responses contain exactly the base fields `schemaVersion`, `asOf`,
  `timezone`, `data`, `coverage`, `warnings`, and `extensions`.
- [ ] OW fields used by the adapter are transformed to camelCase according to the
  table and retain units, `null`, and `isDailyTotal`.
- [ ] `/api/v1/me/verify/overview`, `/api/v1/me/verify/sources`,
  `/api/v1/me/verify/settings`, the run list, and run detail work with the BFF
  fixture.
- [ ] `POST /api/v1/me/verify/runs` creates only one `VerificationRun`, respects
  idempotency, and returns `pending` when asynchronous.
- [ ] `GET /api/v1/me/verify/runs/{runKey}` applies server-side ownership and never accepts
  a client-provided `user_id`.
- [ ] The list uses its own `page.nextCursor`, resets when filters change, and
  handles expiration/context mismatch.
- [ ] The implementation does not simulate a cursor for OW `sync/runs` or
  `sync/recent`; it emits `UPSTREAM_LIMITED`/`not_verifiable` when appropriate.
- [ ] The real implementation/runtime and its tests cover `401`, anonymous
  sessions, `ACCESS_BLOCKED`/`403`, `404`, `409`, `410`, `429`, `500`,
  `502/503/504`, and validation errors without leaking exceptions; corresponding
  synthetic cases are already covered by the fixture.
- [ ] Upstream metadata, `message`, and `error` are classified as
  `upstream_observed`; only allowlisted `BFF_sanitized` outputs cross to the
  browser and all raw data remains `raw_not_public`.
- [ ] The UI distinguishes `empty`, zero, `null`, `partial`, `unsupported`,
  `ready`, `pending`, `completed_with_findings`, `source_ambiguous`,
  `not_verifiable`, `inconclusive`, and `error` with accessible text.
- [ ] The OW `stage/status` table is tested with at least `pending`, `persisted`,
  `partial`, `failed`, `cancelled`, `skipped`, and an unexpected combination.
- [ ] `completed + in_progress` maps to `inconclusive` and a closed mismatch to
  `completed_with_findings`.
- [ ] The MVP shows no map or route; GPS may appear only as an unverifiable
  capability/availability until a formal contract exists.
- [ ] JSON, relative links, and handoff fences pass automatic validation.

`[PENDING]` Before connecting a real instance, pin the OW release/commit,
confirm the server-side header, validate the observed schemas, and turn cases
that remain `not_verifiable` into explicit decisions rather than frontend
assumptions.
