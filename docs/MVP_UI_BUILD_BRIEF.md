# Verification UI MVP

**Status:** [PROPOSED] actionable brief for a first build session with synthetic fixtures.
**Audience:** frontend and BFF agents, test agents, and people resuming the MVP after a pause.
**Visibility:** [FIXED] public; this document and all its examples must be publishable without operator data.

This brief specifies a small session derived from the [project master plan](./PROJECT_PLAN.md). The master plan remains authoritative for overall architecture and security. The observed Open Wearables read contract is in [`OW_READ_CONTRACT.md`](./contracts/OW_READ_CONTRACT.md), and the boundary consumed by the UI is in [`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md). Both documents separate what can be built with fixtures from what remains pending in OW.

All example values, dates, source names, identifiers, and states are synthetic. Do not include real data, UUIDs, MACs, coordinates, personal routes, secrets, raw payloads, or file paths.

The allowed document status markers are `[FIXED]`, `[PROPOSED]`, `[PENDING]`,
`[RISK]`, and `[VERIFIED]`. `[VERIFIED]` means that a concrete check was executed
with recent evidence and explicit scope; it does not turn a proposal into a
production contract.

## 1. Purpose And Limits

### 1.1 Objective

[FIXED] Build a responsive PWA that acts as a verification console for the chain:

```text
fixture sintético -> BFF -> modelo de vista -> UI
```

The canonical strategy for the first slice is read-only health reading from OW;
the BFF may create its own idempotent `VerificationRun` without mutating OW
health facts. The console must allow aggregated inspection of the reads and that
control record:

- Which daily data OW exposes for a logical date.
- Which coverage and warnings accompany that data.
- Which sources and capabilities the contract declares.
- Which import or processing runs exist and their terminal state.
- Which aggregated information the detail of an own `VerificationRun` contains.

[FIXED] The screen must make provenance, coverage, and missing data visible
without turning absence into zero.

### 1.3 Local Development On The Laptop

[FIXED] The first slice is built directly on the laptop with the frontend and
BFF as local processes. Docker, Ansible, containerization, and remote deployment
are not used for these iterations. Those tasks belong to a later phase outside
this initial implementation brief.

[PROPOSED] Local defaults are `http://localhost:5173` for the frontend and
`http://localhost:8000` for the BFF. Ports are configurable and are not a
production contract. The UI calls only relative `/api`; the development-server
proxy forwards those routes to the BFF without exposing internal URLs to React.

### 1.2 What It Is Not

`[FIXED]` This first UI is not a coaching application. It must not include:

- Training, rest, nutrition, or health recommendations.
- Goals, streaks, scores, gamification, or prescriptive language.
- Diagnosis, medical interpretation, or clinical alerts.
- Editing, deletion, import, retry, or mutation of health facts.
- Direct queries to OW, PostgreSQL, or an exported file.
- Rendering coordinates, maps, personal routes, or raw samples.
- Comparison of workouts or periods.

[RISK] A verification-console appearance may look like an operations dashboard.
Copy, actions, and permissions must make clear that it only observes results and
allows a new query.

### 1.4 Map-Free MVP And Later GPS Phase

[FIXED] The MVP in this brief does not draw maps, routes, or GPS points. Workout
detail is limited to the aggregates OW currently publishes; `segments`, `hrZones`,
and an unambiguous relationship between a workout and a timeseries are not part
of this delivery. The OW contract explains the limitation in
[`OW_READ_CONTRACT.md`](./contracts/OW_READ_CONTRACT.md).

[PROPOSED] If a source declares GPS capability, the UI may show it in
`/verify/sources` or `/verify/settings` as availability (`available`,
`unsupported`, or `not_verifiable`). That label does not
authorize requesting, storing, or rendering coordinates, GeoJSON, GPX, or a
route.

[PENDING] The later GPS/route phase needs a formal contract for `workoutKey`
association, privacy, precision, downsampling, and pagination. Do not implement
that contract during the verification slice.

## 2. First-Slice Objective

[PROPOSED] Deliver a vertical slice across all layers with a mixed synthetic fixture:

1. Load the React/Vite shell and responsive navigation.
2. Obtain a summary from the BFF for a synthetic date and timezone.
3. Show the summary at `/verify`, including a value, a real zero, a `null`,
   partial coverage, and an unsupported metric.
4. Navigate to `/verify/sources` and show one unambiguous (`ready`) source and
   one ambiguous source.
5. Navigate to `/verify/runs`, load the first page, and obtain the next page
   through the BFF's own opaque cursor.
6. Create a synthetic `VerificationRun`, query `/verify/runs/:runKey`, and show
   its state and aggregated counts.
7. Open `/verify/settings` and show contract metadata and capabilities without
   sensitive values.
8. Run the Playwright acceptance matrix against the BFF fixture without relying
   on a real OW instance.

The session result must demonstrate that an incomplete, pending, or inconsistent
response can be inspected without inventing data or creating a second health
source.

## 3. Architecture And Trust Boundary

### 3.1 Topology

```text
+----------------------+       HTTPS/cookie       +----------------------+
| Navegador / PWA      | -----------------------> | BFF FastAPI          |
| React + Vite + TS    |     mismo origen /api    | sesion y autorizacion|
+----------------------+                          +----------+-----------+
                                                               |
                                                               | credencial
                                                               | server-side
                                                               v
                                                    +----------------------+
                                                    | Open Wearables       |
                                                    | fuente canonica OW   |
                                                    +----------------------+
```

[FIXED] The frontend follows the master-plan architecture: React + Vite +
TypeScript, React Router, TanStack Query, and accessible components. The
intermediary backend is FastAPI and Pydantic. Keep the shell installable as a
PWA with static assets as the only cache.

[FIXED] The browser communicates with the BFF only through same-origin relative
routes. The BFF resolves the user from the session and applies authorization
before querying OW.

The `/verify/...` paths in this brief are browser UI routes. BFF endpoint
references use the complete `/api/v1/me/verify/...` paths; `/verify/...` is not a
public BFF route shorthand.

The browser never receives or knows:

- The OW API key or any service credential.
- A `user_id` used to select queried data.
- Persistent OIDC tokens.
- Internal URLs, private endpoints, or raw file paths.
- SQL queries, table names, or import payloads.

[FIXED] A run identifier visible in the UI must be an opaque `runKey`; it must
not contain a real UUID or reveal a user identifier. The BFF decides which
resource corresponds to that `runKey`.

### 3.2 Responsibilities

| Layer | Responsibility in this slice | Prohibition |
|---|---|---|
| React/Vite | Presentation, navigation, accessibility, states, and read filters | Do not call OW or choose the destination user |
| TanStack Query | Ephemeral session cache and request states | Do not persist private responses in IndexedDB |
| BFF FastAPI | Session, authorization, stable contract, fixture/OW adaptation, and errors | Do not be a generic URL proxy |
| Open Wearables | Source of normalized facts and domain metadata | Do not access it through external SQL as the normal integration |
| Fixture adapter | Reproducible synthetic contracts for development and Playwright | Do not contain real records |

[PROPOSED] In the initial session, the BFF must be able to swap the real OW
client for a fixture adapter without changing the routes or model consumed by
the UI. The UI must never know whether a response comes from the adapter or OW.

### 3.3 Sync Metadata

OW may expose `metadata`, `message`, and `error` with open content. The adapter
and BFF must distinguish:

- `upstream_observed`: server-side evidence of the OW shape; not a public API.
- `BFF_sanitized`: aggregated, allowlisted fields generated by the BFF after
  sanitization and validation.
- `raw_not_public`: unsanitized metadata, messages, errors, and raw payloads;
  they must not reach the browser or public fixtures.

`[PENDING]` The allowlist and its sanitization tests must exist before connecting
real OW. UI fixtures may use only synthetic `BFF_sanitized` copy and aggregates;
do not invent real payloads. Sanitization is not considered implemented merely
because the contract or fixture exists: it belongs to the BFF and must be
verified before integrating OW.

### 3.4 PWA

[FIXED] The service worker may cache the shell, manifest, icons, and a generic
offline screen. It must not permanently cache private health responses, runs, or
sources.

## 4. Routes And Navigation

Navigation represents verification, not training. Retain the canonical strategy:
read-only health reading from OW; the BFF may create its own idempotent
`VerificationRun` without mutating OW health facts. Therefore all following
routes are reads except `POST /api/v1/me/verify/runs`, which only creates that
BFF control record.

| Route | Purpose | Aggregated data | Permitted action |
|---|---|---|---|
| `/verify` | Daily verification | Activity, sleep, recovery, coverage, and warnings for a logical date; body only as a view relative to `now` | Change date/timezone and query again |
| `/verify/sources` | Visible source inventory | Synthetic name, capabilities, latest aggregate observation, quality, and ambiguity | Filter or open informational detail |
| `/verify/runs` | Processing history | State, time window, counts, source, and coverage for each run | Change filters and load another page |
| `/verify/runs/:runKey` | Run detail | Aggregated state, counts, and warnings for the BFF `VerificationRun` | Return to the list or query again |
| `/verify/settings` | Connection metadata | Declared versions, effective timezone, schema, capabilities, and technical state | No mutation; query only |

`[FIXED]` The UI uses the BFF's `runKey` and `VerificationRun`. OW `run_id`,
`manifest_id`, or `batch_id` identifiers, when present, are server-side
references and do not appear in the browser contract. `batch_id` is the
observed/internal OW name or wire field; `runKey` is the opaque BFF/browser
identifier and is not a public alias for any of those OW fields.

`[FIXED]` Do not create `/coach`, `/recommendations`, `/goals`, or an editing
route in this slice.

### 4.1 Expected Navigation

```text
/verify
  |-- /verify/sources
  |-- /verify/runs
          |-- /verify/runs/:runKey
  `-- /verify/settings
```

The source route may be preserved when changing pages. If the date or timezone
changes, the BFF must receive a new query and the UI must reset the cursor for
any affected list.

## 5. ASCII Wireframes

The wireframes provide hierarchy guidance, not a final visual design. Numbers
and labels are synthetic.

### 5.1 Desktop

```text
+--------------------------------------------------------------------------------------+
| CONSOLA DE VERIFICACION                 Solo lectura       UTC [Ajustes]           |
+----------------------+---------------------------------------------------------------+
| Verificacion         | Verificacion diaria                                          |
| Fuentes              | Fecha [2024-01-02]   Zona UTC   [Consultar]               |
| Runs                 +---------------------------------------------------------------+
|                      | Cobertura: 1/1 dias   As of: 2024-01-02T12:30:00Z           |
|                      +----------------+----------------+----------------+------------+
|                      | Pasos          | Distancia      | Calorias       | Sueno      |
|                      | 8,240          | 5.3 km         | 0              | 7 h        |
|                      | diario         | parcial        | cero real      | valor      |
|                      +----------------+----------------+----------------+------------+
|                      | Recovery: sin medicion (null)                         |
|                      | ADVERTENCIA: la distancia solo cubre una parte de la ventana |
|                      +---------------------------------------------------------------+
|                      | Fuente sintetica A: disponible                              |
|                      | Fuente sintetica B: origen ambiguo                          |
|                      +---------------------------------------------------------------+
|                      | Ultimos runs: verify-demo-02 parcial | verify-demo-03 pendiente |
+----------------------+---------------------------------------------------------------+
```

### 5.2 Mobile

```text
+------------------------------+
| [=] Verificacion       [i]   |
| Solo lectura                 |
+------------------------------+
| Fecha                        |
| [2024-01-02]                |
| Zona UTC       [Consultar]|
+------------------------------+
| Cobertura                    |
| 1/1 dias                     |
| asOf 2024-01-02T12:30:00Z   |
+------------------------------+
| Pasos                        |
| 8,240  | diario              |
+------------------------------+
| Distancia                    |
| 5.3 km | parcial             |
+------------------------------+
| Calorias                     |
| 0      | cero real           |
+------------------------------+
| Sueno                        |
| 7 h      | valor             |
+------------------------------+
| Recovery                     |
| Sin medida | null             |
| ! Fuente ambigua             |
| [Ver fuentes]                |
+------------------------------+
| Verificacion Fuentes Runs    |
|                         Ajustes|
+------------------------------+
```

[PROPOSED] On desktop, use side navigation and a card grid. On mobile, stack
cards, keep the date and timezone at the top, and turn tables into rows or cards
with the same semantic content.

## 6. Components And UI States

### 6.1 Minimum Components

| Component | Responsibility |
|---|---|
| `AppShell` | Layout, navigation, read-only indicator, and `main` region |
| `RouteGuard` | Apply the BFF session and show pending or blocked access without querying data |
| `VerifyToolbar` | Logical date, effective timezone, and GET query |
| `MetricCard` | Value, unit, summarized provenance, `isDailyTotal`, coverage, and state |
| `CoverageSummary` | Expected/available days, UTC window, and warnings |
| `SourceTable` | Capabilities, quality, and state for each synthetic source |
| `RunTable` | Run list, filters, state, and cursor |
| `RunStatusBadge` | Accessible translation of processing states |
| `RunDetailPanel` | Aggregated counts, warnings, and non-sensitive run metadata |
| `StateNotice` | Empty, pending, error, unsupported, and ambiguous source states |
| `ReadonlySettings` | Versions, schema, timezone, and capabilities without mutation forms |
| `CursorPager` | Load the next page without assuming offsets |

Do not create a recommendation, score, coaching, or clinical-summary component.

### 6.2 Required States

| State | How it is identified | Required presentation | Rule |
|---|---|---|---|
| `loading` | Request in progress | Skeleton with an accessible label and no invented values | Do not show zero or copy data from another date |
| `empty` | Valid response without elements or observations | "No data for this window" message and queried context | Not an error and not equivalent to zero |
| `zero` | Zero confirmed by OW/BFF | `0` plus "real zero" label | Use only with semantic confirmation |
| `null` | Missing or null field without an observation | "No measurement" or "Not available" | Never render as `0` |
| `partial` | Incomplete coverage or set | Available value, partial badge, proportion, and warning | Do not present as a complete window |
| `unsupported` | Missing capability or metric outside the contract | "Not supported by this source" | Do not retry indefinitely or estimate |
| `ready` | One source with sufficient provenance for this scope | "Available" and declared capabilities | Does not imply data exists or all capabilities are complete |
| `pending` | Run `queued`, `accepted`, or `processing` | "Pending" with last update and non-terminal state | A `202 Accepted` is not confirmed persistence |
| `completed_with_findings` | Terminal run whose closed scope has at least one `mismatch` finding | "Completed with findings" and finding detail | Do not downgrade to `inconclusive` when comparison closed |
| `error` | Timeout, 4xx/5xx, or invalid response | Generic technical error, untraceable request ID, and GET re-query | Do not show payload or secret |
| `source_ambiguous` | More than one possible source or insufficient provenance | Visible warning and value without exclusive attribution | Do not choose a source silently |
| `not_verifiable` | Public API cannot prove the requested fact | "Not verifiable with the available API" and scope explanation | Do not present as absence or an import error |
| `inconclusive` | Missing page, invalid cursor, failed dependency, or non-unique correlation | "Inconclusive result" and manual re-query | Do not invent a conclusion or turn it into `empty` |

[FIXED] A state must have accessible text and semantics; color may reinforce it,
but must never be the only signal.

### 6.3 Copy Rules

- "No data" describes an empty collection.
- "No measurement" describes a `null` value.
- "Not supported" describes a missing capability.
- "Partial" describes incomplete coverage, not a transport error.
- "Available" describes a `ready` source with sufficient provenance, not a data guarantee.
- "Pending" describes non-terminal processing.
- "Completed with findings" describes a terminal run with at least one closed `mismatch`.
- "Error" describes a technical failure, not a missing metric.
- "Ambiguous source" describes insufficient provenance, not an automatic selection.

## 7. BFF View Model

### 7.1 Wrapper

[FIXED] The UI consumes a stable wrapper with these fields, aligned with the master plan:

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

| Field | UI use |
|---|---|
| `schemaVersion` | Select the view-model parser; do not confuse it with the OW version |
| `asOf` | Indicate when the response was produced; always RFC3339 UTC |
| `timezone` | Indicate the zone applied to the logical day and visible formatting |
| `data` | Aggregated values and entities the screen may render |
| `coverage` | Requested window, expected days, available days, and coverage by domain |
| `warnings` | Limitations, unknown fields, partial/pending states, or ambiguous provenance |
| `extensions` | Additive capabilities and experimental metadata without breaking the previous UI |

### 7.2 Mixed Synthetic Example

This example is a public fixture only. The values do not represent any person.
The synthetic sleep duration is `25200` seconds (7 h); the example's `null`
corresponds to `recoveryScore`, not an observed sleep duration. `warnings`
`message` values are allowlisted `BFF_sanitized` copy; they are not raw OW
messages and sanitization remains a pending BFF requirement.

```json
{
  "schemaVersion": "1",
  "asOf": "2024-01-02T12:30:00Z",
  "timezone": "UTC",
  "data": {
    "logicalDate": "2024-01-02",
    "summary": {
      "steps": {
        "state": "value",
        "value": 8240,
        "unit": "count",
        "isDailyTotal": true
      },
      "distanceMeters": {
        "state": "partial",
        "value": 5300,
        "unit": "meters",
        "isDailyTotal": true,
        "coverage": {
          "availableDays": 1,
          "expectedDays": 1,
          "isPartial": true,
          "observedFraction": 0.5
        }
      },
      "activeCaloriesKcal": {
        "state": "zero",
        "value": 0,
        "unit": "kcal",
        "isDailyTotal": true
      },
      "sleepDurationSeconds": {
        "state": "value",
        "value": 25200,
        "unit": "seconds",
        "isDailyTotal": false
      },
      "recoveryScore": {
        "state": "null",
        "value": null,
        "unit": null,
        "isDailyTotal": false
      },
      "stress": {
        "state": "unsupported",
        "value": null,
        "unit": null,
        "isDailyTotal": false
      },
      "heartRate": {
        "state": "source_ambiguous",
        "value": 60,
        "unit": "bpm",
        "isDailyTotal": false
      }
    },
    "sources": [
      {
        "sourceKey": "synthetic-source-a",
        "label": "Fuente sintetica A",
        "state": "ready",
        "capabilities": ["activity", "body"]
      },
      {
        "sourceKey": "synthetic-source-b",
        "label": "Fuente sintetica B",
        "state": "source_ambiguous",
        "capabilities": ["heart_rate"]
      }
    ],
    "runs": {
      "items": [
        {
          "runKey": "verify-demo-01",
          "state": "persisted",
          "counts": {
            "recordsSeen": 8,
            "recordsAccepted": 8,
            "recordsRejected": 0,
            "recordsDuplicated": 0,
            "fieldsUnsupported": 0
          }
        },
        {
          "runKey": "verify-demo-02",
          "state": "partial",
          "counts": {
            "recordsSeen": 12,
            "recordsAccepted": 10,
            "recordsRejected": 1,
            "recordsDuplicated": 1,
            "fieldsUnsupported": 0
          }
        },
        {
          "runKey": "verify-demo-03",
          "state": "pending",
          "counts": {
            "recordsSeen": null,
            "recordsAccepted": null,
            "recordsRejected": null,
            "recordsDuplicated": null,
            "fieldsUnsupported": null
          }
        }
      ],
      "page": {
        "nextCursor": "cursor-synthetic-02",
        "hasNext": true,
        "totalCount": null
      }
    }
  },
  "coverage": {
    "requested": {
      "logicalDate": "2024-01-02",
      "from": "2024-01-02T00:00:00Z",
      "to": "2024-01-03T00:00:00Z",
      "timezone": "UTC"
    },
    "expectedDays": 1,
    "availableDays": 1,
    "isPartial": true,
    "byDomain": {
      "activity": { "expectedDays": 1, "availableDays": 1, "state": "complete" },
          "sleep": { "expectedDays": 1, "availableDays": 1, "state": "complete" },
      "body": { "expectedDays": null, "availableDays": null, "state": "relative_to_now" }
    }
  },
  "warnings": [
    {
      "code": "PARTIAL_COVERAGE",
      "severity": "warning",
      "message": "La distancia no cubre toda la ventana sintética."
    },
    {
      "code": "SOURCE_AMBIGUOUS",
      "severity": "warning",
      "message": "La atribución de frecuencia cardíaca requiere provenance adicional."
    },
    {
      "code": "BODY_RELATIVE_TO_NOW",
      "severity": "info",
      "message": "La disponibilidad de body es relativa al momento de consulta, no a la fecha lógica."
    }
  ],
  "extensions": {
    "fixture": {
      "synthetic": true,
           "case": "overview_mixed"
    },
    "capabilities": {
      "workoutDetails": "aggregate_only",
      "gps": "not_verifiable"
    }
  }
}
```

`[FIXED]` The example does not expose OW `batch_id`, `manifest_id`, or `run_id`.
The internal relationship between a BFF verification and an OW sync is not part
of the public view model.

## 8. Screen-to-OW Data Mapping

The sources and endpoints in this table are implemented according to
[`OW_READ_CONTRACT.md`](./contracts/OW_READ_CONTRACT.md) and
[`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md). The BFF adapts OW and
does not expose its internal routes to the browser.

