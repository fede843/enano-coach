# Open Wearables Health Webapp

## Project Master Document

**Status:** planning

**Audience:** development agents, infrastructure agents, and people resuming the project after a pause.

**Intended visibility:** public repository.

**Main rule:** this document must be readable and actionable without knowing the operator's private infrastructure.

---

## 0. Initial Local Development

[FIXED] The first development work is done directly on the developer's laptop.
The first slice uses synthetic fixtures and a local adapter; it does not require
a real OW instance or a private network.

[PROPOSED] Local defaults are a frontend at
`http://localhost:5173` and a BFF at `http://localhost:8000`. Both ports are
configurable for development and do not constitute a production contract. The
browser calls relative `/api` routes; the development-server proxy resolves the
local BFF without exposing internal URLs to the UI.

[FIXED] Docker, Docker Compose, Ansible, containerization, moving to another
host, and remote deployment are outside the first iterations and the first
slice. They are documented as later phases, not requirements for starting local
implementation.

Local directory names may appear only as temporary development instructions and
must never include personal paths, real data, or host-specific public
configuration.

## 1. Purpose

The project is a custom, responsive web app installable as a PWA for querying
health data stored in an Open Wearables instance.

The application will have:

- User authentication through Authentik and OIDC.
- An intermediary backend, called the BFF, that centralizes sessions,
  authorization, and access to Open Wearables.
- A local root administrator for bootstrap and operational recovery.
- Explicit linking between OIDC identities and Open Wearables users.
- Open Wearables as the single source of truth for normalized health data.
- Progressive support for daily data, workouts, GPS, swimming, body
  composition, and custom metrics.
- Reproducible deployment through Docker Compose in a later phase, outside the
  local first slice.
- An application repository separate from the Ansible, Open Wearables, and
  device-specific importer repositories.

The application is not intended to replace the Open Wearables administrative
portal. The Open Wearables portal remains the platform administration plane.
The web app is the query and user-experience plane.

---

## 2. Executive Summary

The chosen architecture is:

```text
Browser or PWA
        |
        | HTTPS and session cookie
        v
Web frontend
        |
        | /api on the same origin
        v
BFF
   |          |             |
    |          |             +--> Technical identity and control database
   |          |
    |          +----------------> Authentik through OIDC
   |
    +----------------------------> Open Wearables through a server-side credential
```

The browser must never know the Open Wearables API key or directly send a
`user_id` to decide which data to query.

Open Wearables is the only source of truth for health facts. If the web app has
its own database, it contains application control data only:

- OIDC identities.
- Sessions.
- Roles and access states.
- Mappings between local users and Open Wearables users.
- Technical audit records.
- Job and import state.

The web app database will not maintain a parallel copy of health metrics,
workouts, GPS points, or health samples.

Raw files may be retained as immutable evidence and an import-process backup.
They are not a second query source for the web app.

---

## 3. Document Conventions

Use these markers when adding decisions:

- `[FIXED]`: decision that must be respected unless a documented change exists.
- `[PROPOSED]`: technical recommendation still open to review.
- `[PENDING]`: decision that conditions a later phase.
- `[RISK]`: known problem requiring validation or mitigation.
- `[VERIFIED]`: check executed with recent evidence and explicit scope; it does
  not by itself turn a proposal into a production contract.

Field names, endpoints, hosts, and examples in this document are generic. They
do not necessarily represent the final names of a specific Open Wearables
instance.

These are the only permitted documentary markers: `[FIXED]`, `[PROPOSED]`,
`[PENDING]`, `[RISK]`, and `[VERIFIED]`. The technical capability taxonomy is
independent and uses exactly `default`, `fork_extension`, `persisted_internal`,
`public_api`, `accepted_not_persisted`, `future_contract`, and `unverified`. A
capability can be technically `public_api` for an observed response and remain
`[PENDING]` as a documentary decision while the pin, authorization, or
reproducible tests are missing; `fork_extension` can remain `[PROPOSED]` until
its integration is closed. Do not confuse either dimension with UI states.

`skills-lock.json` records and locks exactly the 11 vendored external skills.
The seven custom `enano-coach-*` skills are versioned under `.agents/skills/`
and discovered by path; they must not be added to the external lock. Local
copies of those 11 external skills contain vendored documentation and are not
versioned in the initial commit. They remain available in the worktree and are
reinstalled from `skills-lock.json` with the CLI when needed; `.gitignore` must
prevent them from entering the commit accidentally.

### 3.1 Baseline, Provenance, and Evidence Boundary

Work continues on the local Open Wearables fork as a `[PROPOSED]` development
baseline. The observed state is not fixed in this repository as a reproducible
reference and must not be presented as a release, public API, or deployment
reference. Before integrating OW, record a clean commit, immutable tag/release,
or digest without publishing private environment identifiers.

Before real OW integration or any deployment, an immutable and auditable
reference is required: a fixed clean commit, immutable tag/release, or image
digest, together with verified compatibility among the backend, frontend,
migrations, parser, and contracts. Until that exists, the local fork is not
called upstream and no local extension is considered part of an upstream
release.

Evidence is separated as follows:

| Level | Use in this plan |
|---|---|
| Technical evidence | Code and tests from the local fork or parser showing a concrete capability. It helps design the adapter, not promise public availability; its documentary state must be `[PROPOSED]` or `[PENDING]` according to the limit. |
| `[PROPOSED]` Documentary proposal | Contracts, view models, and construction order that allow progress with fixtures without turning an observation into a stable API. |
| `[PENDING]` Pending verification | Check against a reproducible reference, real persistence, authorization, public schema, or still-missing semantic decision. |

Publicly citable evidence paths, always relative to their respective repositories
and without personal paths, are:

- Open Wearables: `backend/app/schemas/providers/mobile_sdk/sync_request.py`, `backend/app/models/data_point_series.py`, `backend/app/models/workout_details.py`, `backend/app/api/routes/v1/events.py`, `backend/app/api/routes/v1/summaries.py`, and `backend/app/api/routes/v1/sync_status.py`.
- Open Wearables tests: `backend/tests/schemas/test_mobile_sdk_sync_request.py`, `backend/tests/integrations/test_sdk_daily_total_import.py`, `backend/tests/integrations/test_apple_sdk_import.py`, `backend/tests/services/test_sleep_service.py`, `backend/tests/api/v1/test_workouts.py`, and `backend/tests/api/v1/test_sync_status.py`.
- Gadgetbridge-OW: `src/gadgetbridge_ow/normalizer.py`, `src/gadgetbridge_ow/constants.py`, `src/gadgetbridge_ow/sync.py`, and `src/gadgetbridge_ow/client.py`.
- Gadgetbridge-OW tests: `tests/test_normalizer.py`, `tests/test_sync.py`, and `tests/test_client.py`.

These paths are implementation evidence, not links to a private checkout or a
claim that all of their capabilities are exposed through the public API.

---

## 4. Scope

### 4.1 Included

- Responsive web app for desktop, tablet, and mobile.
- Installation as a PWA.
- OIDC authentication through Authentik.
- Server-side sessions through the BFF.
- Local root administrator separate from Authentik.
- Management of local users and their Open Wearables links.
- Daily dashboard.
- Sleep and sleep stages.
- Heart rate and related metrics.
- Steps, distance, and calories.
- Weight and body composition.
- Period trends.
- Workout list and detail.
- GPS routes for activities that have them.
- Extended swimming data.
- Custom metrics from devices or importers.
- Synchronization and import status.
- Development and production Docker Compose as later scope, not a first-slice
  requirement.
- Unit, contract, integration, and end-to-end tests.
- Public documentation without private data.

### 4.2 Out of MVP Scope

- Native mobile application.
- Automatic coaching.
- Diagnosis or medical interpretation.
- Clinical recommendations.
- AI chat.
- Advanced workout comparison.
- Perfect backfill of every historical format.
- Universal support for every device.
- Full offline mode with health data.
- Social features.
- Enterprise multi-tenancy.
- Public integration for untrusted third parties.

---

## 5. Functional Requirements

### 5.1 Daily Dashboard

When data exists, the dashboard must be able to show:

- Selected date and the user's timezone.
- Steps.
- Distance.
- Active calories.
- Basal and total calories when available and semantically defined.
- Average, minimum, and maximum heart rate.
- Resting heart rate.
- SpO2.
- Stress.
- Main sleep session.
- Naps.
- Sleep duration and stages.
- Latest weight measurement.
- Body fat.
- Body water.
- Lean mass.
- Bone mass.
- BMI.
- Last synchronization status.
- Warnings about incomplete data.

The UI must distinguish:

- No data.
- True zero value.
- Null value.
- Incomplete data.
- Unsupported metric.
- Import error.
- Data still pending processing.

It must never present a missing value as zero.

### 5.2 Trends

Initial trends must support windows of:

- 7 days.
- 30 days.
- 90 days.

