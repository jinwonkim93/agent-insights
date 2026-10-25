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