| Screen | Conceptual OW domain | BFF transformation | Visible result |
|---|---|---|---|
| `/verify` | Daily activity, sleep, and recovery summaries; body only relative to `now`; series only when necessary | Resolve the user from the session, normalize units, calculate the local window in UTC, and preserve `null`/capability | Metric cards, coverage, and warnings |
| `/verify/sources` | Capabilities, provenance, and source catalog | Reduce to a permitted synthetic source, hide traceable identifiers, and mark conflicts | Source table and `ready`/`source_ambiguous` states |
| `/verify/runs` | BFF `VerificationRun` and summarized OW state when available | Normalize `stage/status`, paginate the BFF's own record, and do not fake a `sync/runs` cursor | Run table and pagination |
| `/verify/runs/:runKey` | Aggregated state, counts, and warnings | Resolve `runKey` on the server; never return files, raw payloads, or OW IDs | Aggregated detail and available provenance |
| `/verify/settings` | BFF/OW versions, capabilities, and technical health | Return public metadata only; GPS only as availability until a formal contract | Non-mutating settings panel |

### 8.1 `isDailyTotal`

`[FIXED]` `isDailyTotal` is a semantic assertion, not a rendering decision.

- Show a daily total only when OW or the BFF explicitly marks it `true`.
- Do not sum a series twice when it is already a daily total.
- Do not infer `true` because the date filter contains one day.
- A temporal sample or workout interval must use `false` or omit the field when
  the contract cannot determine it.