Initial metrics:

- Weight.
- Body fat.
- Body water.
- Resting heart rate.
- Steps.
- Calories.
- Sleep duration.
- Workout count.

The trend must show data coverage. An average over three available days must not
be presented like an average over thirty complete days.

### 5.3 Workouts

The MVP must include:

- List filterable by date.
- Filter by sport or normalized type.
- Start date and time.
- Duration.
- Distance.
- Calories.
- Heart rate.
- Pace or speed when available.
- Cadence when available.
- Power when available.
- Elevation when available.
- Source and device.
- Quality warnings.

Extended detail may later include:

- Time-series samples.
- Heart-rate zones.
- Power zones.
- Splits.
- Laps.
- GPS route.
- Swimming metrics.
- Training effect.
- Recovery time.
- Training load.
- Manufacturer-specific fields.

### 5.4 Synchronization and Imports

The application must show:

- Last attempt.
- Last confirmed synchronization.
- Current status.
- Process source.
- Number of records seen.
- Number accepted.
- Number duplicated.
- Number rejected.
- Unknown fields.
- Warnings.
- Summarized errors.
- Retry possibility where applicable.

An asynchronous API `202 Accepted` means that the job was accepted or queued.
It does not mean that all data has been validated and persisted.

### 5.5 First Slice: Fixture -> BFF -> UI

`[FIXED]` The canonical first-slice strategy is: read-only health reads with
respect to OW; the BFF may create its own idempotent `VerificationRun` without
mutating OW health facts. It must traverse the complete chain with synthetic
data:

```text
synthetic OW fixture
        -> adapter/BFF
         -> BFF view model
         -> responsive UI
```

The adapter must be able to replace the real OW source without changing the
contract consumed by the UI. The initial implementation covers:

- Daily activity: steps, distance, calories, minutes, and aggregated HR when
  available.
- Sleep: main night, naps, duration, time in bed, stages, and published
  intervals; generic `sleeping` is not converted to `deep`, `light`, or `rem`.
- Recovery: score and available components, preserving `null`.
- Body: weight/composition and recent readings only as a view relative to `now`,
  with an explicit warning; not as a measurement for the selected day.
- Basic workouts: list or aggregated block with normalized type, start/end,
  duration, distance, calories, HR, pace/elevation when OW publishes them,
  source, and quality. It does not include rich detail.
- Sources and coverage: sanitized inventory, theoretical capabilities,
  requested window, expected/available days, and warnings.
- Sync/runs: run status, source, timestamps, aggregated counts, and `partial`,
  `error`/`failed`, `pending`, and terminal states; `batch_id`/`run_id` are
  correlated server-side only.
- VerificationRun: BFF-owned request created by `POST`, idempotent, and
  separate from `SyncRun`; its record does not mutate OW health facts.
- Data semantics: `null`, true zero, `empty`, `partial`, `unsupported`,
  `pending`, `loading`, `error`, `source_ambiguous`, `not_verifiable`, and
  `inconclusive` where applicable.
- `isDailyTotal`: display and preserve it only when the contract declares it;
  do not re-sum daily totals, samples, workouts, or multiple sources.

This slice does not include maps, renderable GPS, OW health-fact mutations,
imports, retry, editing, AI, comparisons, or direct SQL against OW. The
`POST` that creates the BFF-owned `VerificationRun` does belong to the slice: it
only creates that control record, respects idempotency, and does not mutate OW
health facts. Health queries in the slice remain GET requests.

The screen must demonstrate empty, zero, null, partial, unsupported, and pending
without converting any into another. The body-relative-to-`now` case, coverage,
and basic workouts must live in the same mixed fixture to avoid a prototype that
works only with complete responses.

`[VERIFIED]` `ui-verification-v1.json` already covers the synthetic cases for an
anonymous session, `ACCESS_BLOCKED`/`403`, `409`, `429`, and `500` with
contractual shapes, generic messages, and no real payloads.

`[PENDING]` The real BFF/UI HTTP runtime for session, ownership, idempotency,
rate limiting, sanitization, and errors remains to be implemented and tested.
Fixture coverage does not demonstrate that transport behavior.

