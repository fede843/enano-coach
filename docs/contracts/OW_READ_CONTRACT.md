# Open Wearables Read Contract

**Status:** [PROPOSED] observed read baseline for the server-side adapter.
**Document version:** `ow-read-v1`.
**Audience:** BFF, fixture adapter, and contract tests.
**Visibility:** [FIXED] public; the examples are artificial and do not describe a private installation.

This document describes only the read routes observed in the local Open
Wearables (OW) HTTP API. It is not a write contract, it does not authorize SQL
access, and it does not turn internal models into a public API. The BFF-UI that
consumes this contract is defined in [`BFF_UI_CONTRACT.md`](./BFF_UI_CONTRACT.md).
The minimum public fixture is in
[`ow-read-v1.json`](../fixtures/ow-read-v1.json).

`[FIXED]` This contract participates in the canonical strategy for the first
slice: read-only health reading from OW; the BFF may create its own idempotent
`VerificationRun` without mutating OW health facts. This document describes OW
reads only; the BFF's own `POST` is defined in the BFF-UI contract.

`[PENDING]` Before production, pin an OW release, commit, or digest and run
these tests against that version. Names not appearing in this document must not
be invented in the client.

## Markers And Boundary

- `[FIXED]`: semantics or a boundary that the BFF must respect.
- `[PROPOSED]`: adapter working shape until the OW version is pinned.
- `[PENDING]`: requires version confirmation or a formal extension.
- `[RISK]`: may prevent a complete or unambiguous conclusion.
- `[VERIFIED]`: check executed with recent evidence and explicit scope; by itself,
  it does not turn an observation into a public API.

- `[FIXED]` Only the BFF calls these routes. The browser never receives OW's
  internal URL, API key, or the `user_id` used in the path.
- `[FIXED]` `{user_id}` is resolved through server-side ownership. It is not a
  parameter the GUI can choose.
- `[RISK]` The observed installation uses `X-Open-Wearables-API-Key`; other OW
  documents may mention a different header. Verify it against the deployment pin
  and do not publish it in fixtures.
- `[FIXED]` The BFF must allow only routes and parameters in this allowlist; it
  must not act as a proxy for arbitrary URLs.

## 1. Query Conventions

### Dates And Timestamps

- `[FIXED]` The public BFF accepts `date=YYYY-MM-DD` plus an IANA timezone for
  one logical day. It represents the half-open window
  `[local midnight, next local midnight)`; these public values are not OW wire
  timestamps.
- `[FIXED]` For timeseries, the BFF sends `start_time` and `end_time` as
  RFC3339 UTC with `Z` and uses the `[start, end)` window.
- `[PROPOSED]` The current local OW fork observed by the live adapter receives
  the BFF-derived UTC bounds as RFC3339 values under `start_date` and
  `end_date` for the summary/event reads. This is development-only
  `fork_extension` evidence, not a universal OW public claim.
- `[PENDING]` Do not generalize the local fork's `start_date`/`end_date` wire
  encoding to another OW version. Confirm the parameter semantics against an
  immutable OW reference before real integration.
- `[FIXED]` `timestamp`, `start_time`, `end_time`, `started_at`, `ended_at`, and
  `last_update` are instants when they include a time; `date` is a logical date.
- `[FIXED]` `zone_offset` preserves the source offset and is not added twice to
  the UTC instant.
- `[RISK]` Sleep may group a night by the local date at the end of the session.
  Do not compare `SleepSummary.date` with a UTC timestamp as if they were the
  same field.

### 1.1 Development Date Crosswalk

`[PROPOSED]` The following crosswalk documents only the observed local fork
behavior used by `apps/bff/src/adapter/live.py`; it is classified as
`fork_extension` development evidence and is not a claim about every OW API:

| Public BFF input | BFF calculation | Local fork query values |
|---|---|---|
| `date=YYYY-MM-DD`, `timezone=IANA` | `[local midnight, next local midnight)` in the requested zone | `start_date=<start UTC RFC3339Z>` and `end_date=<end UTC RFC3339Z>` |

The BFF keeps the logical date in its public response and uses the UTC values
only at the server-side adapter boundary. The synthetic/base wrapper may omit
the optional paginated `metadata` member; a local response may include it, but
the adapter validates only the allowlisted aggregate fields (`resolution`,
`sample_count`, `start_time`, and `end_time`) and drops the object.

### Query And Cursor

- `[FIXED]` `types` is repeated for timeseries: `types=heart_rate&types=steps`;
  do not use a CSV list.
- `[FIXED]` `cursor` is opaque. The client forwards exactly
  `pagination.next_cursor` or `pagination.previous_cursor`; it does not decode
  or manufacture it.