- A value `0` with `isDailyTotal: true` may be a real zero; do not turn it into
  empty.
- A `null` value must remain `null` even when the window has other data.
- If the contract does not declare the semantics, show a warning and do not
  present a canonical total.

The first UI must not derive new totals by adding workouts, samples, or multiple
sources. Verification must show what the contract declares.

### 8.2 `summaries/body` Relative To `now`

`[FIXED]` OW `GET /summaries/body` does not accept the date selected by the UI.
`latest` is calculated relative to `now` and `latest_window_hours`, while
`averaged` uses `average_period`. Therefore:

- `/verify` does not present `body.latest` as a measurement for the selected
  logical day.
- If displayed, label it "relative to query," anchor it to `asOf`, and include
  the `BODY_RELATIVE_TO_NOW` warning.
- A historical date or trend requires a documented time-window read; do not
  reuse `summaries/body`.
- A `null` `BodySummary` is "no measurement"; it is not zero or an empty
  dashboard response.

### 8.3 Cursor Pagination

`[FIXED]` The frontend must not assume that the first response contains the full
history.

Proposed list contract:

```text
GET /api/v1/me/verify/runs?from=2024-01-01&to=2024-01-07&limit=25
GET /api/v1/me/verify/runs?from=2024-01-01&to=2024-01-07&limit=25&cursor=<opaque-cursor>
```