The actionable guide is [`MVP_UI_BUILD_BRIEF.md`](./MVP_UI_BUILD_BRIEF.md), the
stable UI boundary is [`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md),
and the OW synthetic responses are [`ow-read-v1.json`](./fixtures/ow-read-v1.json)
and [`ui-verification-v1.json`](./fixtures/ui-verification-v1.json). These
fixtures are artificial and do not constitute production evidence.

---

## 6. Fixed Architectural Decisions

### D-01. Separate Repository

The application code must live in its own repository, separate from:

- Ansible roles.
- Host infrastructure.
- Open Wearables upstream.
- Device-specific importers.
- Personal exports and dumps.

Tentative repository name:

```text
health-webapp
```

The final name may change without affecting the architecture.

### D-02. Open Wearables as the Single Source of Truth

Every normalized health datum consumed by the web app must live in Open Wearables.

The web app must not:

- Create a second database of health facts.
- Maintain a complete copy of metrics.
- Read Open Wearables' internal PostgreSQL directly.
- Depend on undocumented internal tables.
- Write SQL against the Open Wearables database from the BFF or an external
  importer.

If Open Wearables cannot represent a metric, there are two valid solutions:

1. Formally extend Open Wearables through models, migrations, and an API.
2. Retain the raw datum without presenting it as canonical data until a correct
   extension exists.

Do not create a sidecar that becomes a second health-data source.

### D-03. Separate Technical Database

The web app may have its own control-plane database. This database contains no
health data.

Its responsibilities may include:

- Identities.
- Sessions.
- Roles.
- User links.
- Audit records.
- Jobs.
- Provisioning state.
- Non-sensitive configuration.

The technical database may be omitted in an initial read-only test, but it will
be needed for users, sessions, and persistent administration.

### D-04. The Browser Speaks Only to the BFF

The frontend must not know:

- Open Wearables API keys.
- Service credentials.
- Persistent OIDC tokens.
- The local admin password.
- Internal Docker URLs.
- PostgreSQL paths.
- Other users' UUIDs.

### D-05. OIDC with a Server-Side Session

The recommended flow is Authorization Code with PKCE:

1. The browser requests login from the BFF.
2. The BFF generates `state`, `nonce`, and PKCE.
3. Authentik authenticates the user.
4. Authentik returns a code to the BFF.
5. The BFF validates issuer, audience, signature, expiration, `state`, `nonce`,
   and PKCE.
6. The BFF resolves the local identity through `issuer + subject`.
7. The BFF creates its own session.
8. The browser receives a secure cookie, not OIDC tokens.

### D-06. Local Root Admin

The application will have a local root administrator separate from Authentik.

That administrator is used for:

- Initial bootstrap.
- Operational recovery.
- User management.
- Account linking.
- Privilege assignment.
- Auditing.

The password must be stored as a strong hash and supplied by a secret manager.
It must never be hardcoded in the repository or a Docker image.

### D-07. OW and Authentik Are Different Authorities

Authentik is the user's identity authority.

Open Wearables is the authority for health data and its own platform.

The web app must join both domains through an explicit mapping. It must not
assume that an OW user is automatically an OIDC identity.

### D-08. Server-Side OW API Key

The Open Wearables API key is an integration credential and must not be
considered user-isolated unless the specific OW version guarantees it.

The key:

- Lives only in the BFF or an authorized importer.
- Never appears in JavaScript.
- Never appears in `localStorage`.
- Never appears in a URL.
- Never appears in logs.
- Is sent with the header documented by the OW version.
- Has independent rotation.

The BFF applies user isolation before calling OW.

### D-09. Reproducible Versions

Do not use `latest` as a production contract.

The backend, frontend, and OW extensions must be fixed by:

- Release.
- Tested commit.
- Immutable tag.
- Image digest.

An OW update must include a backup, reviewed migration, contract tests, and
documented rollback.

---

## 7. Service Architecture

```text
LAN or NetBird client
        |
        | HTTPS
        v
Traefik or private reverse proxy
        |
        +--> health-web: static frontend
        |
        +--> health-bff: API, OIDC, and authorization
                    |
                    +--> health-db: optional/owned technical database
                    |
                    +--> Open Wearables API
                    |
                    +--> import worker, if applicable
```

### 7.1 Frontend

Responsibilities:

- Presentation.
- Navigation.
- Forms.
- Visualizations.
- Connection state.
- PWA installation.

The frontend must not contain secrets.

### 7.2 BFF

Responsibilities:

- OIDC login.
- Sessions.
- CSRF.
- Authorization.
- User mapping.
- Open Wearables client.
- Frontend-owned contracts.
- Error transformation.
- Technical import state.
- Auditing.

It must not be a generic URL proxy.

### 7.3 Worker

The worker is optional for the MVP. Use it when operations require:

- Large imports.
- Retries.
- Asynchronous processing.
- Confirmation after a `202`.
- GeoJSON generation or downsampling.

### 7.4 Technical Database

If used, it must be isolated from the Open Wearables database. It may be an
owned PostgreSQL instance or a separate database with an independent user and
lifecycle.

Do not share the Open Wearables PostgreSQL volume.

---

## 8. Technologies

### 8.1 Recommended Frontend

```text
React
Vite
TypeScript
React Router
TanStack Query
Mantine
Recharts
Leaflet
vite-plugin-pwa
Vitest
Playwright
```

Reasons:

- Broad ecosystem.
- Extensive documentation.
- Good mobile support.
- Simple static build.
- Direct PWA installation.
- Accessible components ready to use.
- Lower operational complexity than a full-stack framework.

### 8.2 Frontend Alternatives

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| React + Vite | Huge ecosystem, static build, easy to containerize | Separate BFF | Recommended |
| Next.js | Frontend and backend together, SSR | More cache, Server Components, and deployment complexity | Alternative |
| Nuxt | Organized full-stack, Nitro, and Vue | Requires adopting Vue | Not initial |
| SvelteKit | Simple syntax and good PWA story | Smaller ecosystem | Not initial |
| TanStack Start | Very modern and good server-side support | API still too new to be the primary foundation | Not initial |

### 8.3 UI

Mantine is the initial choice because it provides components, forms,
responsiveness, themes, and dark mode without requiring a complete system to be
built from scratch.

Alternatives:

- Tailwind + shadcn/ui: more visual freedom, more in-house maintenance.
- MUI: very mature, but imposes more of the Material aesthetic.
- Radix: excellent accessibility, but requires building the styles.

The UI must not be a generic copy of an administrative panel. The visual
direction should be a personal health observability application, with
information hierarchy, timelines, cards, and clear charts.

### 8.4 Charts and Maps

- Recharts for standard MVP charts.
- ECharts as an alternative if heatmaps, advanced zoom, or many series are
  needed.
- Leaflet for the first GPS maps.
- MapLibre if vector maps, custom styles, or large volumes become central.

Map tiles must have a provider, license, limits, and attribution defined before
production. Public tile servers must not be assumed to be production
infrastructure.

### 8.5 Recommended Backend

```text
FastAPI
Pydantic
SQLAlchemy
Alembic
PostgreSQL
Authlib
HTTPX
argon2-cffi
Pytest
```

Reasons:

- Natural integration with Open Wearables and Python importers.
- Good support for typed contracts.
- Simple HTTP APIs.
- Easy deployment with Docker.
- Suitable for a personal multi-user project.

Alternatives:

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| FastAPI | Python reuse and clear API | Security must be designed explicitly | Recommended |
| NestJS | Strong structure and TypeScript | More boilerplate and less importer reuse | Alternative |
| Hono | Very small | Too manual for identity, sessions, and administration | Not initial |
| Go | Compact and robust binaries | Higher implementation cost and less reuse | Not initial |

### 8.6 AI

Do not include AI in the MVP.

Open Wearables can already serve as an MCP source. The web app must prioritize:

- Data quality.
- Permissions.
- Provenance.
- UI.
- Trends.
- Synchronization.

AI can be added later as an MCP client or separate module, without duplicating
data or introducing a vector store prematurely.

---

## 9. Authentication, Users, and Privileges

### 9.1 Identity Model

The stable identity is:

```text
(oidc_issuer, oidc_subject)
```

Email is profile information, not an authorization key.

Conceptual model:

```text
oidc_identity
    |
    v
app_user
    |
    v
ow_link
    |
    v
Open Wearables user UUID
```

### 9.2 Control Entities

```text
app_user
- id
- status
- display_name_snapshot
- email_snapshot
- role
- created_at
- last_login_at

oidc_identity
- app_user_id
- issuer
- subject
- claims_snapshot_minimal

ow_link
- app_user_id
- ow_user_id
- status
- linked_by
- linked_at
- unlinked_at

session
- app_user_id
- session_hash
- created_at
- last_seen_at
- expires_at
- revoked_at

audit_event
- actor_id
- action
- target_type
- target_id
- result
- request_id
- occurred_at
```

Do not store OIDC tokens without a documented need. Do not store tokens in the
browser.

### 9.3 Roles

Initial roles:

- `pending`: known identity without health-data access.
- `viewer`: reads their own data.
- `operator`: reads and performs permitted synchronization operations.
- `admin`: manages users and application configuration.
- `root`: full application bootstrap and recovery.

The local root admin may assign roles to OIDC users. Authentik groups may serve
as an initial access filter, but must not automatically grant critical
privileges without an explicit policy.

### 9.4 Linking

Recommended flow:

1. The user signs in to Authentik.
2. The user is identified by `issuer + subject`.
3. The BFF creates or retrieves the local user.
4. If there is no link, the user remains pending.
5. The root admin validates the account.
6. The admin links the existing `ow_user_id` or starts controlled provisioning.
7. The BFF verifies that the OW user exists.
8. The link is stored.
9. The user becomes active.

Do not match automatically by email.

### 9.5 Isolation

User routes:

```text
GET /api/me
GET /api/me/health
GET /api/me/workouts
```

Separate administrative routes:

```text
GET /api/admin/users
GET /api/admin/users/{local_user_id}
POST /api/admin/users/{local_user_id}/ow-link
POST /api/admin/users/{local_user_id}/disable
```

An ordinary user must never choose the `ow_user_id` from the frontend for a
query.

### 9.6 Unlinking

Unlinking an account means revoking web-app access. It must not automatically
delete the Open Wearables profile or data.

Separate explicitly:

- Detach: removes the web-app link.
- Disconnect: revokes a provider connection in OW.
- Delete: deletes OW data; a destructive, separate operation.

---

## 10. Open Wearables and Extensions

### 10.1 Strategy

`[PROPOSED]` Development continues with a versioned extension in the local Open
Wearables fork and an owned image. General parts may be proposed upstream later,
but no local modification is described as upstream or considered a release until
there is a reproducible reference and an explicit integration decision.

Do not modify internal tables from external importers.

The extension must contain:

- Models.
- Migrations.
- Pydantic schemas.
- Persistence services.
- Authenticated endpoints.
- Tests.
- Compatibility documentation.

### 10.2 Canonical Data

OW must retain normalized data that the platform already supports:

- Steps.
- Distance.
- Calories.
- Heart rate.
- HRV.
- SpO2.
- Sleep.
- Weight.
- BMI.
- Body fat.
- Lean mass.
- Basic workouts.

### 10.3 Extended Entities

Conceptual models within OW:

```text
WorkoutDetail
WorkoutRoutePoint
WorkoutSample
WorkoutLap
CustomMetricDefinition
ProvenanceRecord
ImportRun
Capability
```

The exact tables depend on the schema and the OW version that is fixed.

### 10.4 Workout Detail

Conceptual fields:

```text
workout_id
sport_type
original_sport_type
started_at
ended_at
duration_seconds
distance_meters
calories_kcal
elevation_gain_meters
source_code
external_record_id
schema_version
```

Keep the device's original type in addition to the normalized type. This allows
mappings to be corrected without losing source information.

### 10.5 Route Points

Conceptual fields:

```text
workout_id
point_index
observed_at
latitude
longitude
altitude_meters
accuracy_meters
speed_meters_per_second
```

Requirements:

- Index by workout and sequence.
- Coordinate validation.
- Temporal ordering.
- Pagination.
- Downsampling for the browser.
- GeoJSON generated by the API.
- Do not include coordinates in logs.
- Privacy and deletion policy.

Conceptual GeoJSON:

```json
{
  "type": "Feature",
  "geometry": {
    "type": "LineString",
    "coordinates": []
  },
  "properties": {}
}
```

### 10.6 Workout Samples

Conceptual fields:

```text
workout_id
metric_key
observed_at
value
unit
quality
source_code
```

Possible metrics:

- `heart_rate_bpm`.
- `speed_meters_per_second`.
- `pace_seconds_per_meter`.
- `cadence_spm`.
- `power_watts`.
- `elevation_meters`.
- `temperature_celsius`.
- `wearable_stress_level`.

Use existing OW metrics when a compatible meaning exists. Do not create a
custom field to hide a semantic incompatibility.

### 10.7 Swimming

Conceptual fields:

```text
workout_id
lap_index
started_at
ended_at
pool_length_meters
stroke_type
stroke_count
swim_swolf
rest_duration_seconds
```

Unavailable values must remain null. Do not estimate strokes, style, or SWOLF
from insufficient metrics without explicitly labeling the data as derived.

### 10.8 Custom Metrics

Definitions describe meaning. Values are stored in the corresponding canonical
entities.

Generic examples:

```text
wearable_stress_level
training_load
training_effect
recovery_time_seconds
body_water_percentage
impedance_ohms
visceral_fat_level
basal_metabolic_rate_kcal
total_daily_energy_kcal
swim_swolf
stroke_count
pool_length_meters
```

A definition must include:

```text
metric_key
value_type
unit
scope
aggregation
valid_range
definition_version
```

Do not accept arbitrary codes without a catalog or validation.

### 10.9 Provenance

Every extended datum must be able to answer:

- Which system it came from.
- Which source type it came from.
- Which importer transformed it.
- Which parser version was used.
- When it was observed.
- When it was ingested.
- Which transformations were applied.

Conceptual example:

```json
{
  "provenance_id": "<opaque-id>",
  "source_system": "wearable_import",
  "source_kind": "export",
  "import_id": "<opaque-id>",
  "observed_at": "<RFC3339>",
  "ingested_at": "<RFC3339>",
  "transform_chain": [
    {
      "name": "normalize_metric",
      "version": "1"
    }
  ]
}
```

### 10.10 Raw Artifacts

Raw files are evidence of the import process, not the web app's query model.

If retained, they must have:

- Opaque ID.
- Hash.
- File type.
- Size.
- Parser version.
- Processing status.
- Retention policy.

Do not include real files in the repository or public fixtures.

### 10.11 Fork Baseline and Capability Matrix

The following matrix summarizes the evidence available in the local fork and
Gadgetbridge-OW. The state describes what can be claimed today, not a promise of
production:

- `default`: base behavior already present in OW, without depending on a specific
  local extension.
- `fork_extension`: change implemented in the local fork, not yet fixed as a
  reproducible release.
- `persisted_internal`: accepted and stored in internal models or tables, but
  not exposed by the current public response.
- `public_api`: route or field observable on the current HTTP surface; it still
  must be checked against a reproducible pin.
- `accepted_not_persisted`: the input/schema accepts it, but current evidence
  does not show canonical persistence.
- `future_contract`: requires a new endpoint, schema, authorization, and public
  tests.
- `unverified`: an end-to-end check or semantic decision remains open.

| Field or capability | State | Evidence and limit |
|---|---|---|
| Base reads for activity, sleep, recovery, body, and aggregated workouts | `default` | OW summaries/events base surface; exact scope is verified in [`OW_READ_CONTRACT.md`](./contracts/OW_READ_CONTRACT.md). |
| `MetricRecord.is_daily_total` with wire alias `isDailyTotal` | `fork_extension` | Schema and tests in `backend/app/schemas/providers/mobile_sdk/sync_request.py` and `backend/tests/schemas/test_mobile_sdk_sync_request.py`. |
| Retry-safe `isDailyTotal` propagation | `persisted_internal` | Persistence and retry are covered by `backend/tests/integrations/test_sdk_daily_total_import.py` and `backend/app/repositories/data_point_series_repository.py`; this does not authorize summing data in the BFF. |
| `DataPointSeries.value` with `NUMERIC(15,6)` precision | `fork_extension` | Local model, mapping, and migration; evidence in `backend/app/models/data_point_series.py`, `backend/app/mappings.py`, and `backend/migrations/versions/2026_08_07_1200-f6a7b8c9d0e1_data_point_series_value_precision.py`. |
| `WorkoutRoutePoint` and `workout.route` input | `fork_extension` | Local SDK schema; the parser proves the shape, but public persistence of the association remains unresolved. |
| Route to `latitude`/`longitude`/`elevation` series | `persisted_internal` | The import creates internal series and tests verify upsert; a generic series does not prove which workout originated it. |
| `segments` | `persisted_internal` | Stored in `WorkoutDetails.segments` and protected from deletion on an empty retry; not present in the current public response. |
| `hr_zones`/`hrZones` | `persisted_internal` | Validated and stored in `WorkoutDetails.hr_zones`; not present in the current public response. |
| `meanCadence` -> `average_cadence` | `persisted_internal` | The statistics mapper and `test_apple_sdk_import.py` demonstrate internal storage; there is no equivalent exposure in `events/workouts`. |
| Overlap and gap normalization for sleep | `fork_extension` | `backend/app/services/apple/healthkit/sleep_service.py`, `backend/tests/services/test_sleep_service.py`, and `gadgetbridge-ow/src/gadgetbridge_ow/normalizer.py` cover overlap merging and temporal coverage. |
| `batch_id`/`run_id` and retry-safe sync correlation | `public_api` | SDK returns `batch_id`, sync exposes runs/recent/stream, and Gadgetbridge tests correlate `batch_id` with `run_id`; the BFF still must encapsulate those IDs. |
| `partial`/`error` states, `dropped_count`, and PII-free aggregated counts | `public_api` | Schemas and tests in `backend/app/schemas/sync_status.py`, `backend/app/schemas/responses/upload/upload_response.py`, `backend/tests/api/v1/test_sync_status.py`, and `gadgetbridge-ow/tests/test_client.py`; public use is allowed only after the BFF allowlist. |
| Open sync `metadata`, `message`, and `error` | `unverified` | `upstream_observed`: OW may expose them without a closed shape. `BFF_sanitized` and the allowlist remain pending; the raw value is `raw_not_public`. |
| Sources and theoretical capabilities | `public_api` | `data-sources` and `meta/coverage` are observed; theoretical coverage does not prove that the user has data. |
| Daily summaries and basic activity, sleep, and recovery events | `public_api` | Observed routes and schemas in `backend/app/api/routes/v1/summaries.py`, `backend/app/api/routes/v1/events.py`, and their tests; use only read-contract shapes. |
| Body relative to `now` | `public_api` | `summaries/body` exists without a historical date; `latest` is relative to query time, not the selected day. |
| Basic aggregated workout | `public_api` | `events/workouts` returns a summary; duration, distance, calories, HR, pace/elevation are optional and do not imply rich detail. |
| Workout `samples`, `laps`, `notes`, `title`, and `metadata` | `accepted_not_persisted` | The SDK accepts them as input, but current evidence does not show complete canonical persistence. Do not present them as facts. |
| Device metadata (`deviceType`, model, software, and similar) | `accepted_not_persisted` | Some reaches the input and some is discarded or reduced; do not assume the complete set is recoverable or publishable. |
| Unambiguous public route-to-workout association | `future_contract` | Requires a stable relationship, endpoint, pagination, privacy, and schema; timestamp/window association is insufficient. |
| Public detail, route, laps, samples, `segments`, or `hrZones` endpoints | `future_contract` | They do not exist in the current documented public surface; do not invent nested routes. |
| Gadgetbridge mappings `outdoor_walking` -> `walking`, `outdoor_cycling` -> `cycling`, `pool_swimming` -> `swimming`, `elliptical` -> `elliptical`, `freestyle` -> `strength_training` | `fork_extension` | Implemented and tested in `gadgetbridge-ow/src/gadgetbridge_ow/constants.py`, `normalizer.py`, and `tests/test_normalizer.py`; the product decision for each equivalence remains separate. |
| Preservation of `original_sport_type` | `unverified` | The parser knows the raw type, but it is not proven as a canonical public field; decide before comparing or correcting mappings. |
| Semantics of `pool_swimming` and `freestyle` | `unverified` | Current mappings are observed, not a final decision about label, comparable sport, or swimming data. |
| Final `deviceType` for Gadgetbridge | `unverified` | The local default reports `watch`; verify whether it should be a source contract, device type, or unknown value. |
| Unknown sleep gap or stage: `unknown` versus `sleeping` | `unverified` | The current normalizer fills gaps with `sleeping` to preserve coverage; product semantics and presentation require an explicit decision. |

`[FIXED]` The local ability to accept, persist internally, or emit a field does
not equal public capability. `[PENDING]` Before promoting any row to a BFF
contract, test the authorized response, persistence, correlation, and
reproducible OW reference. `[RISK]` Uncommitted changes may change while the UI
is being built; therefore, the first slice uses fixtures and an adapter, not a
real instance.

### 10.12 Sync Metadata Policy

Capability classification does not turn open metadata into a contract. Do not
classify open `metadata`, `message`, or `error` as safe `public_api`. Preserve
these three flow labels for every sync response:

| Label | Meaning | Public rule |
|---|---|---|
| `upstream_observed` | OW may return `metadata`, `message`, or `error` with open or variable fields. | Technical evidence only; not a browser surface. |
| `BFF_sanitized` | The BFF produced allowlisted, aggregated, PII-free fields. | May enter the contract only after sanitization and tests. |
| `raw_not_public` | Raw upstream response or subfields. | Prohibited in the browser and public fixtures. |

`[PENDING]` Sanitization, the count/state allowlist, and raw-metadata rejection
tests must be closed before integrating OW or Gadgetbridge-OW.

---

## 11. Open Wearables API for the Web App

The documentary read reference is [`OW_READ_CONTRACT.md`](./contracts/OW_READ_CONTRACT.md),
which records routes observed in the local fork and marks them as a read
baseline, not a production contract. The contract consumed by the UI is
[`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md), and the actionable order
for the first slice is in [`MVP_UI_BUILD_BRIEF.md`](./MVP_UI_BUILD_BRIEF.md). The
two associated synthetic fixtures are
[`ow-read-v1.json`](./fixtures/ow-read-v1.json) and
[`ui-verification-v1.json`](./fixtures/ui-verification-v1.json).

