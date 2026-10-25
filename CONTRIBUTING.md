# Contributing

Install `pip install -e '.[dev]'`; run `pytest`, `ruff check .`, `python -m build`.

Keep provider HTTP details outside the service and SQL inside the repository adapter. New database implementations must satisfy idempotency, scope isolation, stale-claim rejection and atomic publication. Integration tests recreate schema: use only disposable databases.

Use original synthetic fixtures. Do not commit credentials, production conversations, weights, local databases or third-party data without redistribution rights. Default tests must run offline.

Changes to topic identity, classification granularity, assignment stability, retention or reporting semantics need an architecture note. Semantic quality claims require reproducible labeled evaluation, not just unit tests.
