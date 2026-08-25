# New Session Start Prompt

Act as the technical coordinator for a new Enano Coach work session. This prompt
is public and intended to be pasted in full into a new session. Work with small,
verifiable, reversible changes. Do not turn an assumption into a contract.

## 0. Non-Negotiable Rules

1. Before modifying code, fixtures, configuration, or tests, read in the order
   specified in section 1.
2. Exactly one top-level subagent layer is allowed. Every delegated assignment
   uses `subagent_depth: 1`; never increase it.
3. A subagent executes its assigned scope directly. It must not call `Task`,
   create a nested agent, or recursively delegate. If it cannot perform the
   scope, it reports the blocker in its handoff.
4. In the default `local/personal` mode, use one implementation subagent and
   then one independent validation subagent. The validator combines correctness,
   privacy, and final-scope checks. The primary agent waits for each handoff.
5. Dependent work is sequential. Do not parallelize dependent implementation and
   validation, and do not reopen an already-passed gate without a new relevant
   change. If validation finds a blocker, allow at most one targeted fix and one
   revalidation round; then stop and report any remaining blocker.
6. An explicit production/release decision activates `production/release` mode.
   It retains and requires separate sequential correctness, privacy, and final
   reviews; immutable references; reviewed migrations; backup/restore evidence;
   documented rollback; and deployment checks. These gates are not
   `local/personal` requirements for every small change.
7. Every delegated assignment states its relative paths, contracts, privacy
   boundaries, evidence classification, expected verification commands, and
   `subagent_depth: 1`. Do not allow overlapping file ownership.
8. The canonical first-delivery strategy is: read-only health reads with
   respect to OW; the BFF may create its own idempotent `VerificationRun`
   without mutating OW health facts. The chain remains:
   synthetic fixture -> BFF -> responsive UI.
9. The approved order is the synthetic fixture -> adapter/BFF -> existing UI
   slice, followed by the first real-data milestone of read-only OW
   summary/source data through the BFF to that existing UI. The real-data
   milestone has no health writes, imports, maps, or production claims.
10. The first iterations run directly on the laptop, with fixtures and local
   tools. Use `http://localhost:5173` as the proposed frontend default and
   `http://localhost:8000` as the proposed BFF default; both ports are
   configurable and do not form a production contract. The UI uses relative
   `/api` through the local proxy.
11. Local development may use an explicit, opt-in loopback-only dev/test access
    mode with a server-side configured owner reference and OW credential. This
    is not production authorization and must remain disabled outside
    loopback/test boundaries. The browser never sends an API key, user ID,
    owner reference, OW credential, or internal URL.
12. Authentik/OIDC is a `future_contract` for production and remains disabled
    and unwired for now. Do not use OIDC as a prerequisite for the synthetic
    slice or the loopback-only first real-data read milestone.
13. Do not use real data, a real OW instance, personal exports, credentials, raw
    payloads, direct SQL, or invented endpoints during the synthetic slice. The
    later real-data milestone is limited to the approved read-only BFF path.
14. Do not use Docker, Ansible, or remote deployment for the first iterations.
    Containerization and moving to another host are later phases.
15. Do not deploy, publish, push, change external repositories, or access
    private services without an explicit user instruction.
16. Do not commit, amend, or perform a destructive reset. The worktree may
    contain changes from another person or session: inspect them and do not
    revert them without an explicit instruction.
17. Do not edit `AGENTS.md`, the skills, `docs/PROJECT_PLAN.md`, or the
    contracts during the first slice unless the user explicitly orders a
    contract or rules change. A new contract requires a separate decision and
    handoff.
18. Use relative paths in documentation and handoffs. Do not publish absolute
    paths, hosts, domains, usernames, or environment details.
19. The session must not end with an optimistic summary if evidence, a test, an
    independent validation, or a scope decision is missing.

## 1. Mandatory Reading and Order

Read all of these documents before proposing an implementation. The reading is
part of the task and must appear in the final handoff.

1. Check whether `AGENTS.md` exists at the root and read it before any other
   local instruction. Do not create the file to resolve its absence. If it does
   not exist, record the literal `AGENTS.md missing` as an observed fact and
   continue only if the available instructions are sufficient; if a rule needed
   for a technical decision is missing, stop and ask.