The definitive endpoints depend on a reproducible OW reference. An observed
route does not authorize inventing schemas, detail, ownership, or persistence
for another version.

### 11.1 Observed Reads in the Baseline

`[FIXED]` The following routes form the observed surface and are described with
parameters and shapes in `OW_READ_CONTRACT.md`:

```text
GET /api/v1/users/{user_id}/data-sources
GET /api/v1/meta/coverage
GET /api/v1/users/{user_id}/timeseries
GET /api/v1/users/{user_id}/summaries/activity
GET /api/v1/users/{user_id}/summaries/sleep
GET /api/v1/users/{user_id}/summaries/data
GET /api/v1/users/{user_id}/summaries/recovery
GET /api/v1/users/{user_id}/summaries/body
GET /api/v1/users/{user_id}/events/workouts
GET /api/v1/users/{user_id}/events/sleep
GET /api/v1/users/{user_id}/sync/runs
GET /api/v1/users/{user_id}/sync/recent
GET /api/v1/users/{user_id}/sync/stream
```

`data-sources` is a source inventory, `meta/coverage` describes theoretical
capabilities, and `summaries/body` is relative to `now`; none of these shapes
alone proves historical data coverage. Paginated endpoints must be consumed
according to their observed cursors and limits, not client assumptions.

### 11.1.1 Conceptual or Future Routes

