# Initial Commit Checklist

This checklist prepares Enano Coach's first public commit. It does not run
`git commit` and does not authorize deployments or changes in other
repositories.

## Included

The initial commit may include:

- `AGENTS.md` and the repository's public rules.
- Public `docs/` documentation, including contracts, brief, session prompt,
  handoff, and this checklist.
- Synthetic fixtures with valid JSON, no real data, and the corresponding
  security blocks.
- The seven custom `enano-coach-*` skills under `.agents/skills/`.
- `skills-lock.json`, which records exactly the 11 external sources and their
  hashes.
- `.gitignore`, with explicit exclusions for external copies.

The seven custom `enano-coach-*` skills are versioned. Local copies of the 11
external skills are not initially versioned: they contain vendored
documentation, examples, paths for other tools, and links that are not part of
the product. They remain in the worktree and are reinstalled from
`skills-lock.json` with the CLI when needed. `skills-lock.json` records only
external sources; it does not turn custom skills into lock dependencies. Their
`computedHash` values are public integrity references for the sources, not
credentials.

## Excluded

Do not include:

- `.env`, secrets, tokens, API keys, passwords, credential hashes, or rendered
  configuration.
- Real health data, private logs, snapshots, raw payloads, Gadgetbridge exports,
  or any device file.
- Local databases, dumps, backups, SQLite/PostgreSQL databases, or restore files.
- Builds, caches, installed dependencies, coverage, or Playwright reports.
- Personal screenshots, data screenshots, or IDE files.
- Worktrees or uncommitted changes from `open-wearables`, `gadgetbridge-ow`, or
  `ans-health-stack`.
- Paths, hosts, domains, identifiers, or configuration specific to the
  operator's local environment.

The `5173` and `8000` ports and the `localhost` URLs documented in the project
are configurable local defaults, not production values.

## Pre-Preparation Inspection

Run from the repository root, review the output, and correct every finding
before preparing the commit:

```bash
git status --short
git diff --stat
git diff --check
git diff --name-status
git ls-files --others --exclude-standard
```

Review the diff and the list of owned files, including new files:

```bash
git diff -- .
git ls-files --cached --others --exclude-standard
```

Search for secrets or credentials without printing candidate values:

```bash
rg -l --hidden --glob '!.git/**' \
  --glob '!.agents/skills/auth-implementation-patterns/**' \
  --glob '!.agents/skills/code-security/**' \
  --glob '!.agents/skills/fastapi-templates/**' \
  --glob '!.agents/skills/frontend-design/**' \
  --glob '!.agents/skills/openapi-spec-generation/**' \
  --glob '!.agents/skills/systematic-debugging/**' \
  --glob '!.agents/skills/test-driven-development/**' \
  --glob '!.agents/skills/vercel-react-best-practices/**' \
  --glob '!.agents/skills/verification-before-completion/**' \
  --glob '!.agents/skills/web-design-guidelines/**' \
  --glob '!.agents/skills/webapp-testing/**' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'ghp_[A-Za-z0-9]+' \
  -e 'sk-[A-Za-z0-9_-]+' \
  -e 'Bearer [A-Za-z0-9._~-]+' \
  -e 'BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY' \
  -e 'api[_-]?key|secret|token|password' .
```

Local copies of external skills are excluded from the initial commit. Link,
fence, or vendored-documentation problems inside them do not block that commit.
If they are used locally, they may be reviewed separately; a real secret must
not enter the commit or an owned artifact:

```bash
rg -l --hidden --glob '!.git/**' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'ghp_[A-Za-z0-9]+' \
  -e 'sk-[A-Za-z0-9_-]+' \
  -e 'Bearer [A-Za-z0-9._~-]+' \
  -e 'BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY' \
  .agents/skills/auth-implementation-patterns \
  .agents/skills/code-security \
  .agents/skills/fastapi-templates \
  .agents/skills/frontend-design \
  .agents/skills/openapi-spec-generation \
  .agents/skills/systematic-debugging \
  .agents/skills/test-driven-development \
  .agents/skills/vercel-react-best-practices \
  .agents/skills/verification-before-completion \
  .agents/skills/web-design-guidelines \
  .agents/skills/webapp-testing
```

Also confirm parsing of both fixtures, front matter for the seven custom skills,
and internal links/fences in owned files. Links/fences in excluded external
skills do not block the initial commit. Record a `[VERIFIED]` result only after
running the check and noting its scope. Do not run `git commit` as part of this
inspection.