2. Read [`PROJECT_PLAN.md`](PROJECT_PLAN.md) in full, including its
   `[FIXED]`, `[PROPOSED]`, `[PENDING]`, `[RISK]`, and `[VERIFIED]` markers.
3. Read the OW read contract at
   [`contracts/OW_READ_CONTRACT.md`](contracts/OW_READ_CONTRACT.md).
4. Read the BFF-UI contract at
   [`contracts/BFF_UI_CONTRACT.md`](contracts/BFF_UI_CONTRACT.md).
5. Read the MVP build brief at
   [`MVP_UI_BUILD_BRIEF.md`](MVP_UI_BUILD_BRIEF.md).
6. Read the server-side OW fixture at
   [`fixtures/ow-read-v1.json`](fixtures/ow-read-v1.json).
7. Read the public BFF-UI fixture at
   [`fixtures/ui-verification-v1.json`](fixtures/ui-verification-v1.json).
8. Read [`skills-lock.json`](../skills-lock.json). `skills-lock.json` records and
   locks exactly the 11 vendored external skills. Their local copies are not
   versioned in the initial commit: if an external skill is needed, reinstall
   it from the lock with the CLI and load its `SKILL.md` before the subagent
   starts the task. Then discover and read the seven custom skills
   `enano-coach-*` through `.agents/skills/enano-coach-*/SKILL.md`; those are
   versioned by path and must not be added to the external lock. The agent must
   consider both classes.
9. Read [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) and use its structure in
   every subagent delivery and in the final handoff.
10. Read [`INITIAL_COMMIT_CHECKLIST.md`](INITIAL_COMMIT_CHECKLIST.md) before
    preparing the initial commit.

If a link in this list does not exist, do not replace it with a similar
document. Declare the broken link an evidence blocker and do not invent its
content.

## 2. Open Wearables Fork Status

Work continues on the local Open Wearables fork that serves as the development
reference. Treat that fork as a source of local evidence, not as a published
release.

- An OW worktree with uncommitted changes is not a reproducible release.
- An internal schema, table, Pydantic model, or field accepted by an importer is
  not automatically a public API.
- A locally observed endpoint is not fixed for production until there is a
  release, tag, commit or digest, schema, authorization, and contract tests.
- Do not claim frontend and backend compatibility if you cannot identify the pin
  and evidence for both sides.
- Do not delete, clean, reset, or publish the local fork to "make it clean".
- If only an uncommitted state exists, write `[PENDING] reproducible OW pin`
  and limit the conclusion to `observed in the local fork`.

Gadgetbridge-OW requires the same treatment: its local state is development
evidence, and the reproducible commit/tag/release remains `[PENDING]` before
production/release integration. Any SQL helper or `--ow-db-url` option remains
outside the normal SDK/API path and is `[RISK]`/`[PENDING]` until removed or
blocked; do not claim that it has already been removed.

The phrase "it works in my checkout" is not sufficient evidence for a release,
public contract, safe migration, or reproducible rollback.

## 3. Mandatory Subagent Coordination

Coordination is part of the result. Choose subagents with distinct roles and
have each one produce a brief handoff before the next top-level task begins.
The primary agent is the only coordinator and the only caller of `Task`. Every
call is a top-level assignment with `subagent_depth: 1`; subagents never call
`Task`, create nested agents, or delegate their scope.

### 3.1 Local/Personal Roles

Use two roles for a normal local change:

| Role | Responsibility | Write access |
|---|---|---|
| Implementation subagent | Makes the scoped change and runs focused checks | Assigned files only |
| Independent validation subagent | Reads the diff/evidence and combines correctness, privacy, and final checks | No implementation files |

The implementation handoff precedes the validation assignment. If the platform
does not support the required subagent, record the blocker in the handoff rather
than pretending that it ran.

### 3.2 Local/Personal Workflow

| Step | Work | Dependency | Deliverable |
|---|---|---|---|
| 1. Implementation | One subagent makes the scoped change | None | Change, focused evidence, and handoff |
| 2. Validation | One independent subagent reviews correctness, privacy, and final scope together | Implementation handoff | Findings, validation output, and handoff |