Rules:

- For paginated timeseries, summaries, and events, the BFF consumes the OW
  cursor server-side and the browser handles only an opaque cursor from the BFF
  contract.
- The `VerificationRun` list is paginated over the BFF's own record. OW
  `sync/runs` and `sync/recent` offer no real cursor; do not manufacture one from
  `limit`.
- `nextCursor: null` means no elements remain.
- Changing the date, filters, or timezone resets the cursor.
- The UI retains the applied criteria when requesting the next page.
- The UI concatenates pages without duplicating `runKey` and does not order by a
  field the contract does not guarantee.
- Treat an expired cursor as a recoverable error: restart the list, do not invent
  a page.
- Detail receives an opaque `runKey` and never a browser-selected `user_id`.

### 8.3 UTC And Timezone

`[FIXED]` OW and the BFF exchange timestamps as RFC3339 UTC. The timezone is
used to define the logical day and present dates.

- The UI sends `date=YYYY-MM-DD` and `timezone=<IANA-timezone>` to the BFF.
- The BFF validates the zone and calculates `[local midnight, next local
  midnight)`.
- The BFF converts the boundaries to UTC before querying OW.
- `asOf` is always shown as a UTC instant; the user may view the effective zone
  separately.
- Do not perform offset arithmetic in individual components.
- When the zone changes, query the summary again and reset dependent lists.
- Runs are ordered by the contractual timestamp but displayed in the selected
  zone.
