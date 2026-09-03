# Enano Coach

## Purpose and current status

Enano Coach is a public, responsive web app installable as a PWA for querying
health facts normalized by Open Wearables (OW). The architecture separates the
browser, BFF, OW, and the technical identity store. The browser speaks only to
the BFF; the BFF resolves ownership and queries OW server-side.

The repository is in the planning stage. Available evidence consists of the
master plan, public read and UI contracts, the first-slice brief, synthetic
fixtures, and the locked skills catalog. The canonical first-slice strategy
is: read-only health reads with respect to OW; the BFF may create its own
idempotent `VerificationRun` without mutating OW health facts.

```text
synthetic OW fixture -> adapter/BFF -> BFF view model -> responsive UI
```

## Initial local development

[FIXED] The first iterations run directly on the laptop, locally, offline where
possible, and using synthetic fixtures. Docker, Ansible, and remote deployment
are not used for the first slice. Containerization, moving to another host, and
deployment are deferred to a later phase outside this slice.

[PROPOSED] Local defaults are:

- Frontend: `http://localhost:5173`.
- BFF: `http://localhost:8000`.

The ports are configurable for development and are not a production contract.
The UI must call only relative paths such as `/api`; the development server
proxy may forward those paths to the local BFF. Never embed an internal URL, an
OW URL, or a server-side credential in the frontend.

[FIXED] The approved development order is: complete the synthetic
fixture -> adapter/BFF -> existing UI slice; use an explicit loopback-only
dev/test access mode when needed; then reach the first real-data milestone of
read-only OW summary/source data through the BFF to that existing UI. The
real-data milestone adds no health-fact writes, imports, maps, or production
claims.

[FIXED] Local development may use an explicit, opt-in loopback-only dev/test
access mode with a server-side configured owner reference and OW credential.
This mode is not production authorization and must not be enabled outside
loopback/test boundaries. Authentik/OIDC is a `future_contract` for production
and remains disabled and unwired for now. The browser never sends an API key,
user ID, owner reference, OW credential, or internal URL.

The local OW fork is the development baseline, not a release. Uncommitted
changes are not reproducible and must not be presented as an OW version, a
public API, or a deployment reference.

## Mandatory reading

Before any work, the primary agent and each subagent must read at minimum:

- `AGENTS.md`.
- `docs/PROJECT_PLAN.md`.
- `docs/contracts/OW_READ_CONTRACT.md`.
- `docs/contracts/BFF_UI_CONTRACT.md`.
- `docs/MVP_UI_BUILD_BRIEF.md`.
- All fixtures under `docs/fixtures/`.
- `skills-lock.json`, with the 11 locked external skills.
- `docs/INITIAL_COMMIT_CHECKLIST.md`.
- The seven custom `enano-coach-*` skills, discovered at
  `.agents/skills/enano-coach-*/SKILL.md`.
- The external skill relevant to the task, reinstalled from `skills-lock.json`
  when needed.

`skills-lock.json` records and locks exactly the 11 vendored external skills.
The seven `enano-coach-*` skills are versioned custom skills discovered by
path; they must not be added to the external lock. Local copies of external
skills are not versioned in the initial commit because they are vendored
documentation; reinstall them from the lock with the CLI when needed. The
agent must read both classes when relevant, but must not turn a custom skill
into a lock dependency.

The plan and handoff documents are coordinated sources. Do not edit
`docs/PROJECT_PLAN.md`, `docs/START_SESSION_PROMPT.md`, or
`docs/HANDOFF_TEMPLATE.md` from a task that does not explicitly assign them.

## Delegation And Workflow Modes

[FIXED] Exactly one top-level subagent layer is allowed. Every delegated
assignment uses `subagent_depth: 1`; a subagent executes its assigned scope
directly and must never call `Task`, create a nested agent, or delegate further.
If it cannot perform the scope, it reports the blocker in its handoff.

[FIXED] `local/personal` mode is the default for laptop work, synthetic
fixtures, and the explicit loopback-only dev/test read milestone:

1. One implementation subagent makes the scoped change and returns a handoff.
2. After that handoff, one independent validation subagent checks correctness,
   privacy, and final-scope criteria together.
3. Dependent work is sequential; the coordinator must not parallelize it or
   reopen a passed gate without a new relevant change.
4. If validation finds a blocker, allow at most one targeted fix and one
   revalidation round. If the blocker remains, stop and report it; do not start
   an endless review loop.