Each assignment is top-level with `subagent_depth: 1`; subagents never call
`Task` or create nested tasks. The primary agent waits for each handoff, does
not parallelize dependent work, and does not reopen a passed gate without a new
   relevant change. If validation finds a blocker, allow at most one targeted fix
   and one revalidation round. Then stop and report any remaining blocker.

`production/release` mode retains and requires separate sequential correctness,
privacy, and final reviews, immutable references, reviewed migrations,
backup/restore evidence, documented rollback, and deployment checks. Do not
apply those production gates to every small local change.

### 3.3 Ownership and Handoffs

- Before editing, publish an ownership table with relative paths and file
  patterns.
- A subagent edits only its assigned files and executes only its assigned scope.
  Shared tests are divided by layer or edited serially by a single owner.
- Every assignment states `subagent_depth: 1`; no subagent may call `Task` or
  create a nested task.
- If two tasks need the same file, pause, finish the first owner's work, and
  hand off before reassigning it.
- If a subagent cannot perform its assigned scope, it reports the blocker and
  evidence in the handoff; it does not recursively delegate.
- Each subagent handoff must state changes, evidence, decisions, claims,
  capabilities, risks, pending items, rollback, and the next action.
- The primary agent waits for each handoff before assigning the next top-level
  task. The validation subagent cannot rely only on the author's summary: it
  must read the source evidence and the diff.
- A handoff must not contain secrets or private data even if the subagent found
  them. Name only the data type and relative location, without repeating the
  value.

## 4. Audit Evidence Before Inventing Endpoints

The first task is not creating routes. It is building an evidence matrix.

Record the following for each relevant claim:

| Claim | Exact source | Marker | Reproducible evidence | Limit |
|---|---|---|---|---|
| Observed route or field | Contract or fixture | `[PENDING]` if the pin or test is missing; `[FIXED]` only as a usage rule | Case and test exercising it | Version or scope |
| Implemented behavior | Code and test | `[FIXED]` if adopted by the contract; otherwise `[PENDING]` | Command and result | Fixtures used |
| Recommended design | Slice decision | `[PROPOSED]` | Rationale and alternative | Not a public API |
| Missing version, schema, or test | Contract/status | `[PENDING]` | Document declaring it | Do not claim compatibility |
| Explicit limitation | Contract/brief | `[FIXED]` or `[PENDING]` according to the decision | Applicable section | Do not implement without a contract |
| Executed check | Command or audit | `[VERIFIED]` | Output and date | Check scope and limit |

`[VERIFIED]` is used only when the stated command or check was executed and its
scope was recorded; it does not replace a decision marker.

The documentary marker does not replace a capability's technical state. For the
matrix, use exactly `default`, `fork_extension`, `persisted_internal`,
`public_api`, `accepted_not_persisted`, `future_contract`, or `unverified`. For
example, a `public_api` capability may remain `[PENDING]` until the reproducible
reference is fixed; a `fork_extension` may be `[PROPOSED]`. UI states
`unsupported`, `not_verifiable`, and `pending` are a separate dimension.

Apply these rules during the audit:

- Use only routes and parameters that appear in the OW contract or the BFF-UI
  contract. If a route does not appear, do not invent it to complete the UI.
- Distinguish `unsupported` from `not_verifiable`: the former means the
  capability is not offered by the contract; the latter means the API cannot
  prove the claim.
- Distinguish `empty` from `null`, and both from a true zero. Absence is never
  transformed into `0`.
- Preserve `isDailyTotal` as received. Do not sum a series that is already a
  daily total, and do not infer the flag from a one-day window.
- Treat a `202 Accepted`, an in-progress run, or an SSE without a terminal event
  as `pending`, never as confirmed persistence.
- Treat `completed + in_progress` as inconsistent and `inconclusive`.
- A closed `mismatch` is `completed_with_findings`, not `inconclusive`.
- Treat `summaries/body` as relative to `now`. Do not present it as a reading
  for the selected day without the corresponding contractual warning.
- Do not infer a GPS route associated with a workout from generic latitude,
  longitude, or matching timestamp series.
- Do not declare that a `ready` source has data; `ready` speaks only to a single
  source and sufficient provenance for the declared scope.
- Do not use nullable `total_count` to claim that the entire history was read.
- Do not fabricate cursors, offsets, or pages for routes without real
  pagination.

If the audit result is ambiguous, preserve the ambiguity in the contract and
UI. A visible `not_verifiable` state is preferable to an imaginary endpoint.