- A night crossing midnight must follow the contract's documented rule; do not
  silently reassign it.

`[PENDING]` The exact policy for sleep crossing midnight remains decision P-12 in
the master plan and must enter the future contract.

## 9. BFF Slice Contract

`[FIXED]` The implementable contract is in
[`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md). This brief does not duplicate
its HTTP codes or schemas; the BFF contract is
authoritative for the adapter, UI, and tests.

| Method | BFF route | Query/body | Wrapper |
|---|---|---|---|
| `GET` | `/api/v1/session` | none | Session and access state without `userId`. |
| `GET` | `/api/v1/me/verify/overview` | `date`, `timezone` | Daily summary, coverage, and warnings. |
| `GET` | `/api/v1/me/verify/sources` | optional `date`, `timezone` | Sanitized sources and capabilities. |
| `GET` | `/api/v1/me/verify/runs` | `from`, `to`, `state`, `cursor`, `limit` | BFF page with its own `page.nextCursor`. |
| `POST` | `/api/v1/me/verify/runs` | `date`, `timezone`, `domains` | Creates a `VerificationRun`; does not import or modify OW. |
| `GET` | `/api/v1/me/verify/runs/{runKey}` | none | Aggregated run state and detail. |
| `GET` | `/api/v1/me/verify/settings` | none | Non-sensitive schema, versions, and capabilities. |

`[FIXED]` No route includes `user_id` as a browser-provided parameter. The BFF
gets the OW link from the session and control-plane configuration. `runKey` is
opaque and is not an OW-visible `run_id`, `manifest_id`, or `batch_id`.

`[FIXED]` Responses use `schemaVersion`, `asOf`, `timezone`, `data`, `coverage`,
`warnings`, and `extensions`. The minimum UI states are
`loading`, `empty`, `value`, `zero`, `null`, `partial`, `unsupported`, `ready`,
`pending`, `completed_with_findings`, `error`, `source_ambiguous`,
`not_verifiable`, and `inconclusive`.
`stage/status` normalization is in the table in
[`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md).