- `[FIXED]` Continuation is determined by `pagination.has_more`, not by the row
  count or `total_count`.
- `[RISK]` `total_count` is nullable, may be absent, or may not be exact for
  summaries. `null` does not mean zero, and a number does not guarantee that one
  page is sufficient.
- `[PENDING]` The production maximum limit must be fixed by the OW version; the
  adapter uses the observed limits in the table below.

## 2. Observed Read Routes

The routes include the `/api/v1` prefix. The limits were observed in the local
version and must be checked against the production pin.

| Method | Route | Observed parameters | Shape and scope |
|---|---|---|---|
| `GET` | `/api/v1/users/{user_id}/data-sources` | none | `{items, total}`; user-source inventory, not generic pagination. |
| `GET` | `/api/v1/meta/coverage` | none | Theoretical capabilities by provider; does not prove that the user has data. |
| `GET` | `/api/v1/users/{user_id}/timeseries` | `start_time`, `end_time`, repeatable `types`, `resolution`, `cursor`, `limit` 1..100 | Paginated sample wrapper. |
| `GET` | `/api/v1/users/{user_id}/summaries/activity` | `start_date`, `end_date`, `cursor`, `limit` 1..400, `sort_order` | Prioritized daily summaries. |
| `GET` | `/api/v1/users/{user_id}/summaries/sleep` | `start_date`, `end_date`, `cursor`, `limit` 1..100 | Night/logical-date summary. |
| `GET` | `/api/v1/users/{user_id}/summaries/data` | optional `start_date`, `end_date` | Aggregate inventory without a cursor or `limit`. |
| `GET` | `/api/v1/users/{user_id}/summaries/recovery` | `start_date`, `end_date`, `cursor`, `limit` 1..100 | Daily recovery summaries. |
| `GET` | `/api/v1/users/{user_id}/summaries/body` | `average_period` 1..7, `latest_window_hours` 1..24 | `BodySummary` or `null`; no cursor and no historical window. |
| `GET` | `/api/v1/users/{user_id}/events/workouts` | `start_date`, `end_date`, `record_type`, `cursor`, `limit` 1..100 | Public workout summary. |
| `GET` | `/api/v1/users/{user_id}/events/sleep` | `start_date`, `end_date`, `filter_by_priority`, `cursor`, `limit` 1..100 | Sleep and nap sessions; `filter_by_priority` defaults to `false`. |
| `GET` | `/api/v1/users/{user_id}/sync/runs` | `limit` 1..200 | Array of `SyncRunSummary`; no real cursor. |
| `GET` | `/api/v1/users/{user_id}/sync/recent` | `limit` 1..200 | Array of `SyncStatusEvent`; no real cursor. |
| `GET` | `/api/v1/users/{user_id}/sync/stream` | `replay` 1..200 | SSE `text/event-stream`; no pagination. |

Global administrative listing routes and nested routes for workout detail,
route, laps, samples, `segments`, or `hrZones` are not included. `[FIXED]` These
capabilities are not public endpoints in this contract. If a future version
publishes them, they must enter through a formally documented version and schema.

## 3. OW Wrappers

### 3.1 Paginated Response

Timeseries, paginated summaries, and paginated events use an equivalent shape:

```json
{
  "data": [],
  "pagination": {
    "next_cursor": null,
    "previous_cursor": null,
    "has_more": false,
    "total_count": null
  }
}
```

- `data` is the route's collection.
- `pagination.next_cursor` and `previous_cursor` may be `null`.
- `has_more` signals that the client must request another page.
- `total_count` is `integer | null` and may be unavailable; do not use it to
  declare completeness.
- `metadata` is optional at the adapter boundary. The synthetic/base fixture
  omits it; when the observed local fork returns it, the adapter validates only
  the allowlisted aggregate fields and never forwards the raw object.
- OW may include additional `upstream_observed` wrappers with open fields. They
  are not reproduced in this example or the public fixture.
- The publishable representation is created later in the BFF and may contain
  only allowlisted fields, for example:

```json
{
  "state": "completed",
  "progress": 1,
  "counts": {
    "recordsSaved": 8,
    "recordsRejected": 0
  },
  "warningCodes": []
}
```

This object is a `BFF_sanitized` projection, not a claim that OW already
sanitizes its response. Sanitization and its tests belong to the BFF.

### 3.1.1 Sync Metadata And Messages

OW may expose `metadata`, `message`, and `error` with open shapes. The three
flow labels are mandatory:

`[FIXED]` None of these open objects is classified as a safe `public_api`; a
verifiable `BFF_sanitized` output must exist first.

