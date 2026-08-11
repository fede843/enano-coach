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

## Absolute delegation

All technical searching, design, editing, implementation, testing, diff review,
privacy review, final validation, deployment, and integration are delegated to
one or more subagents through `Task`. The primary agent coordinates, divides
the work, sets scope, integrates handoffs, and communicates results.

The primary agent does not directly perform implementation, tests, diff review,
the privacy pass, or final validation; each activity is delegated to an agent
independent of the author.

If `Task` is unavailable in a parent session, stop the technical task and
request a resolution. Do not replace `Task` with direct work by the primary
agent.

Each assignment to a subagent must include relative paths, input and output
contracts, privacy boundaries, evidence classification, and expected
verification commands. The handoff must separate observed facts, proposals,
pending items, and risks.

## Parallelization and files

Read-only auditors may work in parallel, including on the same files. Only
concurrent editing of the same file is prohibited. Writing tasks may be
parallelized only when they have independent files. The primary agent assigns
one owner per file and resolves conflicts through handoffs, not simultaneous
edits.

Every technical delivery requires an independent reviewer. The reviewer must
read the diff and the produced evidence without relying on the implementer's
report. An independent privacy agent and an independent final-validation agent
must also review artifacts when the task affects them; the primary only
integrates their handoffs and does not replace those reviews. Do not declare
success without real, recent evidence: validation output, an inspected diff,
and independent handoffs.

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
uncommitted changes is not a release. Before real OW integration or deployment,
an immutable and auditable reference is required: a clean commit, immutable
tag/release, or image digest. Compatibility among the backend, frontend,
migrations, parser, and contracts must also be checked, with a backup, reviewed
migration, and documented rollback where applicable.

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

`Gadgetbridge-OW` also needs a reproducible reference before real integration.
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

Sanitization, its allowlist, and its tests remain `[PENDING]` before real
integration. Do not present sanitization of raw metadata, `message`, or `error`
as complete: the BFF owns this responsibility, and the public output may only
be `BFF_sanitized` after verification.

## Expected validations

Subagents must select validations proportional to the change and return real
evidence. When applicable, expect:

- YAML and JSON parsing, valid relative links, and `git diff --check`.
- Unit, contract, integration, and Playwright tests without real OW for the
  first slice.
- Local lint, typecheck, and build; Compose checking applies only to the later
  containerization phase and is not run to start the first slice.
- Tests for `401`, `403`, `404`, `409`, `410`, `429`, `500`, `502`, `503`,
  `504`, and date, timezone, cursor, and scope validation. `[VERIFIED]`
  `ui-verification-v1.json` already covers anonymous sessions and
  `ACCESS_BLOCKED`/`403`, along with `409`, `429`, and `500`, without inventing
  real payloads. `[PENDING]` Implement and test the real HTTP runtime for
  session, ownership, idempotency, rate limiting, sanitization, and errors.
- Scanning for secrets, private paths, internal hosts, PII, health data, and
  GPS.
- Review that the PWA caches only shell/assets and not private responses.
- Verification of migrations, idempotency, pagination, and terminal states when
  OW or an importer changes.

These validations do not authorize accidental deployment. For the first slice,
they are local on the laptop, offline, read-only, dry-run, or against synthetic
fixtures. Do not run Docker, Ansible, `compose up`, migrations against real
data, real imports, or deployments without explicit separate user
authorization, in addition to the immutable reference required above.