`[FIXED]` `stage=completed` with `status=in_progress` is an inconsistent
combination mapped to `inconclusive`; do not present it as successful terminal
state. A `mismatch` that could be compared and closed leaves the global
`VerificationRun` in `completed_with_findings`, not `inconclusive`. The latter
is reserved for a check that could not be closed.

`[RISK]` If the UI connects to concrete OW endpoints before the version is
pinned, every schema change may become an accidental visual decision. Keep the
synthetic adapter until contract tests exist.

## 10. Synthetic Fixtures

`[FIXED]` OW fixtures and fixtures consumed by the UI are separate:
[`ow-read-v1.json`](./fixtures/ow-read-v1.json) retains OW snake_case and
[`ui-verification-v1.json`](./fixtures/ui-verification-v1.json) contains the
BFF camelCase contract. They must run without the internet or a real OW
instance.

The minimum collection must cover:

| Fixture | What it demonstrates |
|---|---|
| `overview_mixed` | Normal value, real zero, `null`, partial, and unsupported in one response |
| `overview_empty` | Valid window without observations |
| `overview_error` | Timeout or BFF error without sensitive payload |
| `source_ready` | One source with sufficient provenance and `ready` state |
| `source_ambiguous` | Two synthetic sources without sufficient provenance |
| `runs_first_page` | First page with terminal and pending states |
| `runs_second_page` | Valid cursor and end of collection |
| `verification_run_partial` | Seen/accepted/rejected/duplicated counts and warnings |
| `pending` | `accepted` or `processing` without asserting persistence |
| `settings_capabilities` | Schema, placeholder version, and capabilities |
| `verification_run_create` | `201`/`202`, opaque `runKey`, and synthetic idempotency |
| `verification_run_mismatch` | `mismatch` result without raw payload |
| `verification_not_verifiable` | `segments`/`hrZones` or sync completeness not demonstrable |
| `auth_401` / `session_required_401` / `session_anonymous_401` | Anonymous session and safe HTTP `401` response |
| `auth_403` / `access_pending_403` | Pending access and safe HTTP `403` response |
| `access_blocked_403` | Blocked link or ownership with `ACCESS_BLOCKED` |
| `idempotency_conflict_409` | Idempotency conflict with `IDEMPOTENCY_CONFLICT` |
| `rate_limited_429` | Rate limit with `RATE_LIMITED` and a generic message |
| `internal_error_500` | Generic internal error with `INTERNAL_ERROR` |
| `run_not_found_404` | Missing run without leaking details |
| `upstream_invalid_502` / `upstream_unavailable_503` / `upstream_timeout_504` | Upstream failures without leaking details |
| `validation_400_query` / `validation_400_cursor` / `validation_422_scope` | Invalid date/zone/cursor and scope with safe errors |

`[FIXED]` `ui-verification-v1.json` already covers `session_anonymous_401`,
`access_blocked_403`, `idempotency_conflict_409`, `rate_limited_429`, and
`internal_error_500` with contractual shapes, codes, and generic messages; it
contains no raw metadata or real data.

`[PENDING]` Only the real BFF/UI implementation and runtime remain, together
with HTTP transport, session, ownership, idempotency, rate-limit, and internal
error tests.

