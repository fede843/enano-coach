# Public Handoff Template

Use this document to close a work wave, review, or session. It is public and
reusable. Complete the fields with synthetic evidence and relative paths. Delete
instructions in angle brackets when they do not apply, but keep the important
fields and mark anything that could not be verified.

## 0. Security and Privacy Rule

Do not write the following in this handoff:

- Secrets, API keys, tokens, passwords, credential hashes, or complete cookies.
- Personal data, real emails, real names, exports, dumps, private logs, or real
  biometric values.
- Real UUIDs, traceable IDs, MACs, serial numbers, coordinates, or GPS routes.
- Raw payloads from OW, the BFF, importers, or providers.
- Hosts, private domains, absolute paths, signed URLs, or private-environment
  file names.
- Authentication headers with values, SQL, stack traces, or rendered
  configuration.

Use synthetic names such as `verify-demo-01`, `<opaque-id>`,
`user@example.invalid`, `https://api.example.test`, and `<redacted>`. If you
find a secret or private datum, report only its type and the relative path where
it was detected. Do not copy the value into the handoff, a test, a screenshot,
or the agent response.

## 1. Identification

- Coordinating agent: `<public agent name or identifier>`
- Subagents and roles: `<role -> public identifier>`
- Workflow mode: `local/personal` or `production/release`
- Delegation: `local/personal: one implementation -> one independent validation; top-level only; subagent_depth: 1`
- Execution rule: `<subagents performed only their assigned scope; no nested Task or delegation>`
- Session date: `<YYYY-MM-DD>`
- Wave: `<local implementation | local validation | production/release review>`
- Task: `<brief, concrete description>`
- Overall status: `DONE`, `IN PROGRESS`, `PENDING`, or `BLOCKED`
- Approved scope: `<what could be changed>`
- Uncompleted scope: `<what was left out and why>`
- Explicit user instruction required: `<yes/no; public detail>`

## 2. Executive Summary

In a few sentences, describe what was observed, what was implemented, and what
cannot be claimed. Do not use release language if the fork or dependencies are
not fixed reproducibly.

Text:

> `<Verifiable summary. Clearly separate observed result, completed change, and limitations.>`

### 2.1 Local/Personal Simplifications And Safeguards

- Simplifications made: `<reduced waves, proportional checks, or omitted tooling>`
- Retained safeguards: `<secrets, ownership, SQL, health-fact, loopback, read-only, and claim boundaries>`
- Production/release items deliberately not applied: `<immutable reference, backup/restore, rollback, deployment, or separate reviews>`

## 3. Files and Ownership

Use paths relative to the repository. Do not include absolute paths or private
file listings.

| Action | Relative path | Owner | Reason | Status |
|---|---|---|---|---|
| `<created/modified/reviewed>` | `<path/relative>` | `<agent>` | `<reason>` | `DONE` / `PENDING` |

Files deliberately not touched:

- `AGENTS.md`: `<read/does not exist/not touched by scope>`
- `docs/PROJECT_PLAN.md`: `<not touched unless explicitly ordered>`
- Skills and `skills-lock.json`: `<lock external skills and seven custom skills read/not touched/reason>`
- Contracts: `<not touched or list changes with a separate decision>`

`skills-lock.json` records and locks exactly the 11 vendored external skills.
The seven custom `enano-coach-*` skills are discovered by path, versioned under
`.agents/skills/`, and must not be added to the external lock. Local copies of
external skills are not versioned initially; reinstall them from the lock with
the CLI when needed. The handoff must state that both classes were read when
applicable.

Ownership conflicts:

- `<none, or describe the conflict, owner, and how it was serialized>`
- `<Every assignment was top-level and sequential; a blocker was reported rather
  than recursively delegated>`

## 4. Wave Status

| Wave or subagent | Role | Handoff received | Assigned files | Result |
|---|---|---|---|---|
| `<wave/role>` | `<responsibility>` | `YES` / `NO` | `<relative paths>` | `DONE` / `PENDING` |

If a handoff is missing, mark the row `PENDING`. Do not consider it complete by
inference. In `local/personal` mode, record one implementation row followed by
one independent validation row. Each delegated row is top-level with
`subagent_depth: 1`; the coordinator waits before assigning dependent work.
Subagents execute their assigned scope directly and must not call `Task` or
create nested agents. A subagent that cannot perform its scope reports the
blocker in its handoff.

