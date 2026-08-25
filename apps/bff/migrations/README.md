# BFF Migrations

This isolated Alembic environment owns only the technical application database.
It must never receive an Open Wearables database URL.

The initial revision is reviewable and transactional. It creates control-plane
tables for local users, OIDC identity keys, OW links, hashed sessions, audit
events, idempotency records, and sanitized verification-run control state. It
does not create health-fact tables or persist detailed health results.

The selected default is one-to-one OW ownership: PostgreSQL partial unique
indexes permit only one active link per local user and only one active link per
OW user reference. Link history remains possible through inactive statuses and
versions. A future one-to-many policy requires a reviewed product/privacy
decision, authorization and contract changes, active-link conflict resolution,
a replacement migration, and a tested rollback; the current schema is not
runtime-configurable.

The revision stores only canonical lowercase SHA-256 digests for session and
idempotency values. Runtime validators enforce hexadecimal characters and reject
placeholders before ORM persistence; raw session tokens are never modelled.
Scope domains, warning codes, audit values, control states, and revocation
reasons are bounded application allowlists. `verification_run` stores only
scope, state, aggregate counts, warning codes, timestamps, and opaque refs.
Detailed health results require a separate privacy and contract decision.

The `20260822_0002` downgrade is fail-closed. Before dropping or replacing any
hardening constraints, it checks that every existing audit action and session
revocation reason is representable by the previous revision's allowlists. The
new `verification.run.update` action and `ow_unlink` reason are therefore
rejected before downgrade DDL. If either check fails, it raises a generic
migration error and relies on transactional DDL to preserve the current revision
and control-plane rows. It never deletes, rewrites, or relabels unsupported data.
A populated downgrade therefore requires an approved data policy before it can
proceed.

The disposable PostgreSQL gate is `[PENDING]` and must run later with an
explicitly provisioned service-owned database. The current offline command can
be rendered from either the repository root or `apps/bff`:

Alembic reads the server-side `APP_DATABASE_URL` directly. Any
`sqlalchemy.url` value supplied by an Alembic config file or CLI configuration is
ignored and cannot select the migration target.

```bash
# From the repository root.
BFF_CONTROL_PLANE_ENABLED=true APP_DATABASE_URL='<disposable-app-db-url>' \
  alembic -c apps/bff/alembic.ini upgrade head --sql

# From apps/bff.
BFF_CONTROL_PLANE_ENABLED=true APP_DATABASE_URL='<disposable-app-db-url>' \
  alembic -c alembic.ini upgrade head --sql
```

That gate must verify upgrade, a safe second `upgrade head`, constraint
behavior, and downgrade on the disposable database. It must not use an OW
database, an app URL equal to an OW database URL, existing application data, or
a production deployment. Offline upgrade and downgrade SQL rendering is the
current validation boundary; no connection is opened by these commands.