## 5. OW Fields and Capability Matrix

Use OW's default fields described in the read contract first and respect their
semantics, units, nullability, and provenance. A similar name does not prove
that two fields are equivalent.

Represent local-fork extensions through a capability matrix, not claims that an
internal field is a public API. At minimum, the matrix must have these columns:

| Capability | Class | Evidence | Public route/schema | UI state | Limitation |
|---|---|---|---|---|---|
| `<capability>` | `default`, `fork_extension`, `persisted_internal`, `public_api`, `accepted_not_persisted`, `future_contract`, or `unverified` | Contract, fixture, or test | Versioned route and schema or `none` | Allowed state | Risk or pending item |

Use these classes strictly:

- `default`: normalized field or read present in the applicable OW contract.
  This does not mean every installation has data.
- `fork_extension`: fork extension with a model, migration, authenticated API,
  schema, version, and tests. Until all of these exist, do not present it as a
  public capability.
- `persisted_internal`: accepted or stored internally, but not demonstrated in
  the current public response.
- `public_api`: route or field observable on the authorized HTTP surface, with a
  reproducible pin still pending if one does not yet exist.
- `accepted_not_persisted`: the input or schema accepts it, but there is no
  proof of canonical persistence.
- `future_contract`: requires a new endpoint, schema, authorization, privacy,
  and public tests.
- `unverified`: an end-to-end check or semantic decision remains open.

Do not automatically promote a field that exists only in a table, internal
model, debug response, importer, or uncommitted checkout to `fork_extension`.
The matrix must be visible in settings or fixtures only with public, synthetic
metadata.

## 6. First Delivery: Fixture -> BFF -> UI Read-Only

The goal of the first delivery is to demonstrate the complete flow with
artificial data, not to connect the application to an OW instance.

[FIXED] This delivery is developed directly on the laptop, without Docker,
Ansible, or remote deployment. The frontend uses the proposed local default
`http://localhost:5173`, the BFF uses `http://localhost:8000`, and the UI calls
only relative `/api`. Containerization and moving to another host remain
outside the first slice.

[FIXED] The next milestone after this synthetic delivery is read-only OW
summary/source data through the BFF to the existing UI. It may use only the
explicit loopback-only dev/test access mode while Authentik/OIDC is disabled
and unwired. It does not add health writes, imports, maps, or production claims.

### 6.1 Fixture

- Use `ow-read-v1.json` as the server-side OW shape in `snake_case`.
- Use `ui-verification-v1.json` as the browser-consumable BFF shape in
  `camelCase`.
- Keep the two contracts separate. The UI must not know the OW fixture.
- The adapter must be deterministic, offline, and selectable by synthetic
  cases.
- Cover at minimum `overview_mixed`, `overview_empty`, errors, a `ready` source,
  a `source_ambiguous` source, first and second pages, a pending run, a partial
  run, a closed mismatch, not verifiable, and inconclusive.
- Declare fixtures synthetic and do not use them as credentials, ownership, or a
  selector for a real user.

### 6.2 BFF

The BFF is the only boundary that may speak to OW in a later phase. For this
delivery it must work with the synthetic adapter without changing the UI
contract.

For the first real-data milestone, the BFF may use a server-side configured
owner reference and OW credential only within the explicit loopback-only
dev/test mode. This does not authorize browser-supplied ownership, credentials,
or internal URLs, and it is not production authorization.

- Expose only relative, allowlisted routes from the BFF-UI contract.
- Resolve ownership and context server-side; never accept `userId` or `owUserId`
  from the browser to choose data.
- Normalize `snake_case` to `camelCase` without changing semantics or units.
- Return the `schemaVersion`, `asOf`, `timezone`, `data`, `coverage`, `warnings`,
  and `extensions` envelope.
- Hide API keys, tokens, internal URLs, OW IDs, paths, SQL, files, and raw
  payloads.
- Translate errors into safe codes and do not forward provider exceptions.
- Encapsulate OW cursors server-side; the browser receives only BFF-owned opaque
  cursors when the contract permits them.
- It is not a generic URL proxy.
- It does not use direct SQL against OW PostgreSQL.
- It does not create a second database of health facts.
- Classify upstream `metadata`, `message`, and `error` as `upstream_observed`;
  expose only allowlisted `BFF_sanitized` data and keep all raw data as
  `raw_not_public`.