`[PROPOSED]` These routes are useful for describing a possible extension, but
are not observed as a public API in the current baseline:

```text
GET /api/v1/users/{user_id}/events/workouts/{workout_id}
GET /api/v1/users/{user_id}/events/workouts/{workout_id}/route
GET /api/v1/users/{user_id}/events/workouts/{workout_id}/laps
GET /api/v1/users/{user_id}/events/workouts/{workout_id}/samples
GET /api/v1/meta/series-types
GET /api/v1/meta/capabilities
```

`[PENDING]` Workout detail, an associated route, laps, samples, `segments`, and
`hrZones` enter only when an endpoint, schema, authorization, pagination, and
versioned tests exist. The absence of a route from the observed contract must
not become `empty`; present it as `unsupported` or `not_verifiable` according to
what is being demonstrated.

### 11.2 Observed Import and Conceptual Routes

`[FIXED]` The local fork observes the SDK ingestion endpoint:

```text
POST /api/v1/sdk/users/{user_id}/sync
```

It returns asynchronous acceptance with `batch_id`; receipt or a `202 Accepted`
does not confirm persistence. This route is outside the first slice's read-only
health reads with respect to OW and must not be called by the browser.

`[PROPOSED]` The following routes remain a conceptual contract for a BFF import
API, not observed routes that the client may assume:

```text
POST /api/v1/imports
GET /api/v1/imports/{import_id}
POST /api/v1/imports/{import_id}/retry
GET /api/v1/imports/{import_id}/events
```

Import endpoints must validate authorization, idempotency, and ownership of the
target user. They are not implemented in the first slice.

### 11.3 BFF Contract

The BFF should not expose every OW detail directly. It must provide its own
stable contracts.

`[PROPOSED]` The following routes are examples of the future general BFF
contract, not observed OW routes or an automatic part of the first slice. To
start, the UI must follow only the health-read GET routes and schemas in
[`BFF_UI_CONTRACT.md`](./contracts/BFF_UI_CONTRACT.md).

Examples:

```text
GET /api/v1/me
GET /api/v1/me/dashboard?date=&timezone=
GET /api/v1/me/metrics?types=&from=&to=&resolution=
GET /api/v1/me/sleep?from=&to=
GET /api/v1/me/body?from=&to=
GET /api/v1/me/workouts?from=&to=&sport=
GET /api/v1/me/workouts/{workout_id}
GET /api/v1/me/workouts/{workout_id}/route
GET /api/v1/me/workouts/{workout_id}/laps
GET /api/v1/me/sync/status
GET /api/v1/me/capabilities
GET /api/v1/admin/users
POST /api/v1/admin/users/{id}/ow-link
```

### 11.4 Response Envelope

```json
{
  "schemaVersion": "1",
  "asOf": "<RFC3339>",
  "timezone": "<IANA-timezone>",
  "data": {},
  "coverage": {},
  "warnings": [],
  "extensions": {}
}
```

`extensions` must allow new capabilities to be displayed without breaking an
older UI version.

### 11.5 Pagination

The BFF must encapsulate OW pagination when necessary.

Possible types:

- Offset pagination.
- Cursor pagination.
- Time-window pagination.
- Downsampling by resolution.

The frontend must not assume that one response contains an entire history.

---

## 12. Importers

### 12.1 Pipeline

```text
External file or source
        |
        v
Extraction
        |
        v
Normalization
        |
        v
Validation
        |
        v
Deduplication
        |
        v
Open Wearables API
        |
        v
Terminal confirmation
```

### 12.2 Import States

```text
queued
accepted
processing
persisted
partial
failed
cancelled
```

A client must not move the watermark or mark a file complete immediately after
receiving HTTP `202`.

### 12.3 Idempotency

Depending on the data type, the deduplication key must consider:

- User.
- Source.
- Device or provider.
- Metric type.
- Timestamp or interval.
- External identifier.
- Content hash when no stable ID exists.

Do not use only `timestamp + provider`.

### 12.4 Timezone and Units

- Persist timestamps in UTC.
- Preserve the original offset when available.
- Calculate the logical day in the user's timezone.
- Document assignment of nights that cross midnight.
- Use canonical units.
- Keep the original unit in provenance when conversion occurs.

### 12.5 Unknown Data

Unknown fields must not cause silent loss of the entire batch.

The importer must:

- Preserve the original name.
- Report the field as unknown.
- Omit it from canonical persistence until a definition exists.
- Allow reprocessing with a future parser.

Do not invent values or map a metric to a semantically different one merely to
avoid an error.

### 12.6 Example Fields and Metrics

These names are public examples of possible extensions:

```text
wearable_stress_level
training_load
training_effect
recovery_time_seconds
body_water_percentage
impedance_ohms
visceral_fat_level
basal_metabolic_rate_kcal
skeletal_muscle_percentage
swim_swolf
stroke_count
pool_length_meters
```

Each field must be validated against the source's actual meaning. For example,
lean mass, skeletal muscle, and muscle percentage are not necessarily
equivalent.

### 12.7 Reproducible Gadgetbridge-OW Baseline

`[PENDING]` Gadgetbridge-OW needs its own reproducible baseline before real OW
integration: the current citable state is an observed local checkout, but its
clean commit, tag, or exact release is not yet fixed in this plan. Integration
must record that reference together with the parser version, mappings, sync
contract, and replay tests.

`[RISK]` Any SQL helper or `--ow-db-url` option present in Gadgetbridge-OW is
outside the normal integration path and is a blocker to remove before using the
SDK/API path. Do not claim that the helper has already been removed; verify it
in an independent importer review.

---

## 13. Future Comparisons

Workout and period comparison is feasible with this architecture because it is a
view derived from OW data.

### 13.1 Workouts of the Same Type

Examples:

- Two runs.
- Three bike rides.
- Several swimming sessions.
- Equivalent walks.

Possible metrics:

- Duration.
- Distance.
- Pace.
- Speed.
- Calories.
- Average and maximum HR.
- Time in zones.
- Cadence.
- Power.
- Elevation.
- Laps.
- SWOLF.
- GPS route.

Comparison must separate:

- Normalized type.
- Original type.
- Measured metric.
- Derived metric.
- Estimated metric.
- Source.
- Quality.

Do not automatically compare incompatible sports.

### 13.2 Compare Periods

Examples:

```text
Last 7 days vs previous 7 days
Last 30 days vs previous 30 days
This month vs previous month
```

Metrics:

- Steps.
- Calories.
- Sleep.
- Resting HR.
- Average HR.
- Weight.
- Body fat.
- Body water.
- Workout count.
- Distance.

### 13.3 Aggregations

| Metric | Recommended aggregation |
|---|---|
| Steps | Total, daily average, and median |
| Calories | Total and daily average |
| Sleep | Average and median per night |
| HR | Average, median, percentiles, and resting HR |
| Weight | First value, last value, and change |
| Body composition | Last value and trend |
| Workouts | Individual session and normalized metrics |
| Swimming | Distance, laps, pace, strokes, and SWOLF |

Missing values must contribute to a coverage metric. Do not treat a day without
data as zero.

### 13.4 Conceptual Endpoints