| Label | Meaning | Rule |
|---|---|---|
| `upstream_observed` | Shape observed in local OW; it may change and is not a public contract. | Serves as server-side adapter evidence. |
| `BFF_sanitized` | Allowlisted, aggregated, PII-free subset produced by the BFF. | May appear in the BFF contract only after sanitization and tests. |
| `raw_not_public` | Unfiltered metadata, messages, errors, or raw payloads. | Never pass to the browser or appear in public fixtures. |

`[PENDING]` The allowlist, message/error sanitization, and test rejecting raw
keys must be verified against a reproducible reference.

`data-sources` uses `{items, total}` without `pagination`; `summaries/data`
returns an inventory object; `summaries/body` returns an object or `null`; and
the `sync/runs`/`sync/recent` endpoints return bounded arrays. Do not normalize
these shapes as if they all had cursors.

### 3.2 Timeseries

Minimum server-side query:

```text
GET /api/v1/users/{ow_user_id}/timeseries
  ?start_time=2024-01-02T00:00:00Z
  &end_time=2024-01-03T00:00:00Z
  &types=heart_rate
  &types=steps
  &resolution=raw
  &limit=100
```

`resolution` accepts `raw`, `1min`, `5min`, `15min`, and `1hour` in the observed
signature. `[RISK]` The local implementation may receive the parameter without
applying it to the query service. The BFF must not advertise downsampling unless
it demonstrates it or performs it explicitly.

### 3.3 Summaries

- `activity` returns `date`, source, steps, distance, calories, minutes,
  elevation, intensity, and HR statistics when available.
- `sleep` returns the main night, sessions, duration, efficiency, stages, naps,
  and physiological averages when available.
- `data` returns an aggregate count inventory by type/provider; it does not
  replace a sample query and does not use `pagination`.
- `recovery` returns the available score and daily components; missing is `null`,
  not zero.
- `body` separates `slow_changing`, `averaged`, and `latest`; it is not a
  historical series.

`events/sleep` may include `duration_seconds`, `sleep_duration_seconds`, and
`sleep_stage_intervals`. The generic `sleeping` stage is preserved as such; do
not invent specific stages.

In the public fixture, the session from `2024-01-01T22:30:00Z` to
`2024-01-02T06:30:00Z` contains 15 minutes of `in_bed`, 420 minutes of
`sleeping`, and 45 minutes of `awake`. Therefore `duration_seconds` is `28800`,
`sleep_duration_seconds` is `25200`, and the summary retains
`duration_minutes` and `total_duration_minutes` as `420`. The corresponding BFF
name is `sleepDurationSeconds`; it represents the `sleeping` interval, not all
time in bed.

### 3.4 Body: Relative To `now`

`GET /summaries/body` does not receive `start_date` or `end_date`.

- `slow_changing` contains slow-changing values.
- `averaged` uses `average_period` and returns its own period when OW reports it.
- `latest` looks for recent readings in `latest_window_hours` relative to the OW
  server or query `now`.
- `[FIXED]` The body summary is relative to `now`, not the day selected by the
  user in the UI.
- `[FIXED]` If the BFF displays it next to a logical day, it must label it
  "relative to query" and emit `BODY_RELATIVE_TO_NOW`; do not call it a
  "measurement for the day."
- `[FIXED]` A trend or historical date requires timeseries or another public
  route with a time window. Do not invent body filters that OW does not declare.

### 3.5 Recovery

`RecoverySummary` may include `date`, `source`,
`sleep_duration_seconds`, `sleep_efficiency_percent`,
`resting_heart_rate_bpm`, `avg_hrv_sdnn_ms`, `avg_spo2_percent`, and
`recovery_score`. Fields may individually be `null`.

- Durations: seconds.
- Efficiency and SpO2: percentage 0..100.
- HR: bpm.
- HRV: ms.
- Recovery score: integer 0..100 when OW publishes it; not diagnostic.

`[FIXED]` A missing `recovery_score` is not equivalent to `0`; a score of `0` is
zero only when OW returns it explicitly.

### 3.6 Events

`events/workouts` returns only the public workout summary and its available
aggregate metrics. `events/sleep` returns complete sleep/nap sessions and their
stage intervals when stored.

`filter_by_priority=true` requests the highest-priority source for a sleep date;
`false` allows the sources returned by OW to be viewed. Do not assume that
priority resolves all provenance ambiguity in other domains.

## 4. OW -> BFF Crosswalk

The BFF exposes its own camelCase, not a copy of OW JSON. An unlisted field is
dropped or added through a versioned extension. `user_id` and other internal IDs
are never returned to the browser.

### 4.1 Wrapper, Pagination, And Metadata