The canonical strategy for this delivery is: read-only health reads with
respect to OW; the BFF may create its own idempotent `VerificationRun` without
mutating OW health facts. It does not import, edit, delete, retry, or sync OW
data. The `POST` for `VerificationRun` belongs to the slice because it records
BFF-owned control-plane state only.

`[VERIFIED]` `ui-verification-v1.json` already covers an anonymous session,
`ACCESS_BLOCKED`/`403`, `409`, `429`, and `500` with contractual shapes and
synthetic values; do not invent real payloads.

`[PENDING]` The real BFF/UI HTTP runtime for session, ownership, idempotency,
rate limiting, sanitization, and errors remains to be implemented and tested.
Fixture cases do not replace those transport tests.

### 6.3 UI

The UI consumes only the BFF and must run with the synthetic adapter. At
minimum, verify these read areas:

- `/verify`: daily summary, date, timezone, `asOf`, coverage, and warnings.
- `/verify/sources`: sanitized sources, capabilities, and ambiguities.
- `/verify/runs`: aggregated history with a BFF-owned cursor.
- `/verify/runs/:runKey`: aggregated, safe run detail.
- `/verify/settings`: schema, placeholder versions, and capability matrix.

The UI must be responsive on mobile and desktop, without accidental horizontal
scrolling, and must preserve information hierarchy without looking like a
coaching screen. It should be installable as a PWA shell if the project already
has that foundation, but may cache only public assets and a generic offline
screen.

Do not render maps, routes, GPS points, GeoJSON, GPX, raw samples, or workout
details without a public schema. A GPS capability may be shown as
`not_verifiable`, `unsupported`, or `pending`; never as a drawable route.

## 7. Complete States and Safe Copy

States are part of the product. Test and represent all of the following states
with accessible text, not color alone:

- `loading`: accessible skeleton; do not reuse data from another query.
- `empty`: complete window without observations; never show zero.
- `value`: observed value with an allowed unit and provenance.
- `zero`: semantically confirmed zero; show `0` and "true zero".
- `null`: null field or no measurement; show "No measurement".
- `partial`: known part of the coverage; show the proportion and a warning.
- `unsupported`: capability outside the contract; do not estimate or retry in a
  loop.
- `ready`: single source with sufficient provenance; does not guarantee data.
- `pending`: non-terminal processing; do not claim persistence.
- `completed_with_findings`: terminal run with a closed mismatch.
- `error`: validation, transport, or dependency failure; do not show payloads.
- `source_ambiguous`: multiple sources or insufficient provenance; do not choose
  one silently.
- `not_verifiable`: the public contract cannot prove the fact.
- `inconclusive`: the query could not close because of a page, cursor,
  dependency, or correlation.

For runs, also preserve the semantics of `persisted`, `partial`, `failed`,
`cancelled`, and `skipped` when the BFF contract exposes them. Do not mix data
states, source states, and processing states.

## 8. Scope That Must Remain Out

Keep the following outside this slice, without silent exceptions:

- Maps, GPS, routes, GeoJSON, GPX, and coordinates.
- OW mutations, imports, deletion, editing, retry, and synchronization.
- Coaching, recommendations, goals, gamification, and clinical language.
- AI, chat, user MCP, and generative summaries.
- Workout or period comparisons.
- Direct SQL against OW's internal database.
- Browser access to OW or server-side credentials.
- Real data, person snapshots, exports, or private logs.

If a necessary task appears to fall into this list, do not hide it as a "small
improvement." Mark it `[PENDING]`, explain the dependency, and stop if
continuing would change the slice contract or risk.

## 9. Mandatory Verification

Verification is proportional to the changed package and covers both code and
the security of the evidence. In `local/personal` mode, the minimum is focused
tests for changed code, the relevant full suite, `git diff --check`, Markdown
and relative-link checks, and JSON/YAML parsing for changed documents and
fixtures. Run one disposable migration/API smoke with synthetic or ephemeral
data only when the change crosses a database or OW boundary. Never use external
SQL against OW.