```text
GET /api/v1/me/comparisons/workouts?ids=...
GET /api/v1/me/comparisons/periods?metric=steps&from=...&to=...
GET /api/v1/me/trends?metric=body_weight&range=90d
```

The calculation may be performed on demand. Add materializations or temporary
cache only if actual volume justifies it.

### 13.5 What to Prepare from the Start

- Stable IDs.
- Normalized sport types.
- Canonical units.
- Consistent timestamps.
- Source metadata.
- Data quality.
- Route and laps associated with a workout.
- Measured, derived, or estimated metrics.

The comparison UI does not need to be implemented in the MVP.

---

## 14. PWA

The PWA must be installable, but must not become an offline store for health
data.

### 14.1 Allowed

- Cache static assets.
- Cache icons and the manifest.
- Load the application shell.
- Show a generic offline page.

### 14.2 Not Allowed by Default

- Cache private health responses.
- Store metrics in IndexedDB without an explicit decision.
- Store API keys.
- Store OIDC tokens.
- Send notifications with biometric values.
- Execute offline mutations without safe reconciliation.

### 14.3 Updates

- Version the service worker.
- Handle old installations.
- Show a notice when a new version exists.
- Test asset rollback.
- Do not break a valid session when updating the shell.

---

## 15. Docker and Compose

[PENDING] This section describes a later containerization and deployment phase.
It is not part of the first iterations directly on the laptop or the fixture ->
BFF -> UI first slice. During that slice, the frontend and BFF run with their
local tools, using relative `/api` and the configurable defaults documented in
section 0.

### 15.1 Owned Services

```text
web
bff
migrate
worker, optional
health-db, optional until persistent state exists
```

Open Wearables and Authentik are external dependencies of the production
environment.

### 15.2 Frontend Dockerfile

Stages:

```text
Node builder
    -> pnpm install --frozen-lockfile
    -> tests
    -> build
Unprivileged static server
    -> dist
```

Rules:

- Do not clone external branches during the build.
- Do not use `VITE_*` secrets.
- Prefer relative `/api` on the same origin.
- Serve on an unprivileged port.
- `/healthz` endpoint.
- Minimal image without development dependencies.

### 15.3 BFF Dockerfile

Rules:

- Multi-stage build.
- Unprivileged user.
- Separate production dependencies.
- Owned health endpoints.
- Secret support from files or protected variables.
- Do not run migrations automatically from every replica.

### 15.4 Development Compose

It must allow work without installing Node, Python, or PostgreSQL on the host.

Possible services:

- `web` in development mode.
- `bff` in reload mode.
- Development `db`.
- `ow-mock` or fixtures for reproducible tests.

Never use production volumes in development.

### 15.5 Production Compose

It must not contain `build:` or mount source code.

It must use:

- Published images.
- Release tags and digests.
- Internal networks.
- Healthchecks.
- Deployment-defined volumes.
- External secrets.
- One-shot migrations.
- No public port for PostgreSQL.

Flow:

```text
db healthy
    -> migrate completed
    -> bff ready
    -> web available
```

### 15.6 Secrets

Conceptual secrets:

```text
OIDC_CLIENT_SECRET
OW_API_KEY
APP_SESSION_SECRET
ADMIN_PASSWORD_HASH
DATABASE_PASSWORD
```

Never include real values in `.env.example`, public Compose, Dockerfile, logs,
documentation, or fixtures.

---

## 16. Application Repository Structure

Proposed structure:

```text
health-webapp/
├── apps/
│   ├── web/
│   └── bff/
├── packages/
│   └── contracts/
├── db/
│   └── migrations/
├── docker/
│   ├── web.Dockerfile
│   ├── bff.Dockerfile
│   └── nginx.conf
├── compose.dev.yml
├── compose.production.yml
├── .dockerignore
├── .env.example
├── package.json
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── docs/
│   └── PROJECT_PLAN.md
└── .github/
    └── workflows/
```

The repository must not contain:

- Real datasets.
- Dumps.
- Private screenshots.
- `.env` files.
- Private keys.
- Decrypted vaults.
- Signed URLs.
- Host-specific configuration.
- Personal file paths.

---

## 17. CI/CD

[PENDING] CI/CD, image builds, image scans, and `docker compose config` belong to
a later phase. They are not initial local-development steps and do not authorize
remote deployment.

### 17.1 Pull Requests

Run:

- Formatting.
- Lint.
- Typecheck.
- Unit tests.
- Contract tests.
- Integration tests with temporary PostgreSQL.
- Frontend build.
- BFF build.
- `docker compose config`.
- Secret scan.
- Dependency scan.
- Image scan.
- SBOM generation.

### 17.2 Releases

A release must:

1. Build the images.
2. Publish semantic tags.
3. Publish digests.
4. Publish the SBOM and provenance.
5. Publish production Compose without secrets.
6. Document migrations.
7. Document contract changes.
8. State the compatible Open Wearables version.

Production must use an immutable digest or tag, never `latest`.

---

## 18. Repository Responsibilities

| Repository or system | Responsibility |
|---|---|
| Web application | Frontend, BFF, contracts, tests, and Compose |
| Open Wearables | Health data, API, and domain extensions |
| Importers | Extraction, normalization, and delivery to OW |
| Infrastructure | Docker, networks, proxy, secrets, backups, and versions |
| Authentik | OIDC identity and authentication |

The application repository must not depend on absolute paths, host names, or
variables that exist only in one installation.

---

## 19. Private Network Integration

The web app must be accessible only through:

- An authorized local network.
- A private VPN or mesh network.

Verify before production:

- Internal DNS.
- Certificates.
- Firewall.
- No WAN port forwarding.
- No public tunnels.
- Group-based access restrictions.
- Internal communication between BFF and OW.

Concrete DNS, host, IP, and group details must live outside the public document,
in private deployment configuration.

---

## 20. Observability

Record technical metrics only:

- BFF latency.
- Errors by operation.
- Authentik status.
- Open Wearables status.
- Import duration.
- Accepted, rejected, and duplicate records.
- Retries.
- CPU and memory usage.
- Migration status.

Do not record:

- Tokens.
- Passwords.
- API keys.
- Health payloads.
- GPS coordinates.
- Biometric data.
- Device exports.
- Complete cookies.

Correlation IDs may be used provided they contain no personal IDs or traceable
data.

---

## 21. Tests

### 21.1 Unit Tests

- OIDC validation.
- Identity resolution.
- Authorization.
- User mapping.
- Unit conversion.
- Metric normalization.
- Deduplication.
- Coordinate validation.
- Lap validation.
- Missing-data handling.
- Error transformation.

### 21.2 Contract Tests

- BFF client against fixed Open Wearables.
- Fixtures with new fields.
- Fixtures with null fields.
- Cursor pagination.
- Asynchronous states.
- Extended workouts.
- Routes.
- Swimming.
- Custom metrics.

### 21.3 Integration

- Complete login.
- OIDC callback.
- Session expiration.
- Logout.
- Pending user.
- Approved link.
- Blocked user.
- User A without access to user B.
- Admin with audited access.
- Open Wearables unavailable.
- Authentik unavailable.
- Partial import.
- Idempotent retry.
- Migration and rollback.

### 21.4 Frontend

- Dashboard without data.
- Dashboard with partial data.
- Charts with gaps.
- Null values versus zero.
- Date filters.
- User timezone.
- Workout without GPS.
- Swimming without HR.
- Unknown fields.
- Mobile layout.
- Keyboard navigation.
- Contrast and screen readers.
- PWA installation.
- Logout and session cleanup.

### 21.5 Reconciliation

Use synthetic datasets that verify:

```text
fictional source
    -> importer
    -> Open Wearables
    -> BFF
    -> frontend
```

Validate:

- Record count.
- Units.
- Timestamps.
- Duplicates.
- Null values.
- Provenance.
- Unknown fields.
- Routes and laps.

---

## 22. Criteria for Starting the Web App

Real web-app integration must not begin until Open Wearables meets:

- Fixed and reproducible version.
- Documented read API.
- Daily data available.
- Workouts with stable IDs.
- Normalized sport types.
- Sleep with correct intervals.
- Defined timestamps and units.
- Idempotent import.
- Confirmed asynchronous state.
- Missing fields distinguished from zero.
- GPS routes formally exposed or an explicit decision to defer them.
- Swimming represented without losing the main fields.
- Cataloged custom metrics.
- Tested backups and restore.
- No importer depending on internal SQL as the normal path.

The UI may be prototyped earlier with fixtures, but must not be coupled to a
contract that is still changing.

`[FIXED]` This gate applies to integration of a real OW instance and deployment,
not to the synthetic first slice. The slice may start with the fixture adapter
and must make visible which part is a BFF contract, which part is an observed OW
route, and which part remains unverified.

---

## 23. Roadmap

### Phase 0A. First Read-Only Slice with Fixtures

`[FIXED]` This phase can begin without waiting for the OW pin because it does not
connect to a real instance or write health data:

