# Contributing

Install `pip install -e '.[dev]'`; run `pytest`, `ruff check .`, `python -m build`.

Keep provider HTTP details outside the service and SQL inside the repository adapter. New database implementations must satisfy idempotency, scope isolation, stale-claim rejection and atomic publication. Integration tests recreate schema: use only disposable databases.

Use original synthetic fixtures. Do not commit credentials, production conversations, weights, local databases or third-party data without redistribution rights. Default tests must run offline.

Changes to topic identity, classification granularity, assignment stability, retention or reporting semantics need an architecture note. Semantic quality claims require reproducible labeled evaluation, not just unit tests.

## Release checks

Run `ruff check .`, `ruff format --check .`, `pytest -q`, and `python -m build`.
Format dashboard assets with `npx --yes prettier@3.6.2 --write 'src/agent_insights/web/*'`; CI checks the pinned format and JavaScript syntax.

For SQL contracts set TEST_DATABASE_URL to a dedicated disposable database; the suite recreates application tables. Run against PostgreSQL and MySQL before changing ownership, transactions or schema handling. Add an immutable Alembic revision for schema changes, and test fresh installation, repeated upgrade and legacy adoption. The initial baseline must not import live application metadata.

Build the Dockerfile and exercise `migrate`, API readiness, authentication and worker processing. Keep unverified semantic quality and scale claims out of release notes. Dependency ranges are library compatibility bounds, not a reproducible deployment lock; pin and scan the resolved image in the deployment release process.