The validation row combines correctness, privacy, and final-scope evidence. Do
not add redundant review rows for a small local change. If
`production/release` mode is active, list its separate correctness, privacy, and
final reviews and its immutable-reference, backup/restore, rollback, and
deployment evidence.

## 5. Decisions

Every decision must have a marker and evidence. Do not present a proposal as a
fixed decision.

| ID | Marker | Decision | Reason | Evidence | Impact |
|---|---|---|---|---|---|
| `<D-XX>` | `[FIXED]`, `[PROPOSED]`, `[PENDING]`, `[RISK]`, or `[VERIFIED]` | `<text>` | `<why>` | `<file/section/test>` | `<affected layers>` |

Unresolved decisions:

- `<pending decision, owner, and condition for resolving it>`

## 6. Guide to Marking Facts and Proposals

Use these markers literally to avoid ambiguous claims:

| Marker | Permitted use | Safe public example |
|---|---|---|
| `[FIXED]` | Decision or boundary adopted by the delivery | `[FIXED] The BFF hides the OW identifier from the browser response.` |
| `[PROPOSED]` | Recommended design not yet tested or fixed | `[PROPOSED] Use a replaceable adapter for OW and fixtures.` |
| `[PENDING]` | Missing decision, version, schema, test, or authorization | `[PENDING] Fix the reproducible OW commit or digest.` |
| `[RISK]` | Known problem that may invalidate a conclusion | `[RISK] An upstream cursor may not have sufficient retention.` |
| `[VERIFIED]` | Check executed with recent evidence and explicit scope | `[VERIFIED] The synthetic JSON passes the local parser.` |

Writing rules:

- A green test proves the case it covers, not the entire API or an entire
  release.
- A field present in a schema proves shape, not necessarily persistence.
- An endpoint observed in an uncommitted fork is described as local evidence,
  not a production contract; it normally remains `[PENDING]`.
- An internal capability uses the canonical technical taxonomy and is not
  promoted to `public_api` until it has an API, schema, authorization, version,
  and tests.
- `[VERIFIED]` does not replace a scope decision or promote a capability; it
  records only a specific check and its limit.
- If you cannot link to or name the evidence without exposing private data,
  write `[PENDING] insufficient public evidence`.
- Do not use "safe," "complete," "compatible," or "reproducible" without
  stating the exact test scope.

## 7. Test Evidence

Record sanitized commands, the actual result, and limitations. Do not paste
payloads, complete logs, tokens, private URLs, or output containing personal
data. For `local/personal`, record focused tests for changed code, the relevant
full suite, `git diff --check`, Markdown/relative-link checks, JSON/YAML parsing,
and a disposable migration/API smoke only when the change crosses a database or
OW boundary. Mark non-applicable checks `NOT RUN` with the reason and risk; do
not imply that Playwright, backup/restore, or production-like checks are
required for every small local change.

| Area | Command or test | Result | Date | Public evidence | Limitation |
|---|---|---|---|---|---|
| Unit | `<command without secrets>` | `PASS` / `FAIL` / `NOT RUN` | `<YYYY-MM-DD>` | `<relative test or summary>` | `<scope>` |
| OW contract | `<command>` | `PASS` / ... | `<date>` | `<fixture/case>` | `<pin or limit>` |
| BFF-UI contract | `<command>` | `PASS` / ... | `<date>` | `<relative test>` | `<scope>` |
| Integration | `<command>` | `PASS` / ... | `<date>` | `<summary>` | `<dependency>` |
| UI/Playwright | `<command>` | `PASS` / ... | `<date>` | `<cases>` | `<fixtures used>` |
| Accessibility | `<command or audit>` | `PASS` / ... | `<date>` | `<summary>` | `<devices>` |
| Responsive | `<viewport or test>` | `PASS` / ... | `<date>` | `<summary>` | `<scope>` |
| Security | `<scanner or review>` | `PASS` / ... | `<date>` | `<summarized findings>` | `<limits>` |
| Privacy | `<file and request review>` | `PASS` / ... | `<date>` | `<summary>` | `<scope>` |
| Links/Markdown | `<checker or review>` | `PASS` / ... | `<date>` | `<verified paths>` | `<limits>` |
| Reproducibility | `<offline/build command>` | `PASS` / ... | `<date>` | `<public versions>` | `<pending pin>` |