| OW snake_case | BFF camelCase | Rule |
|---|---|---|
| `next_cursor` | `page.nextCursor` | The BFF wraps it; the public value must not be the OW cursor. |
| `previous_cursor` | not exposed | The BFF minimum only needs forward continuation. |
| `has_more` | `page.hasNext` | Only after validating that the source allows continuation. |
| `total_count` | `page.totalCount` | Integer or `null`; does not prove completeness. |
| `sample_count` | `sampleCount` | `BFF_sanitized` candidate: row count, not days; requires an allowlist and test. |
| `start_time` in metadata | `startTime` | `BFF_sanitized` candidate: RFC3339 UTC; does not copy raw metadata. |
| `end_time` in metadata | `endTime` | `BFF_sanitized` candidate: RFC3339 UTC; does not copy raw metadata. |
| `resolution` | `resolution` | `BFF_sanitized` candidate: advertises only the resolution actually applied. |
| `schema_version` if present | `schemaVersion` | BFF schema version; not copied without validation. |
| `data` | `data` | Only the endpoint's allowlisted shape. |
| `metadata` | not forwarded as an object | `upstream_observed`; only explicitly allowlisted `BFF_sanitized` subfields. The raw object is `raw_not_public`. |

### 4.2 SourceMetadata And DataSource

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `provider` | `provider` | Integration code; do not assume the device name. |
| `source` | `source` or `sourceKey` | Writer/source; `sourceKey` may be an opaque BFF alias. |
| `device` | `device` | Model label when allowed. |
| `device_type` | `deviceType` | `watch`, `band`, `phone`, `scale`, `ring`, `other`, or `unknown`. |
| `device_name` | `deviceName` | Non-sensitive derived name; may be omitted. |
| `id` of data source | omitted or `sourceKey` | The OW ID does not leave the BFF. |
| `user_id` | omitted | Server-side ownership. |
| `user_connection_id` | omitted | Internal connection ID. |
| `device_model` | `deviceModel` | Sanitized label, not a serial/MAC. |
| `software_version` | `softwareVersion` | Non-secret version. |
| `original_source_name` | `originalSourceName` | Only if it is not a path or private name. |
| `display_name` | `displayName` | Sanitized label. |

### 4.3 TimeSeriesSample, Flags, And Units

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `timestamp` | `timestamp` | RFC3339 UTC; same instant. |
| `zone_offset` | `zoneOffset` | Original offset, string or `null`. |
| `type` | `type` | Published metric code. |
| `value` | `value` | Number; `null` remains `null` when allowed by the schema. |
| `unit` | `unit` | Canonical unit. |
| `is_daily_total` | `isDailyTotal` | Boolean or `null`; per-sample flag, not a query parameter. |

Common canonical units:

| Types OW | Unit OW/BFF |
|---|---|
| `heart_rate`, `resting_heart_rate` | `bpm` |
| `heart_rate_variability_sdnn`, `heart_rate_variability_rmssd` | `ms` |
| `oxygen_saturation`, `body_fat_percentage` | `percent` |
| `steps`, `flights_climbed`, `swimming_stroke_count` | `count` |
| `energy`, `basal_energy` | `kcal` |
| `distance_*`, `six_minute_walk_test_distance` | `meters` |
| `elevation`, `underwater_depth` | `meters` |
| `latitude`, `longitude` | `degrees` |
| `weight`, `lean_body_mass`, `body_fat_mass` | `kg` |
| `height`, `walking_step_length` | `cm` |
| `body_temperature`, `skin_temperature` | `celsius` |
| `speed`, `running_speed`, `walking_speed` | `m_per_s` |
| `cadence` | `rpm` |
| `power`, `running_power` | `watts` |

The BFF may format meters as km in UI text, but the data contract retains
`distanceMeters`. Do not convert based on the field name when `unit` does not
match.

### 4.4 ActivitySummary

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `date` | `date` | Logical date. |
| `source` | `source` | Sanitized SourceMetadata object. |
| `steps` | `steps` | `count`, integer or `null`. |
| `distance_meters` | `distanceMeters` | Meters. |
| `floors_climbed` | `floorsClimbed` | `count`. |
| `elevation_meters` | `elevationMeters` | Meters. |
| `active_calories_kcal` | `activeCaloriesKcal` | kcal. |
| `total_calories_kcal` | `totalCaloriesKcal` | kcal. |
| `active_minutes` | `activeMinutes` | Minutes. |
| `sedentary_minutes` | `sedentaryMinutes` | Minutes. |
| `intensity_minutes` | `intensityMinutes` | `light`, `moderate`, and `vigorous` children, in minutes. |
| `heart_rate` | `heartRate` | `avgBpm`, `maxBpm`, and `minBpm` children; bpm, not a sum. |