Each assignment states relative paths, input and output contracts, privacy
boundaries, evidence classification, expected verification commands, and
`subagent_depth: 1`. Handoffs separate observed facts, proposals, pending
items, and risks. The coordinator integrates the two local handoffs and does
not turn a fixture or local observation into a public API or production claim.

[FIXED] `production/release` mode is activated only by an explicit production
or release decision. It retains the stronger gates: separate sequential
correctness, privacy, and final reviews; an immutable OW/parser/application
reference; reviewed migrations; backup and restore evidence; documented
rollback; and deployment checks. Those gates are not mandatory for every small
local change, but their absence keeps production work `[PENDING]`.

If `Task` is unavailable for a task that requires delegation, stop that task
and record the blocker rather than inventing a review or pretending that it
ran. An explicit user instruction may authorize the coordinator to edit these
workflow documents directly; it does not waive the validation or safety
boundaries.

## Coordination And Files

Top-level delegated work is sequential by default. Independent read-only work
may run concurrently only when it has no dependency or shared write scope; the
coordinator must not parallelize dependent implementation and validation. Each
file has one owner at a time, and a conflict is resolved through a handoff
before ownership changes. Do not reopen already-passed checks unless a new
relevant change affects their scope.

Every local technical delivery requires the independent validation handoff. The
validator must read the diff and evidence without relying only on the
implementation report, and must combine correctness, privacy, and final checks.
Production/release work additionally requires the separate multi-review
handoffs described above. Do not declare success without recent validation
output, an inspected diff, and the required handoff(s).

## Domain invariants

- OW is the canonical source for all normalized health facts.
- The BFF is the browser's only intermediary to OW and is not a proxy for
  arbitrary URLs.
- The application database may contain only control-plane data: OIDC
  identities, sessions, roles, OW links, audit records, jobs, and technical
  import state.
- Do not create a normal copy of metrics, workouts, sleep, GPS, or other health
  facts outside OW.
- Do not use ordinary external SQL against OW PostgreSQL from the BFF or an
  importer. If OW cannot represent a datum, extend OW formally or retain the
  raw value as non-queryable evidence.
- Never send OW API keys, service credentials, persistent OIDC tokens,
  passwords, internal URLs, file paths, or `user_id` to the browser.
- Do not include private data, secrets, real exports, dumps, raw payloads,
  coordinates, or real fixtures in the repository.
- `null`, a true zero, absence, partial, unsupported, pending, error,
  source_ambiguous, not_verifiable, and inconclusive are distinct states.
- Fixtures are artificial and reproduce contracts; they do not authorize access
  to any user or prove a production capability on their own.

## OW baseline and release

Work on the local fork for investigation and development, but a fork with
uncommitted changes is not a release. Before production/release OW integration
or deployment, an immutable and auditable reference is required: a clean
commit, immutable tag/release, or image digest. Compatibility among the
backend, frontend, migrations, parser, and contracts must also be checked, with
a backup, reviewed migration, and documented rollback where applicable. A
loopback-only local read may use the observed fork as development evidence, but
its pin and compatibility remain `[PENDING]` and it must not be presented as a
release or public API.

Do not use `latest` as a production contract. Do not call a local extension
upstream without an integration decision and a reproducible reference.

## Required evidence classification

Every capability, field, schema decision, and handoff claim must have exactly
one of these classifications:

- `default`: OW base capability without depending on a specific local
  extension.
- `fork_extension`: change implemented in the local fork, not yet integrated
  into a reproducible release.
- `persisted_internal`: accepted or stored internally, but not demonstrated in
  the current public response.
- `public_api`: route or field observable on the authorized HTTP surface;
  requires a reproducible pin before production.
- `accepted_not_persisted`: the input or schema accepts it, but there is no
  proof of canonical persistence.
- `future_contract`: requires a new endpoint, schema, authorization, privacy,
  and public tests.
- `unverified`: an end-to-end check or semantic decision remains open.

Do not promote `persisted_internal`, `accepted_not_persisted`, or a schema
observation to `public_api` without an authorized response, tests, and a fixed
reference.

### Documentary markers and crosswalk

The permitted documentary markers are exactly `[FIXED]`, `[PROPOSED]`,
`[PENDING]`, `[RISK]`, and `[VERIFIED]`. `[VERIFIED]` means that a specific
check was executed with recent evidence and explicit scope; it does not by
itself turn a proposal, capability, or observation into a production contract.
Do not use alternative markers to describe facts, implementations, exclusions,
or blockers.