For each failure, include the test identifier or a short description, impact,
owner, and next action. A `NOT RUN` result always includes a reason and risk; it
never equals `PASS`.

## 8. Contract Claims

Separate what the contract permits you to claim from what the code does and
what is still proposed. Do not copy raw responses.

| Claim | Marker | Source | Evidence | Scope | Limit or warning |
|---|---|---|---|---|---|
| `<concrete claim>` | `[FIXED]` / `[PROPOSED]` / `[PENDING]` / `[RISK]` / `[VERIFIED]` | `<file/section>` | `<fixture/test/diff>` | `<route/case>` | `<what it does not prove>` |

Claims that must not appear without additional tests:

- "OW publishes" when only an internal model or importer field exists.
- "Persisted" when only `202 Accepted` was received or a non-terminal run
  exists.
- "No data" when the page, retention, or source could not be closed.
- "GPS available" when there is no unambiguous public association with the
  workout.
- "Production-ready" when a pin, authorization, backup, restore, or contract
  tests are missing.

## 9. Capability Matrix

Classify every capability without promoting local implementations to public API.

Permitted classes:

- `default`: normalized field or read from the applicable OW contract.
- `fork_extension`: formal extension with a model, migration, authenticated API,
  versioned schema, and tests.
- `persisted_internal`: accepted or stored internally, but not demonstrated in
  the current public response.
- `public_api`: route or field observable on the authorized HTTP surface.
- `accepted_not_persisted`: the input or schema accepts it, but there is no
  proof of canonical persistence.
- `future_contract`: requires a new endpoint, schema, authorization, privacy,
  and public tests.
- `unverified`: an end-to-end check or semantic decision remains open.

| Capability | Class | Public source | Route/schema | Exposed by BFF | UI presentation | Risk/pending |
|---|---|---|---|---|---|---|
| `<capability>` | `<class>` | `<contract/fixture/test>` | `<route or none>` | `YES` / `NO` | `<visible state>` | `<limit>` |

An `fork_extension` row requires evidence for every formal component. If one is
missing, use `unverified`, `accepted_not_persisted`, or the applicable technical
class and explain why. UI states such as `unsupported`, `not_verifiable`, and
`pending` are recorded separately and do not replace the class. Never write
internal IDs, database paths, payloads, or raw fields in this table.

The canonical first-slice strategy is: read-only health reads with respect to
OW; the BFF may create its own idempotent `VerificationRun` without mutating OW
health facts. A capability may have a technical class and a different
documentary marker: for example, `public_api` with `[PENDING]` until the pin is
fixed, or `fork_extension` with `[PROPOSED]` until integration is closed.

For sync, always record the metadata crosswalk: `upstream_observed` for OW's
open shape, `BFF_sanitized` for allowlisted fields, and `raw_not_public` for
anything that cannot cross to the browser or enter public fixtures.

## 10. Risks

| ID | Marker | Risk | Probability/impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| `<R-XX>` | `[RISK]` | `<description without private data>` | `<low/medium/high>` | `<action>` | `<agent>` | `OPEN` / `MITIGATED` |

Technical risks to review when applicable:

- OW fork without a reproducible commit, tag, or digest.
- Observed contract that may change between versions.
- Field accepted but not proven to be persisted.
- Ambiguous source or possible double counting.
- `null`, empty, zero, partial, and pending confused by the UI.
- Expired cursor, missing page, or incorrectly used `total_count`.
- API key, `user_id`, token, SQL, internal URL, or payload exposed to the
  browser.
- PWA cache of private responses.
- Missing keyboard, screen-reader, or mobile-viewport coverage.
- Fixtures that are too perfect, non-synthetic, or not runnable offline.
- Upstream `metadata`, `message`, or `error` treated as API without
  sanitization.
- Local Gadgetbridge-OW baseline or SQL/`--ow-db-url` helper used as the normal
  integration path without first establishing its reproducible status.

## 11. Pending Items and Blockers

| ID | Pending item or blocker | Why it matters | Missing evidence | Owner | Start condition |
|---|---|---|---|---|---|
| `<P-XX>` | `<text>` | `<impact>` | `<what is missing>` | `<agent/user>` | `<condition>` |