### 4.5 SleepSummary, SleepSession, And Stages

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `date` | `date` | OW logical date. |
| `start_time` | `startTime` | RFC3339 UTC or `null` in the summary. |
| `end_time` | `endTime` | RFC3339 UTC or `null` in the summary. |
| `duration_minutes` | `durationMinutes` | Minutes. |
| `total_duration_minutes` | `totalDurationMinutes` | Minutes. |
| `time_in_bed_minutes` | `timeInBedMinutes` | Minutes. |
| `efficiency_percent` | `efficiencyPercent` | Percentage 0..100. |
| `stages` | `stages` | `awakeMinutes`, `lightMinutes`, `deepMinutes`, and `remMinutes` children. |
| `sessions` | `sessions` | Session-summary list. |
| `nap_count` | `napCount` | `count`. |
| `nap_duration_minutes` | `napDurationMinutes` | Minutes. |
| `avg_heart_rate_bpm` | `avgHeartRateBpm` | bpm. |
| `avg_hrv_sdnn_ms` | `avgHrvSdnnMs` | ms. |
| `avg_hrv_rmssd_ms` | `avgHrvRmssdMs` | ms. |
| `avg_respiratory_rate` | `avgRespiratoryRate` | Breaths/minute according to OW. |
| `avg_spo2_percent` | `avgSpo2Percent` | Percentage 0..100. |
| `id` of sleep event | not exposed or `sleepKey` | Opaque BFF alias; do not require UUID format. |
| `duration_seconds` | `durationSeconds` | Seconds. |
| `sleep_duration_seconds` | `sleepDurationSeconds` | Seconds or `null`. |
| `is_nap` | `isNap` | Boolean. |
| `sleep_stage_intervals` | `sleepStageIntervals` | Intervals when published by OW. |
| `stage` | `stage` | `in_bed`, `awake`, `sleeping`, `light`, `deep`, `rem`, `unknown`. |

`sleeping` is a generic stage. `[FIXED]` It cannot be reinterpreted as `light`,
`deep`, or `rem` merely to complete a chart.

### 4.6 RecoverySummary

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `date` | `date` | Logical date when included in the response. |
| `source` | `source` | Sanitized SourceMetadata. |
| `sleep_duration_seconds` | `sleepDurationSeconds` | Seconds or `null`. |
| `sleep_efficiency_percent` | `sleepEfficiencyPercent` | Percentage or `null`. |
| `resting_heart_rate_bpm` | `restingHeartRateBpm` | bpm or `null`. |
| `avg_hrv_sdnn_ms` | `avgHrvSdnnMs` | ms or `null`. |
| `avg_spo2_percent` | `avgSpo2Percent` | Percentage or `null`. |
| `recovery_score` | `recoveryScore` | 0..100 or `null`; not diagnostic. |

### 4.7 BodySummary

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `slow_changing` | `slowChanging` | Query-relative group. |
| `weight_kg` | `weightKg` | kg. |
| `height_cm` | `heightCm` | cm. |
| `body_fat_percent` | `bodyFatPercent` | Percentage. |
| `muscle_mass_kg` | `muscleMassKg` | kg. |
| `bmi` | `bmi` | Number without an additional unit. |
| `age` | `age` | Only when declared and allowed. |
| `averaged` | `averaged` | Group calculated with `averagePeriod`. |
| `period_days` | `periodDays` | Average period in days. |
| `resting_heart_rate_bpm` | `restingHeartRateBpm` | bpm. |
| `avg_hrv_sdnn_ms` | `avgHrvSdnnMs` | ms. |
| `avg_hrv_rmssd_ms` | `avgHrvRmssdMs` | ms. |
| `period_start` | `periodStart` | RFC3339 when returned by OW. |
| `period_end` | `periodEnd` | RFC3339 when returned by OW. |
| `latest` | `latest` | Window relative to `now`, not the selected date. |
| `body_temperature_celsius` | `bodyTemperatureCelsius` | Celsius. |
| `body_temperature_measured_at` | `bodyTemperatureMeasuredAt` | RFC3339. |
| `skin_temperature_celsius` | `skinTemperatureCelsius` | Celsius. |
| `skin_temperature_measured_at` | `skinTemperatureMeasuredAt` | RFC3339. |
| `blood_pressure` | `bloodPressure` | mmHg and `readingCount` only when declared by OW. |
| `blood_pressure_measured_at` | `bloodPressureMeasuredAt` | RFC3339. |

The complete `BodySummary` may be `null`. A present group with null fields is
not equivalent to an absent group.

