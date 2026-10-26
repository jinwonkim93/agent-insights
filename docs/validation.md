# Validation record

Initial alpha, 2026-10-25:

- Python 3.12, SQLite: 19 offline tests passed.
- Ruff checks and source/wheel builds passed. Wheel includes dashboard assets, not datasets or local databases.
- Real local Ollama-compatible endpoint: two original synthetic closed conversations were summarized, embedded into 768 dimensions and registered under one topic. This is a connectivity/flow smoke test, not a quality benchmark.
- vLLM/OpenAI-compatible adapter: mocked HTTP contracts for chat completions and ordered embedding response reconstruction; no live vLLM server was available.
- PostgreSQL and MySQL: SQL schema compilation checked. Live contract suites are configured in CI but were not executed locally because the Docker daemon was not running. Do not interpret compilation as runtime compatibility verification.
- Browser: synthetic fixture dashboard served at loopback, topic click related four conversations and highlighted evidence; date filters use server-side queries.
- Optional UMAP/HDBSCAN: small-input fallback covered; full optional backend not installed or benchmarked in this local verification.

Known warning: current Starlette emits a TestClient/httpx deprecation warning in this environment; tests pass. No production throughput, rare-topic recall, multilingual quality, retention policy or multi-worker load certification is claimed.

## Hardening verification — 2026-10-26

- Python 3.12: SQLite and PostgreSQL 16 each passed 30 tests (one MySQL-only skip); MySQL 8.4 passed all 31, including independent concurrent worker ownership. Dedicated localhost Docker databases were used; no customer database was touched.
- New coverage: heartbeat lifecycle, expired/stolen lease renewal refusal, transactional rejection, same-batch semantic reuse with recomputed prototypes, actual streamed body limits, input-safe validation, request IDs, readiness and repeatable/legacy schema migrations.
- Real MySQL testing exposed loss of epoch-second precision in default FLOAT columns. Current schema uses 53-bit precision; Alembic revision 0002 upgrades legacy leases. A MySQL-specific regression verifies migration of the original column type.
- Non-root Docker image built successfully. Containerized Alembic migration and synthetic analysis against PostgreSQL passed (12 sessions, 3 topics). API readiness returned 200 and authenticated ranking returned three topics with four sessions each, running as UID 10001.
- Ruff lint/format checks, JavaScript syntax, pinned Prettier formatting and source/wheel builds are release checks. CI also runs Python 3.11–3.13 and disposable SQL contracts.
- These checks establish functional behavior, not semantic accuracy or sustained throughput. Live vLLM, full optional UMAP, gateway authorization, deletion propagation and a production-scale soak remain unverified or outside this release.