- Run the frontend and BFF directly on the laptop with proposed local defaults
  `5173` and `8000`, configurable ports, and relative `/api` routes.
- Keep Docker, Ansible, remote deployment, and moving to another host outside
  this phase.
- Consolidate contracts and baseline evidence.
- Implement the `ow-read-v1.json` adapter.
- Implement the BFF's read-only health reads with respect to OW and the
  BFF-owned `VerificationRun` according to `BFF_UI_CONTRACT.md`.
- Build the brief's UI with activity, sleep, recovery, body relative to `now`,
  basic workouts, sources, coverage, and runs.
- Test `null`, zero, `empty`, `partial`, `unsupported`, `pending`, errors, and
  `isDailyTotal`.
- Verify that the browser calls only the BFF, without SQL, maps/GPS, mutations,
  AI, or comparisons.

### Phase 0. OW Stabilization

- Fix importers.
- Fix activity types.
- Fix units.
- Fix sleep.
- Resolve idempotency.
- Resolve state after `202`.
- Add detailed workouts.
- Add routes.
- Add laps.
- Add samples.
- Add custom metrics.
- Remove external direct SQL.
- Create synthetic fixtures.
- Fix the OW version.

### Phase 1. Application Foundation

- Create the repository.
- Create the frontend/BFF monorepo.
- Create Dockerfiles.
- Create development Compose.
- Implement health checks.
- Implement contracts.
- Implement the OW client.
- Implement error handling.

### Phase 2. Identity and Access

- Configure OIDC.
- Implement sessions.
- Implement the local root admin.
- Create the user model.
- Create OIDC-OW mapping.
- Implement roles.
- Implement auditing.
- Test isolation.

### Phase 3. MVP Dashboard

- Daily dashboard.
- Sleep.
- HR.
- Steps.
- Calories.
- Body composition.
- Trends.
- Synchronization status.
- Empty, partial, and error states.

### Phase 4. Workouts

- List.
- Filters.
- Detail.
- Aggregated metrics.
- Samples.
- Zones.
- Provenance.

### Phase 5. Rich Data

- GPS.
- Maps.
- Downsampling.
- GeoJSON or GPX export.
- Swimming.
- Laps.
- Strokes.
- SWOLF.
- Device custom metrics.

### Phase 6. PWA and Production

- Manifest.
- Icons.
- Limited service worker.
- Safe updates.
- Versioned images.
- Reproducible deployment.
- Backups.
- Tested restore.

### Phase 7. Comparisons

- Compare workouts from the same sport.
- Compare equivalent sessions.
- Compare periods.
- Trends.
- Normalized metrics.
- Coverage and quality.

### Phase 8. AI

- Integrate the Open Wearables MCP.
- Queries about owned data.
- Optional summaries.
- Without duplicating storage.
- Without presenting results as diagnosis.

---

## 24. Future Comparisons

Comparison between workouts or periods is compatible with this design and does
not require a second health database.

### 24.1 Compare Workouts

Compare two or more workouts of the same type:

- Duration.
- Distance.
- Pace.
- Speed.
- HR.
- Zones.
- Cadence.
- Power.
- Elevation.
- Laps.
- SWOLF.
- Route.

The comparison must indicate whether each value is:

- Measured.
- Derived.
- Estimated.
- Absent.

### 24.2 Compare Periods

Possible comparisons:

- Last 7 days versus the previous 7 days.
- Last 30 days versus the previous 30 days.
- Current month versus the previous month.
- Same period in different years, if sufficient coverage exists.

Metrics:

- Steps.
- Calories.
- Sleep.
- Resting HR.
- Weight.
- Body fat.
- Body water.
- Workout count.
- Distance.

Each result must include:

- Current-period value.
- Previous-period value.
- Absolute difference.
- Percentage difference when meaningful.
- Number of days with data.
- Warnings.

### 24.3 Aggregations

| Metric | Aggregation |
|---|---|
| Steps | Total, daily average, median |
| Calories | Total, daily average |
| Sleep | Average and median per night |
| HR | Average, median, percentiles, resting HR |
| Weight | First value, last value, change |
| Body composition | Last value, trend |
| Workouts | Individual session and normalization |
| Swimming | Distance, laps, strokes, SWOLF |

Calculations may be performed on demand in the BFF. Add cache or materialized
views only if actual volume justifies it.

---

## 25. Security and Privacy

### 25.1 Runtime Rules

- HTTPS required outside development.
- `HttpOnly` and `Secure` cookies.
- CSRF for cookie-based mutations.
- Strict issuer, audience, nonce, and state validation.
- Server-side API keys only.
- Authorization for every operation.
- Do not trust `user_id` from the frontend.
- Allowlist for outbound connections.
- SSRF protection.
- Size and frequency limits.
- CSP and security headers.
- Updated dependencies.
- External secrets.
- Auditing of privileged actions.

### 25.2 GPS Data

Routes may reveal home, schedules, and habits. An explicit policy must cover:

- Retention.
- Export.
- Deletion.
- Precision reduction.
- Administrative access.
- Logs.
- Future sharing.

### 25.3 Root Admin Security

- Do not use it as a daily account.
- Do not share it.
- Password as a strong hash.
- Rate limiting.
- MFA recommended.
- Mandatory auditing.
- Recovery procedure documented in a private channel.

---

## 26. Observability

Technical metrics:

- Latency by endpoint.
- Errors by dependency.
- OIDC status.
- OW status.
- Import duration.
- Processed records.
- Duplicate records.
- Rejected records.
- Retries.
- Migration status.
- CPU, memory, and restart count.

Never send to observability:

- Health payloads.
- Tokens.
- Passwords.
- API keys.
- Coordinates.
- Exports.
- Complete biometric values.

---

## 27. Backups and Recovery

### 27.1 Open Wearables

Backups must include:

- OW database.
- Auxiliary service databases containing required state.
- Encryption keys required to recover credentials or payloads.
- Version and migration configuration.

### 27.2 Web App

If a technical database exists, back up:

- Local users.
- Mappings.
- Auditing.
- Provisioning state.
- Configuration required to recover sessions or access.

Do not back up inside the repository:

- Real datasets.
- `.env`.
- Tokens.
- Private logs.
- Screenshots.

### 27.3 Tests

- Verify backups with a restore listing.
- Test restoration periodically.
- Test rollback of non-destructive migrations.
- Document destructive operations separately.
- Back up before updating OW.

---

## 28. Public Repository Privacy

This repository must be publishable without revealing operator information.

### 28.1 Never Publish

- Real hosts.
- Private domains.
- IPs.
- Networks or CIDR.
- Local paths.
- Machine names.
- Usernames.
- Real emails.
- MACs.
- Serial numbers.
- Traceable IDs.
- Real UUIDs.
- Tokens.
- API keys.
- Passwords.
- Credential hashes.
- Private keys.
- Database dumps.
- Device exports.
- Real GPX or FIT files.
- GPS coordinates.
- Real biometric values.
- Private logs.
- Signed URLs.
- Rendered production configuration.
- Decrypted vaults.
- Screenshots containing personal data.

### 28.2 Substitutions

Use:

```text
https://auth.example.test
https://health.example.test
https://api.example.test
user@example.invalid
<opaque-user-id>
<opaque-workout-id>
<secret-ref>
<redacted-coordinate>
/srv/example-service
database:5432
```

Health examples must be generated artificially and marked as synthetic.

### 28.3 Pre-Publication Checklist

- Review tracked files.
- Review branches and tags.
- Review Git history.
- Review releases.
- Review CI artifacts.
- Review issues and comments.
- Review images and PDFs.
- Run a secret scanner.
- Search for tokens, signed URLs, and credentials.
- Review file metadata.
- Clone a clean copy.
- Scan the copy again.
- Review rendered Markdown.
- Confirm that public links are valid.
- Confirm that all fixtures are synthetic.

### 28.4 Rules for Future Agents

```text
Treat all health data, exports, dumps, backups, logs, screenshots, and databases
as private by default.

Do not include real secrets, tokens, keys, hashes, IDs, MACs, paths, or domains
in documentation, code, tests, or responses.

If a secret is found, report only its type and location; do not repeat its value.

Use example.test, example.invalid, placeholders, and synthetic names.

Use artificial fixtures, not real records.

Do not include real GPS coordinates.

Do not include absolute paths or private-environment names.

Review Git history, branches, tags, releases, issues, and artifacts, not only the
current state.

Separate public architecture from private runbooks.

Do not read personal data unless necessary for the task.

Do not copy personal data into tests, documentation, or messages.
```

---

## 29. Pending Decisions