### 4.8 Public Workout

`events/workouts` allows only the following summary, with optional fields:

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `id` | `workoutKey` | Opaque BFF alias; the OW ID format is not published. |
| `type` | `type` | Normalized type. |
| `name` | `name` | String or `null`; may be omitted for privacy. |
| `start_time` | `startTime` | RFC3339 UTC. |
| `end_time` | `endTime` | RFC3339 UTC. |
| `duration_seconds` | `durationSeconds` | Seconds or `null`. |
| `zone_offset` | `zoneOffset` | Original offset. |
| `calories_kcal` | `caloriesKcal` | kcal or `null`. |
| `distance_meters` | `distanceMeters` | Meters or `null`. |
| `avg_heart_rate_bpm` | `avgHeartRateBpm` | bpm or `null`. |
| `max_heart_rate_bpm` | `maxHeartRateBpm` | bpm or `null`. |
| `avg_pace_sec_per_km` | `avgPaceSecPerKm` | Seconds/km or `null`. |
| `elevation_gain_meters` | `elevationGainMeters` | Meters or `null`. |

Do not infer `segments`, `hrZones`, laps, samples, or a route from the fields
above.

### 4.9 UserDataSummary

| OW snake_case | BFF camelCase | Unit/rule |
|---|---|---|
| `total_data_points` | `totalDataPoints` | Inventory count. |
| `total_workouts` | `totalWorkouts` | Count. |
| `total_sleep_events` | `totalSleepEvents` | Count. |
| `series_type_counts` | `seriesTypeCounts` | Type-to-count map. |
| `workout_type_counts` | `workoutTypeCounts` | Type-to-count map. |
| `by_provider` | `byProvider` | Aggregate by provider. |
| `data_points` | `dataPoints` | Count. |
| `series_counts` | `seriesCounts` | Count map. |
| `workout_count` | `workoutCount` | Count. |
| `sleep_count` | `sleepCount` | Count. |
| `has_womens_health_data` | `hasWomensHealthData` | Boolean, only if needed by the UI. |
| `user_id` | omitted | Does not leave the BFF. |

### 4.10 SyncRun And SyncStatusEvent

| OW snake_case | BFF camelCase or rule |
|---|---|
| `batch_id` | Observed/internal OW wire field; omitted from the public BFF contract and never exposed as `runKey`. |
| `run_id` | Internal `sourceRunKey`; not the public `runKey`. |
| `user_id` | omitted. |
| `provider` | `provider`. |
| `source` | `source`. |
| `stage` | Internal `sourceStage`; the BFF publishes normalized `state`. |
| `status` | Internal `sourceStatus`; the BFF publishes normalized `state`. |
| `message` | Not copied; only warnings with `BFF_sanitized` copy; `upstream_observed`, never a literal raw message. |
| `progress` | `progress`, 0..1 or `null`. |
| `items_processed` | `itemsProcessed`, integer or `null`. |
| `items_total` | `itemsTotal`, integer or `null`. |
| `error` | `BFF_sanitized` `errorSummary` or `null`; only an allowlisted code/summary, never a literal exception or raw body. |
| `metadata` | `BFF_sanitized` `counts` or omitted; the upstream object is `upstream_observed`; raw `metadata` is `raw_not_public`. |
| `started_at` | `startedAt`. |
| `ended_at` | `endedAt`. |
| `last_update` | `lastUpdate`. |
| `event_id` | `eventKey` opaque internal. |
| `timestamp` | `timestamp`. |
| `primary_user_id` | omitted. |

Observed stages: `queued`, `started`, `fetching`, `processing`, `saving`,
`completed`, `failed`, `cancelled`. Observed statuses:
`in_progress`, `success`, `partial`, `failed`, `cancelled`, `skipped`.
The mapping to UI states is fixed in
[`BFF_UI_CONTRACT.md`](./BFF_UI_CONTRACT.md).

## 5. What Is And Is Not Sufficient

### 5.1 API Sufficient For The Map-Free MVP

| Fact | Routes | Result |
|---|---|---|
| Declared source and provider | `data-sources` | Verifiable as a source inventory. |
| Theoretical capability | `meta/coverage` | Verifiable as a capability, not as user data. |
| Intraday metric and unit | `timeseries` consuming every page | Verifiable when `has_more` closes and the source is unambiguous. |
| Prioritized daily total | `summaries/activity` | Verifiable as an OW aggregate; do not sum timeseries again. |
| Published night, nap, and stages | `summaries/sleep`, `events/sleep` | Verifiable according to the shape returned by OW. |
| Daily recovery | `summaries/recovery` | Verifiable as published fields; preserve nulls. |
| Current/relative body data | `summaries/body` | Verifiable as a view relative to `now`, not as a historical date. |
| Aggregated workout | `events/workouts` | Verifiable only for fields present in the summary. |
| Sync state | `sync/runs`, `sync/recent`, SSE | Confirms a result only when terminal and consistent. |