Fixture requirements:

- Use documented test dates and artificial values.
- Use `verify-demo-*` for every synthetic `runKey` and `VerificationRun` URL; the
  OW fixture uses `ow-run-demo-*` as `run_id`, and the `runKey`/`owRunId` mapping
  remains server-side and never leaves the browser.
- Do not use realistic UUIDs, MACs, coordinates, routes, file hashes, or real
  device names.
- Do not include raw payloads or file paths.
- Retain enough aggregates to verify units, coverage, and `isDailyTotal`.
- Declare `extensions.fixture.synthetic: true`.
- Playwright must run without the internet or real OW.

`[FIXED]` The MVP fixture contains no coordinates, routes, GeoJSON, GPX,
`segments`, or `hrZones`. A GPS capability may appear as `not_verifiable`
availability, never as a drawable route.

`[RISK]` An overly perfect fixture would hide contract errors. The suite should
prefer mixed and negative cases, not only a complete response.

## 11. Acceptance Matrix And Playwright

Tests must intercept BFF routes or start the synthetic adapter. No UI test may
call OW directly.

| ID | Scenario | Route | Expected verification |
|---|---|---|---|
| PW-01 | Initial load | `/verify` | Accessible skeleton appears, then the mixed summary; browser requests contain no credentials or internal routes |
| PW-02 | Empty window | `/verify` | Shows "no data," not `0`, and retains the queried date and zone |
| PW-03 | Real zero | `/verify` | Value `0` appears with the "real zero" label when `isDailyTotal` is `true` |
| PW-04 | `null` value | `/verify` | `recoveryScore` shows "No measurement"; no visual conversion to zero or misleading empty chart |
| PW-05 | Partial coverage | `/verify` | Shows the value, coverage proportion, and a persistent warning |
| PW-06 | Unsupported metric | `/verify` | Shows "not supported by this source" and does not retry in a loop |
| PW-07 | Unambiguous and ambiguous source | `/verify/sources` | `source_ready` shows `ready` and `source_ambiguous` shows `source_ambiguous`; no selection is made silently |
| PW-08 | Initial list | `/verify/runs` | Shows `persisted`, `partial`, and `pending` states with distinct copy |
| PW-09 | Cursor | `/verify/runs` | Loading the next page uses `nextCursor`, retains filters, and does not duplicate runs |
| PW-10 | Expired cursor | `/verify/runs` | Shows a recoverable error and an option to restart the list without inventing results |
| PW-11 | Partial detail | `/verify/runs/verify-demo-02` | Shows aggregated counts and warnings; no raw payloads, coordinates, or file paths |
| PW-12 | Pending run | `/verify/runs/verify-demo-03` | "Pending" is not presented as `persisted` and no retry action appears |
| PW-13 | BFF error | `/verify` | Accessible technical error, untraceable request ID, and GET re-query; exception body is not leaked |
| PW-14 | Timezone | `/verify` | Changing `timezone` changes the window sent to the BFF and resets dependent data/cursor |
| PW-15 | `asOf` UTC | `/verify` | `asOf` is shown as a UTC instant and is not confused with the logical date |
| PW-16 | `isDailyTotal` | `/verify` | A declared total is not summed again from series; missing semantics produce a warning |
| PW-17 | Non-mutating settings | `/verify/settings` | Shows schema/capabilities/placeholder version; no secret inputs or configuration editing |
| PW-18 | Responsive | All | Mobile viewport has no horizontal scroll or loss of actions, states, or warnings |
| PW-19 | Keyboard and screen reader | All | Visible focus, logical order, landmarks, accessible names, and announced states |
| PW-20 | PWA | Shell | Manifest and assets load; offline shows only the shell/generic page, not cached private data |
| PW-21 | Session and authorization | `/verify` | `session_anonymous_401` goes to login and `access_pending_403` shows pending access; neither becomes `empty` |
| PW-22 | Not verifiable/inconclusive | `/verify/runs/:runKey` | UI distinguishes a contractual limitation from a query error and does not assert a conclusion |
| PW-23 | Missing run | `/verify/runs/:runKey` | `404 RUN_NOT_FOUND` shows a safe error without revealing ownership or turning it into `empty` |
| PW-24 | Upstream errors | `/verify` | `502`, `503`, and `504` show a recoverable technical error; never `empty` or the OW body |
| PW-25 | Minimum validation | `/verify` and `POST /api/v1/me/verify/runs` | `400` rejects invalid date/zone/cursor and `422` rejects invalid scope with a safe field |
| PW-26 | Closed mismatch | `/verify/runs/:runKey` | A `mismatch` finding leaves the global run in `completed_with_findings`, not `inconclusive` |
| PW-27 | Inconsistent upstream state | `/verify/runs/:runKey` | `completed + in_progress` is shown as `inconclusive`, not terminal success |
| PW-28 | Blocked link/ownership | `/verify` | `access_blocked_403` shows blocked access without revealing details or becoming `empty` |
| PW-29 | Idempotency conflict | `/verify/runs` | `idempotency_conflict_409` shows a recoverable conflict and does not duplicate the request |
| PW-30 | Rate limit | `/verify` | `rate_limited_429` shows the limit and respects `Retry-After` when present |
| PW-31 | Generic internal error | `/verify` | `internal_error_500` shows a generic technical error without an exception or raw metadata |