Inherited pending items:

- Reproducible OW pin: `<release/tag/commit/digest or PENDING>`
- Server-side header and authentication: `<status without secret values>`
- Public schemas for extensions: `<status>`
- Endpoint and schema for route, laps, samples, `segments`, or `hrZones`:
  `<out of scope or PENDING>`
- Reproducible Gadgetbridge-OW baseline: `<commit/tag/release or PENDING>`
- Removal or blocking of the SQL/`--ow-db-url` helper: `<PENDING; do not claim it has already been removed>`
- Sanitization of `metadata`, `message`, and `error`: `<PENDING>`
- Production Authentik/OIDC: `[PENDING]` `future_contract`, disabled and
  unwired until a separately approved production phase.
- First real-data milestone: `[PENDING]` read-only OW summary/source data
  through the BFF to the existing UI, using only explicit loopback-only
  dev/test access with server-side owner/credential configuration; no health
  writes, imports, maps, or production claims.
- Synthetic BFF fixture coverage for anonymous session,
  `ACCESS_BLOCKED`/`403`, `409`, `429`, and `500`: `[VERIFIED]` in
  `fixtures/ui-verification-v1.json`; no real payloads.
- Real HTTP runtime for session, ownership, idempotency, rate limiting,
  sanitization, and errors: `[PENDING]`
- Deployment, backup, and restore policies: `<PENDING if not verified>`

## 12. Rollback

Describe a reversible action limited to this wave's change. Do not use
`git reset --hard`, `git clean`, volume deletion, or destructive commands. Do not
include secrets or absolute paths.

- Rollback condition: `<what signal activates it>`
- Affected files or feature flag: `<relative paths>`
- Reversible action: `<how to disable or revert without destroying data>`
- Data impact: `<none / describe synthetic data only>`
- Post-rollback validation: `<tests or checks>`
- Unverified rollback: `[PENDING] <reason>`

If the change touched an external repository or deployed environment without an
explicit instruction, the handoff is `BLOCKED` and must not describe private
details. The canonical first-slice strategy is: read-only health reads with
respect to OW; the BFF may create its own idempotent `VerificationRun` without
mutating OW health facts. Therefore, rollback must not touch OW data.

## 13. Next Action

- Concrete next action: `<one verifiable action>`
- Owner: `<agent or user>`
- Dependency: `<handoff, decision, or test>`
- May start when: `<condition>`
- Do not do yet: `<out of scope, for example maps, health-fact mutations, AI, comparisons, or direct SQL>`

## 14. Closure

Mark local closure only after the independent validation handoff. For
`production/release`, also record the stronger separate reviews and gates:

- [ ] Files and ownership are listed with relative paths.
- [ ] Delegation stayed one level through top-level tasks with
  `subagent_depth: 1`; no subagent called Task or created a nested agent.
- [ ] In local/personal mode, the implementation handoff was followed by one
  independent validation handoff combining correctness, privacy, and final
  checks; blockers were reported, not delegated.
- [ ] If a blocker was found, no more than one targeted fix and one revalidation
  round occurred; any remaining blocker is recorded as `PENDING` or `BLOCKED`.
- [ ] Passed gates were not reopened without a new relevant change.
- [ ] In production/release mode, separate correctness, privacy, and final
  reviews plus immutable-reference, backup/restore, rollback, and deployment
  evidence are listed.
- [ ] Each claim uses a permitted documentary marker and, where applicable, a
  technical class from the canonical taxonomy.
- [ ] The capability matrix does not present internal fields as public API.
- [ ] Tests have an actual result or are marked `NOT RUN` with a reason and risk.
- [ ] Applicable accessibility, responsiveness, security, privacy, links, and
  reproducibility checks have evidence; non-applicable checks are `NOT RUN` with
  a reason and risk.
- [ ] There are no secrets, personal data, real UUIDs, coordinates, or raw
  payloads.
- [ ] Rollback and the next action are concrete and non-destructive.
- [ ] The independent validator confirms scope and findings.

Final result: `DONE`, `PENDING`, or `BLOCKED`.

Public signature of coordinator: `<identifier>`

Public signature of independent validator: `<identifier>`