### 5.2 Not Public Or Not Demonstrable

| Fact | Limitation |
|---|---|
| Public detail by `workout_id` | No public GET route is documented in this contract. |
| `segments` | No public, versioned GET schema. State: `unsupported`/`not_verifiable`. |
| `hrZones` | No public, versioned GET schema. State: `unsupported`/`not_verifiable`. |
| Route unambiguously associated with a workout | `latitude`, `longitude`, and `elevation` may be generic series when declared by coverage, but `TimeSeriesSample` does not include `workout_id`. Window association is not sufficient proof. |
| Laps, workout samples, or manufacturer metrics | Not promised without public endpoints and schemas. |
| Parser, raw file, original payload, or individual rejects | Not exposed by these reads. |
| Completeness of `sync/runs` | The endpoint accepts only `limit`; it has no real cursor or `has_more`. |
| Applied `resolution=5min` | The parameter may be accepted without effective downsampling. |

`[FIXED]` The MVP does not draw maps or routes. GPS-series availability may be
shown in settings/capabilities as availability that is insufficient to build a
route. The GPS/route phase needs a formal contract resolving workout-point
association, privacy, downsampling, and pagination.

## 6. Sync And Pagination Without A Cursor

An observed SSE stream may contain status events, but its raw payload is not
reproduced in public documentation or fixtures. The shape the BFF may deliver
after its allowlist is conceptual:

```text
event: sync.status
data: {"state":"completed","progress":1,"warningCodes":[]}
```

This projection is `BFF_sanitized`; it does not claim that OW already sanitizes
the frame.

`: connected` and `: heartbeat` may also appear. The BFF may read `recent` or
replay, deduplicate server-side, and convert the result to the state of its own
`VerificationRun`.

- `[FIXED]` `stage=completed` and `status=success` allow a successful completion
  of the observed sync to be asserted.
- `[FIXED]` `stage=completed` and `status=in_progress` is an inconsistent
  combination mapped to `inconclusive`; it does not establish completion.
- `[FIXED]` `queued`, `in_progress`, `202 Accepted`, or an SSE without a terminal
  event means only accepted/in progress.
- `[FIXED]` `partial`, `failed`, `cancelled`, and `skipped` are terminal process
  states, but are not equivalent to complete persistence.
- `[RISK]` `sync/recent` may depend on short event retention. A historical
  absence does not prove that a run never existed or that no data was persisted.
- `[FIXED]` `sync/runs` and `sync/recent` have no real cursor. The BFF must not
  invent `nextCursor` from `limit`.

If the BFF needs to paginate verification history, it must do so over its own
`VerificationRun` record, as defined by the BFF contract. If it has only OW's
bounded array, it must mark the conclusion `not_verifiable` and emit
`UPSTREAM_LIMITED`.

## 7. Flags And Data Semantics

### `is_daily_total`

- `[FIXED]` `true` means the sample is already a provider-aggregated daily total.
- `false` means the sample is not marked as a daily total.
- `null` means unknown/legacy semantics, not zero or a confirmed total.
- Do not send `is_daily_total` as a query parameter: it is a response flag.
- For steps, energy, distance, floors, and active time, prefer the daily total
  for the same date/source/type; sum non-daily samples only when the aggregation
  contract permits it.
- HR, HRV, and SpO2 are not summed; use an appropriate statistic or aggregate.
- `[RISK]` Mixing a daily total with intraday samples duplicates figures.

### Missing, `null`, And Zero

- No row after consuming every page: absence/`empty`.
- Row with `value: null`: `null`/no measurement.
- Row with numeric value `0`: real zero only when the metric and its semantics
  are valid.
- Capability absent from `meta/coverage`: `unsupported`; it does not prove the
  absence of all data in OW.

### Source And Priority

`provider` identifies the integration; `source` identifies a writer/source and
they are not necessarily synonyms. Do not merge providers or sources merely
because they share a timestamp. If OW priority does not resolve fact
attribution, the BFF uses `source_ambiguous`.

`ready` is a BFF-derived state, not an additional OW assertion: use it only when
a single permitted source explains the scope and its provenance is sufficient.
A source inventory alone does not prove that data exists or that a capability is
complete.

## 8. Comparison And Results

The comparison uses a scope key containing the server-side user, UTC window,
provider/source, type, and event when present. Never compare by timestamp alone.