In addition to Playwright, the BFF must test that it rejects an arbitrary
`user_id`, does not expose credentials, and correctly transforms errors and
cursors. These are contract/integration tests, not reasons to relax the browser
matrix.

## 12. Session Definition Of Done

The build session may be declared complete only when all of the following are met:

- The React/Vite TypeScript shell exists with the five requested navigation areas.
- `/verify`, `/verify/sources`, `/verify/runs`, `/verify/runs/:runKey`, and
  `/verify/settings` load without direct OW routes.
- The FastAPI BFF exposes the provisional contract with a synthetic adapter.
- The browser receives no API key, `user_id`, OIDC token, internal URL, or raw
  path.
- The view model contains `schemaVersion`, `asOf`, `timezone`, `data`,
  `coverage`, `warnings`, and `extensions`.
- Loading, empty, real zero, `null`, partial, unsupported, ready, pending,
  completed with findings, error, source ambiguous, not verifiable, and
  inconclusive have verifiable representations.
- Metrics do not turn absence into zero and respect `isDailyTotal`.
- The list uses a cursor and resets correctly when filters or timezone change.
- `POST /api/v1/me/verify/runs` creates a synthetic `VerificationRun`, respects
  idempotency, and does not start an OW import.
- Windows are calculated in the logical timezone and queried in UTC.
- Run detail shows aggregates only, not raw data, personal routes, or coordinates.
- The MVP draws no maps or routes; GPS appears only as unverifiable availability
  until a formal contract exists.
- Playwright covers the minimum matrix and runs with reproducible synthetic
  fixtures.
- Basic accessibility, mobile viewport, and keyboard-navigation tests exist.
- The PWA caches only assets/shell, not private responses.
- Fixtures are marked synthetic and contain no secrets or traceable identifiers.
- The provisional contract, its limits, and pending items are documented without
  changing the master plan.

`[FIXED]` "Works with the happy-path fixture" is not sufficient for Done.
Absence, uncertainty, and pending processing are part of the verification
product.

## 13. Pending Items And Risks

### 13.1 Blocking Pending Items

| Marker | Pending decision | Slice impact |
|---|---|---|
| [PENDING] | Exact, reproducible OW reference (release, tag, commit, or digest) | Prevents validating names, capabilities, states, and semantics against the real API |
| [PENDING] | Server-side OW auth and exact header per deployment | The adapter cannot fix authentication or publish a header that may still vary |
| [PENDING] | Effective `resolution` semantics | Cannot promise that `1min`, `5min`, or `15min` produce real downsampling |
| [PENDING] | OW run retention and historical querying | An absence in `sync/recent` cannot establish that a run never existed |
| [PENDING] | BFF contract validation against the first deployable service | Keeps `schemaVersion`, auth, limits, and errors as the slice contract until integration testing |
| [PENDING] | Server-side relationship between `VerificationRun` and `SyncRun` | Prevents publishing an OW reference as if it were a UI `runKey` |
| [PENDING] | Reproducible Gadgetbridge-OW baseline and removal of the SQL helper/`--ow-db-url` from the normal path | Prevents integrating the parser as an auditable reference; does not claim the helper has already been removed |
| [PENDING] | Sanitization and allowlist for OW metadata, `message`, and `error` | Prevents raw metadata from reaching the browser or public fixtures |
| [PENDING] | Versioned public endpoint and schema for workout details, route, `segments`, and `hrZones` | Keeps rich detail outside this slice and blocks future maps and samples |
| [FIXED] | Versioned public synthetic fixtures | Enable Playwright reproduction without real OW; expand only with artificial cases |

### 13.2 Risks To Watch

- `[RISK]` OW may accept a schema field without persisting it; contract fixtures
  must verify response and persistence when real integration arrives.
- `[RISK]` A `202 Accepted` may be mistaken for terminal success; the UI must
  retain `pending` until the BFF confirms the state.
- `[RISK]` Multiple sources may produce double counts or ambiguous provenance;
  do not merge without a contractual rule.
- `[RISK]` An aggregate value may not be a daily total; require explicit
  `isDailyTotal` and coverage.
- `[RISK]` Caching private responses in the PWA may expose health data; limit the
  cache to the asset shell.
- `[RISK]` Timezone differences may move an observation to another day; always
  test UTC boundaries and the overnight-sleep rule.

### 13.3 Order For The Next Session

1. Read this brief and the [master plan](./PROJECT_PLAN.md).
2. Confirm the [OW read contract](./contracts/OW_READ_CONTRACT.md) against the
   pinned OW version.
3. Implement the BFF adapter over [`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md)
   and the synthetic fixtures.
4. Implement the response wrapper and state renderers.
5. Implement `/verify` and verify `isDailyTotal`, coverage, and timezone.
6. Implement sources, runs, cursor, and aggregated detail.
7. Implement non-mutating settings and the limited PWA shell.
8. Run the Playwright matrix and review that no sensitive data appears.

`[PENDING]` Do not advance workout details, maps, routes, coaching, or
comparisons to close this slice. Their implementation requires OW decisions and
separate contracts.