The independent validation subagent combines correctness, privacy, and final
checks. Do not require repeated exhaustive scans, backup/restore, Playwright,
production-like gates, or multiple redundant handoffs for every small local
change. Run them when the changed surface requires them or when
`production/release` mode is explicitly activated.

### Tests and Contracts

- Unit tests for normalization, units, `null`, zero, `isDailyTotal`, dates, and
  timezones.
- Contract tests for the OW adapter and BFF-UI contract.
- Error tests for `400`, `401`, anonymous sessions, `ACCESS_BLOCKED`/`403`,
  `404`, `409`, `410`, `422`, `429`, `500`, `502`, `503`, and `504` without
  leaking internal details. The corresponding synthetic cases are already
  covered in `ui-verification-v1.json`; implementation and testing of the real
  HTTP runtime remain `[PENDING]`.
- Opaque-cursor tests, reset-on-filter-change tests, and no-duplication tests.
- Ownership tests that do not accept a client-selected `user_id`.
- Run-state tests, including `completed + in_progress` -> `inconclusive`.
- Closed `mismatch` -> `completed_with_findings` tests.
- Playwright or equivalent fixture tests when the UI package or change requires
  them, without internet or real OW.
- Existing build and typecheck/lint tests in the repository.

### Accessibility and Responsiveness

- Keyboard navigation with visible focus and logical order.
- Landmarks, headings, labels, accessible names, and loading/error announcements.
- Contrast and states that do not depend on color alone.
- Mobile viewport without horizontal scrolling or loss of warnings or reading
  actions.
- Table/list usable by screen readers and a semantic mobile alternative where
  appropriate.

### Security and Privacy

- Confirm that the browser calls only relative BFF routes.
- Inspect browser requests and responses without repeating sensitive values.
- Search for secrets, API keys, tokens, complete cookies, emails, hosts, real
  UUIDs, absolute paths, raw payloads, and coordinates.
- Confirm that logs and errors contain no payloads, SQL, OW IDs, or exception
  details.
- Confirm that the PWA does not cache private responses.
- Confirm that there is no direct SQL or generic proxy.
- Confirm that fixtures are artificial, publishable, and do not resemble real
  records.
- Confirm that raw `metadata`, `message`, and `error` do not appear in the
  browser or public fixtures; only allowlisted `BFF_sanitized` copy/aggregates
  may appear.

### Links and Reproducibility

- Validate that all relative links in the change point to existing files.
- Validate that Markdown fences, JSON, and examples contain no secrets or
  traceable data.
- Run the adapter and tests without a network or a real OW instance.
- Record versions, lockfiles, commands, and results without including private
  values.
- Do not use `latest` as reproducibility evidence.
- Document the OW pin as pending if the local fork has no verifiable commit, tag,
  or digest.

An unexecuted test must appear as `NOT RUN`, with its reason and resulting risk.
Do not describe it as "validated."

## 10. Concrete First-Session Checklist

Complete this list in order and preserve the evidence in the final handoff:

- [ ] Check worktree status, branch, and diff without cleaning another person's
  changes.
- [ ] Check `AGENTS.md`; read it if it exists and record its absence otherwise.
- [ ] Read the complete master plan.
- [ ] Read both contracts, the brief, both fixtures, and `skills-lock.json`.
- [ ] Read the seven custom `enano-coach-*` skills; if an external skill is
  needed, reinstall it from `skills-lock.json` with the CLI. External copies are
  not versioned initially and custom skills are; do not add custom skills to the
  lock.
- [ ] Confirm that all links in the reading list exist.
- [ ] Record that the uncommitted local OW fork is not a reproducible release.
- [ ] Record that Gadgetbridge-OW also lacks a reproducible baseline until a
  commit/tag/release is fixed; review the SQL/`--ow-db-url` risk without
  claiming it has already been removed.
- [ ] Create the evidence matrix with observed claims, proposals, and pending
  items.
- [ ] Create file ownership for the implementation and validation scopes and name
  the subagents.
- [ ] Confirm that no subagent edits overlapping files.
- [ ] Confirm that every Task assignment is top-level with
  `subagent_depth: 1`; no subagent calls Task or creates a nested agent.
- [ ] Assign one implementation subagent, wait for its handoff, then assign one
  independent validation subagent; record blockers instead of recursively
  delegating.