| Result | Meaning |
|---|---|
| `match` | Expected and observed facts match after explicit normalization. |
| `missing` | Public capability and expected data exist and all pages were consumed, but the data does not appear. |
| `unexpected` | Data outside the expected set in a scope that could be closed. |
| `mismatch` | Logical fact is present but differs in value, unit, timestamp, stage, or type. |
| `unsupported` | The public API does not provide the field/capability. |
| `not_verifiable` | The API cannot prove the assertion, for example an associated route or `segments`/`hrZones`. |
| `inconclusive` | The result could not be closed because of an error, missing page, ambiguous source, cursor, or non-unique correlation. |

Minimum normalization:

1. Convert timestamps to the same UTC instant.
2. Convert only documented units and retain the canonical unit.
3. Compare integers exactly and use an explicit per-metric tolerance for floats.
4. Do not depend on page order.
5. Compare sleep by stage and interval; generic `sleeping` is not equivalent to
   specific stages.
6. Treat a route as `inconclusive` when the timestamp does not identify one
   unique workout.

## 9. Contract Limits

- `[PENDING]` Exact OW reference (release, tag, commit, or digest) and schema
  generated from that version.
- `[PENDING]` Authentication policy and exact header for each deployment. The
  observed `X-Open-Wearables-API-Key` header is not fixed, and no credential
  value enters fixtures.
- `[PENDING]` Effective `resolution` semantics; accepting `raw`, `1min`, `5min`,
  `15min`, or `1hour` does not guarantee that OW applies downsampling.
- `[PENDING]` Retention and historical querying of `sync/runs`, `sync/recent`,
  and `sync/stream`.
- `[PENDING]` Reproducible Gadgetbridge-OW baseline: local state is only
  development evidence, and a commit/tag/release must be pinned before
  integration.
- `[RISK]` Any SQL helper or `--ow-db-url` in the importer is outside the normal
  SDK/API path and must be removed or blocked; this contract does not claim it
  has already disappeared.
- `[PENDING]` Versioned endpoint and schema for workout detail, route, laps,
  samples, `segments`, and `hrZones`, if they are included; workout detail is
  not public in this contract.
- `[PENDING]` Sanitization and allowlist for sync `metadata`, `message`, and
  `error`; until verified, only `upstream_observed` is recognized and all raw
  data is `raw_not_public`.
- `[RISK]` Do not elevate a field accepted by the importer or stored internally
  to a public capability without a GET route, schema, authorization, and tests.
- `[RISK]` Do not use nullable `total_count` to close a reconciliation.

## 10. Public Fixture

`ow-read-v1.json` is a small set of synthetic responses, not a snapshot of a
person or installation. It must contain only:

- Readable IDs such as `user-demo-01`, `source-demo-a`, and `ow-run-demo-01`;
  synthetic OW `run_id` values use `ow-run-demo-*`. An observed OW `batch_id`,
  when represented, remains an internal/wire field. BFF `runKey` values use the
  separate `verify-demo-*` namespace and remain opaque to the browser.
- Artificial values and test dates.
- Activity, sleep, recovery, and body aggregates.
- Examples of `summaries/data`, `events/sleep`, and `sync/stream` with synthetic
  shapes.
- Enough non-sensitive samples to test units, flags, `null`, zero, and
  pagination.
- Samples with `is_daily_total: null` and `value: null` to distinguish unknown
  semantics from an absent value.
- Synthetic runs and events with terminal/non-terminal states.
- Cases `match`, `empty`, `zero`, `null`, `partial`, `unsupported`, `ready`,
  `source_ambiguous`, `pending`, `mismatch`, and `inconclusive`.

`[FIXED]` The OW fixture uses synthetic values and allowlisted fields for the
server-side adapter; it is not a raw export. Its paginated wrappers omit the
optional `metadata` member and do not add sync `metadata`, `message`, or
`error`. The live adapter accepts a local response with `metadata`, validates
only the allowlisted aggregate fields, and drops the object; raw metadata
remains `raw_not_public`. The `public_sync_projection` section documents a
`BFF_sanitized` output whose implementation status remains `[PENDING]`;
sanitization belongs to the BFF. The BFF/UI fixture contains only
`BFF_sanitized` outputs and never `raw_not_public` data.

It must not contain realistic UUIDs, MACs, coordinates, routes, tokens, API
keys, hashes, file paths, emails, or private data. It does not include routes,
GeoJSON, `segments`, or `hrZones`; those cases are represented as
`unsupported`/`not_verifiable`.

`[FIXED]` The fixture is an adapter contract, not authorization: no synthetic ID
or value may be used to select a real user.