| ID | Decision | Impact |
|---|---|---|
| P-01 | Exact compatible OW version | Blocking |
| P-02 | Extensions included in the first version | High |
| P-03 | Custom fork or initial upstream contribution | High |
| P-04 | Final user-provisioning method | High |
| P-05 | Use of OIDC groups for roles | Medium |
| P-06 | Technical database engine and location | Medium |
| P-07 | Raw-artifact retention policy | High |
| P-08 | GPS-route retention policy | High |
| P-09 | Map provider | High |
| P-10 | MVP import sources | High |
| P-11 | Canonical calorie definition | High |
| P-12 | Policy for nights crossing midnight | Medium |
| P-13 | Maximum chart resolutions | Medium |
| P-14 | Comparable-workout definition | Medium |
| P-15 | Mandatory MFA for the root admin | High |
| P-16 | SLO and restore policy | High |
| P-17 | Reproducible Gadgetbridge-OW baseline and removal of the auxiliary SQL path | High |

Each decision must document date, alternatives, decision, reason, and impact.

### 29.1 Update to P-01, P-02, P-03, P-10, P-11, and P-14

These notes do not close decisions that still require confirmation; they record
the working direction derived from current evidence:

| ID | Current state | Working direction and pending item |
|---|---|---|
| P-01 | `[PENDING]` | The local fork commit is only a development baseline. Choose a clean commit, immutable tag/release, or digest before integrating real OW or deploying. |
| P-02 | `[PROPOSED]` | The first slice limits the UI to activity, sleep, recovery, body relative to `now`, basic workouts, sources, coverage, and runs. Internal extensions without a public API remain outside the browser until formalized. |
| P-03 | `[PROPOSED]` | Continue in the local fork for development and testing. Upstream contribution and the final extension-maintenance model remain open; neither is assumed to be a user decision. |
| P-10 | `[PROPOSED]` | To build now, the source is a synthetic-fixture adapter. Later real integration must verify Gadgetbridge-OW, its mappings, and its sync contract before fixing MVP sources. |
| P-11 | `[PENDING]` | The observed parser emits active calories as `ACTIVE_CALORIES_BURNED` and marks the daily total when applicable. The canonical definition of active, basal, and total calories remains pending; the UI must not mix or infer them. |
| P-14 | `[PENDING]` | Comparisons are not implemented in the first slice. Before defining a comparable workout, resolve normalized/raw type, source, units, quality, measured/derived metrics, and public access to detail. |
| P-17 | `[PENDING]` | Gadgetbridge-OW remains in an observed local state; fix its commit/tag/release and remove or block any `--ow-db-url`/SQL helper from the normal path before real integration. |

`[PENDING]` Current Gadgetbridge mappings are an observation of code and tests,
not a final product-semantics decision. In particular, `pool_swimming`,
`freestyle`, `original_sport_type`, `deviceType`, and the choice between
`unknown` and `sleeping` for sleep gaps remain `[PENDING]`.

---

## 30. Definition of Done

A feature is complete when:

- It has a documented contract.
- It uses the correct source of truth.
- It has verifiable authorization.
- It has tests.
- It handles loading, error, empty, and partial data.
- It does not record sensitive data.
- It is technically observable.
- It has a migration and rollback where applicable.
- It is compatible with the session policy.
- It is reproducible in Docker when applicable to a later phase; the first slice
  must be reproducible directly on the laptop with fixtures.
- It is documented for a public environment.
- It does not depend on private hosts, paths, or secrets.

---

## 31. Architectural Invariants

These rules must not be broken without an explicit decision:

1. Open Wearables is the canonical source of normalized health data.
2. Authentik is the OIDC identity authority.
3. The local root admin is an application recovery account, not a shared identity.
4. `issuer + subject` identifies an OIDC user.
5. The BFF derives the user from the session.
6. The frontend never decides which OW user to query.
7. The OW API key never reaches the browser.
8. OW PostgreSQL is not accessed through external SQL as the normal integration
   path.
9. OW extensions must have models, migrations, and an API.
10. A `202 Accepted` is not considered confirmed persistence.
11. Importers must be idempotent.
12. A missing value is not zero.
13. Timestamps and units must be explicit.
14. GPS data requires additional privacy controls.
15. Comparison results are derived and do not replace original data.
16. The PWA must not permanently cache health data.
17. No real secret enters the public repository.
18. Production images must be versioned.
19. Schema changes require a backup and restore tests.
20. Public fixtures must be synthetic.

---

## 32. First Backlog When Resuming the Project

### 32.1 Ordered Immediate Backlog

`[FIXED]` The order for starting work is:

1. Consolidate evidence, provenance, public limits, and links to contracts and
   fixtures in this plan.
2. Create a reproducible local-fork baseline: clean commit, immutable
   tag/release or digest, version manifest, and compatibility test.
3. Build the first-slice mixed fixture for activity, sleep, recovery, body
   relative to `now`, basic workouts, sources, coverage, sync/runs, and all
   required states.
4. Implement the BFF read-only health contract with respect to OW and its
   adapter, hiding OW IDs, credentials, internal paths, and non-allowlisted
   metadata; the `POST` for `VerificationRun` writes BFF control-plane only.
5. Implement unit, contract, integration, and UI/Playwright fixture tests,
   including `null`, zero, `empty`, `partial`, `unsupported`, `pending`, errors,
   and `isDailyTotal`.
6. Only afterward, integrate real OW and Gadgetbridge-OW against the reproducible
   baseline, validate persistence/response, and record differences as contract
   or pending items.

### 32.2 Expanded Later Backlog

1. Fix the Open Wearables version that will be the initial contract.
2. Create synthetic fixtures for the dashboard, sleep, body composition, and
   workouts.
3. Audit which current importer metrics actually reach OW.
4. Design migrations for extended workouts.
5. Design detail, route, laps, and samples endpoints.
6. Define the initial custom-metric catalog.
7. Remove internal SQL dependencies from importers.
8. Implement terminal confirmation of imports.
9. Create the application repository.
10. Create development Compose.
11. Implement the BFF OW client.
12. Implement OIDC with a test Authentik provider.
13. Implement the local root admin.
14. Implement manual user mapping.
15. Implement the MVP dashboard.
16. Add versioned Docker deployment.
17. Add isolation tests.
18. Validate backup and restore.

### 32.3 Subagent Implementation Workflow

`[FIXED]` The primary agent coordinates scope, maintains the evidence matrix,
integrates handoffs, and communicates results. The primary agent does not
directly perform implementation, tests, diff review, the privacy pass, or final
validation; each activity is delegated to an agent independent of the author.
Tasks use an explicit list of permitted files and acceptance criteria:

1. One subagent prepares or updates the adapter and synthetic OW fixtures.
2. One subagent implements the BFF's read-only health reads with respect to OW,
   its transformations, and the idempotent BFF-owned `VerificationRun`.
3. One subagent implements the first-slice UI and its responsive/accessible
   states.
4. One subagent adds unit, contract, integration, and Playwright tests.
5. An independent reviewer reviews the diff and evidence without implementing
   the change.
6. An independent auditor reviews privacy, raw metadata, paths, secrets, and
   fixtures.
7. An independent validator performs final validation and confirms closing
   criteria.
8. A later subagent validates OW/Gadgetbridge integration only after the
   reproducible baseline exists.

Do not edit the same file in parallel. Each subagent works on a disjoint file
scope; `docs/PROJECT_PLAN.md` has one editor, the primary agent. Agents may
analyze interfaces in parallel, but a dependency or conflict is returned to the
primary for sequential integration. The primary integrates only after receiving
the handoffs and does not replace the reviewer, privacy auditor, or final
validator.

Do not implement AI or advanced comparison before completing these foundations.

---

## 33. Notes for the Agent Resuming the Project

Before modifying code:

1. Read this complete document.
2. Identify which decisions have `[FIXED]` status and which remain `[PENDING]`.
3. Review the Open Wearables version and its real contract.
4. Do not assume that a field accepted by a schema is actually persisted.
5. Do not assume that HTTP `202` means final success.
6. Create synthetic fixtures before testing the UI.
7. Preserve separation among health, identity, and deployment.
8. Do not use OW's internal database as an API.
9. Do not introduce a parallel database of health facts.
10. Do not publish data or private deployment-environment details.
11. Make small changes and test each layer separately.
12. Update this document if an architectural decision changes.

The recommended work order is:

```text
OW contract
    -> trusted importers
    -> formal OW extensions
    -> BFF and authentication
    -> dashboard
    -> PWA
    -> maps and swimming
    -> comparisons
    -> AI
```

---

## 34. Public References

These references may remain in the public repository:

- Public Open Wearables documentation.
- Public Authentik OAuth2/OIDC documentation.
- React, Vite, Mantine, and PWA documentation.
- FastAPI, Pydantic, SQLAlchemy, and Alembic documentation.
- Docker Compose documentation.
- Leaflet or MapLibre documentation.
- Documentation for RFC 3339, OAuth2, OIDC, and PKCE standards.

Do not include references that reveal a specific installation, its hosts, paths,
accounts, data, or secrets.