The technical capability taxonomy and the documentary marker are distinct
dimensions. The canonical capability taxonomy is exactly:

```text
default, fork_extension, persisted_internal, public_api,
accepted_not_persisted, future_contract, unverified
```

For example, a capability may have technical state `public_api` for an
observed response while having documentary state `[PENDING]` until the pin,
authorization, or reproducible tests exist. Likewise, `fork_extension` may be
accompanied by `[PROPOSED]` until an integration decision exists. Do not
confuse these dimensions with UI states such as `unsupported`,
`not_verifiable`, or `pending`.

### Parser and importer baseline

`Gadgetbridge-OW` also needs a reproducible reference before production/release
integration.
The current state is an observed local checkout, and the exact commit, tag, or
release remains `[PENDING]`; do not treat it as a release or deployment
contract. Any existing SQL helper or `--ow-db-url` option is outside the normal
integration path and is `[RISK]`/`[PENDING]` until it is removed or its
replacement is formally justified. This document does not claim that it has
already been removed.

## Vertical slices

Each slice must declare its boundary and cross the required layers without
duplicating health facts:

1. Define the use case and its versioned contract.
2. Provide a synthetic fixture when real OW is not fixed.
3. Adapt from OW or a fixture in the server-side BFF.
4. Expose a stable, sanitized BFF view model.
5. Render positive and negative states in the UI.
6. Test authorization, ownership, coverage, pagination, and errors.

The canonical first-slice strategy is: read-only health reads with respect to
OW; the BFF may create its own idempotent `VerificationRun` without mutating OW
health facts.

The first slice does not import, delete, edit, or retry OW data; does not draw
maps or routes; and does not execute SQL against OW. The only permitted write
is the `POST` for the BFF-owned `VerificationRun`. A `202 Accepted` indicates
acceptance or queuing only, never terminal persistence.

### Sync metadata policy

- `upstream_observed`: OW may expose `metadata`, `message`, or `error` with open
  and variable content; this observation does not make them a public API.
- `BFF_sanitized`: only allowlisted, aggregated, PII-free fields after
  sanitization and schema verification.
- `raw_not_public`: upstream metadata, messages, errors, and raw payloads never
  reach the browser or enter public fixtures.

Sanitization, its allowlist, and its tests remain `[PENDING]` until verified.
The local read milestone must still expose only the allowlisted projection; do
not present sanitization of raw metadata, `message`, or `error` as complete.
The BFF owns this responsibility, and the public output may only be
`BFF_sanitized` after verification.

## Expected validations

[FIXED] In `local/personal` mode, choose validations proportional to the
changed package and return real evidence. The minimum local profile is:

- Focused tests for changed code and the relevant full suite.
- `git diff --check`, Markdown and relative-link checks, and JSON/YAML parsing
  for the changed documents and fixtures.
- One disposable migration/API smoke using synthetic or ephemeral data only
  when the changed package crosses a database or OW boundary. Never use
  external SQL against OW.
- A targeted privacy/correctness review of the changed surface, including
  secrets, private paths or hosts, identifiers, health data, GPS, raw payloads,
  browser credentials, ownership, and direct OW access as applicable.

Do not require repeated exhaustive scans, backup/restore, Playwright,
production-like gates, or multiple redundant handoffs for every small local
change. Run those checks when the changed surface or an explicit
`production/release` decision requires them. `[VERIFIED]`
`ui-verification-v1.json` covers anonymous sessions and `ACCESS_BLOCKED`/`403`,
along with `409`, `429`, and `500`, without inventing real payloads.
`[PENDING]` The real HTTP runtime for session, ownership, idempotency, rate
limiting, sanitization, and errors still needs its own focused tests when that
package changes.

These validations do not authorize accidental deployment. For the first slice
and local read milestone, they are local on the laptop, offline, read-only,
dry-run, disposable, or against synthetic fixtures. Do not run Docker, Ansible,
`compose up`, migrations against real data, real imports, or deployments
without explicit separate user authorization. Production/release mode still
requires the immutable reference, backup/restore, rollback, and deployment
gates described above.

### Frontend validation

`[FIXED]` Frontend changes require a fresh simulated browser context when the
tooling is available: load the UI, interact with the changed controls, inspect
console messages and failed requests, and verify the resulting DOM and visual
state. A desktop or mobile screenshot is useful when layout or chart styling
changes. HTTP and unit checks alone do not close a UI task. Keep this browser
check proportional to the changed surface and report it as unavailable rather
than claiming browser verification when the tooling cannot run.