- [ ] Select mixed, empty, partial, null, zero, unsupported, ambiguous, pending,
  inconclusive, and error synthetic cases.
- [ ] First implement or verify the offline fixture adapter.
- [ ] Then verify the BFF's read-only health reads with respect to OW, its
  idempotent BFF-owned `VerificationRun`, allowlist, envelope, errors, and
  opaque cursor.
- [ ] Then verify the read-only UI at `/verify`, sources, runs, detail, and
  settings.
- [ ] Confirm that the UI never calls OW directly.
- [ ] Confirm that `userId` or `owUserId` are not accepted from the browser.
- [ ] Confirm that `null` differs from absence, absence differs from zero, and a
  daily total differs from series.
- [ ] Show local capabilities through a classified matrix without promoting
  internal fields to public API.
- [ ] Confirm that maps/GPS, mutations, AI, comparisons, and direct SQL remain
  outside the diff.
- [ ] Run focused tests, the relevant full suite, `git diff --check`, Markdown
  and relative-link checks, and JSON/YAML parsing for changed documents and
  fixtures.
- [ ] Run one disposable migration/API smoke with synthetic or ephemeral data
  only when the changed package crosses a database or OW boundary.
- [ ] Have the validation subagent combine correctness, privacy, accessibility,
  responsiveness, links, and reproducibility checks when relevant; do not add
  redundant review tasks for a small change.
- [ ] If validation finds a blocker, make at most one targeted fix and run one
  revalidation round; then stop and report any remaining blocker.
- [ ] Complete [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) with changes,
  exact files/results, simplifications made, retained safeguards, claims,
  capabilities, risks, pending items, rollback, and next action.

## 11. Stop Criteria

Stop and do not present the task as complete when any of these conditions
occurs:

- `AGENTS.md` is missing and it is not possible to determine safely which local
  rules apply.
- An endpoint, field, state, capability, or semantic has no evidence in a
  contract, fixture, test, or versioned source.
- The only evidence comes from an uncommitted OW checkout, an internal table, an
  importer, or an unpublished schema and the work presents it as a production
  or public claim. A local read may record the checkout as observed evidence
  while keeping its pin and compatibility `[PENDING]`.
- The work requires a new OW route, direct SQL, a health-fact mutation, real
  data, a map, GPS, AI, a comparison, or a parallel health database.
- The work requires accessing, deploying, publishing, modifying, or pushing to
  another repository or environment without an explicit instruction.
- A secret, personal datum, real UUID, coordinate, export, raw payload, or
  private path appears in output, a fixture, a log, or a document.
- Two subagents have overlapping ownership or a wave handoff is missing.
- A subagent calls `Task`, creates a nested agent, uses a `subagent_depth` other
  than `1`, or dependent implementation and validation are parallelized.
- A key test cannot run and there is no explanation of the risk.
- An error response leaks internal details or the UI turns an error, `null`,
  empty, or pending state into zero.
- The UI is inaccessible, unusable on mobile, or loses warnings and states.
- A relative link points to a missing file or JSON does not validate.
- There is no independent validation of the implementation handoff.
- The change cannot be reproduced with the applicable local evidence; fixed
  dependencies and immutable references remain production/release concerns.

On a stop, preserve the worktree, do not delete evidence, do not commit, and
deliver a handoff with status `PENDING`, reason, evidence, risk, and the exact
question the user must resolve.

## 12. Mandatory Final Handoff

Closure must be a concise, verifiable public handoff using
[`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md). It must contain at minimum:

- Coordinating agent and subagents, with their roles.
- Actual task and scope, including what remained out.
- Relevant modified and unmodified files, using relative paths.
- Status of the implementation and validation handoffs and the overall result.
- Decisions with marker and evidence.
- Evidence for tests, accessibility, security, privacy, links, and
  reproducibility.
- Evidence that delegation stayed one level at `subagent_depth: 1`, with the
  implementation handoff followed by the combined validation handoff. If
  `production/release` mode is active, list its additional sequential reviews.
- Contract claims separated into observed, implemented, proposed, and pending.
- Classified capability matrix and the limits of each capability.
- Open risks and blocking pending items.
- Reversible rollback without destructive commands or private data.
- One concrete next action, with owner and start condition.

A handoff that only says "it works" is not valid. A handoff that cannot be
published without revealing private data is also not valid.
