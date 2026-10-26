# Agent Insights

**Provider-independent topic analytics for continuously arriving, closed conversations.**

![Agent Insights demo dashboard showing topic rankings, linked conversations, and transcript evidence](docs/assets/demo-dashboard.jpg)

*Offline demo with original synthetic conversations. No customer data is shown.*

```text
Closed conversation → request summaries → existing topic assignment
                                            ↓ uncertain requests
                                  bounded batch discovery
                                  → existing topic / new topic / pending
```

**Experimental alpha.** This is a runnable reference implementation, not a production-ready multi-tenant SaaS or a reproduction of Clio, HILTON, or BERTopic. Evaluate semantic accuracy, storage and throughput on your data.

There is one persistent classification layer. Temporary daily clusters do not automatically become permanent subtopics. Registered topics are not automatically deleted, merged or split. A configurable per-bot topic budget limits new registration; uncertain requests are not forced into unrelated topics.

## Quick start: offline demo

Python 3.11+:

```sh
git clone https://github.com/jinwonkim93/agent-insights.git
cd agent-insights
python -m venv .venv
source .venv/bin/activate
pip install -e .
export AI_GENERATION_PROVIDER=demo
export AI_EMBEDDING_PROVIDER=demo
agent-insights demo
agent-insights serve
```

Open **http://127.0.0.1:8766**, workspace `demo`, bot `support`. The 12 original synthetic conversations have explicit October 2026 timestamps. Date filters start unrestricted. The `demo` providers use deterministic fixture logic: they are **not language models** and make no external calls. No third-party dataset is bundled.

## Model backends

Copy `.env.example` to `.env`. Generation and embedding are configured independently; environment variables override the file.

### Ollama native

```dotenv
AI_GENERATION_PROVIDER=ollama
AI_GENERATION_URL=http://127.0.0.1:11434
AI_GENERATION_MODEL=gemma3:4b
AI_EMBEDDING_PROVIDER=ollama
AI_EMBEDDING_URL=http://127.0.0.1:11434
AI_EMBEDDING_MODEL=embeddinggemma
```

Pull/install the configured models separately. Use your actual served IDs, including MLX aliases if applicable. The adapter uses `/api/generate` and `/api/embed`. It parses/validates JSON with bounded syntax retries without assuming JSON-mode or thinking extensions.

### vLLM / OpenAI-compatible servers

```dotenv
AI_GENERATION_PROVIDER=openai
AI_GENERATION_URL=http://127.0.0.1:8000/v1
AI_GENERATION_MODEL=your-served-chat-model
AI_GENERATION_API_KEY=
AI_EMBEDDING_PROVIDER=openai
AI_EMBEDDING_URL=http://127.0.0.1:8001/v1
AI_EMBEDDING_MODEL=your-served-embedding-model
AI_EMBEDDING_API_KEY=
```

The adapter calls `/chat/completions` and `/embeddings` relative to the `/v1` base URL. An embedding-capable model/server is required; a generation-only vLLM deployment does not automatically provide embeddings. You can mix vLLM generation with Ollama embeddings or vice versa.

References: [Ollama API](https://docs.ollama.com/api), [vLLM compatible server](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/).

## Database backends

The service depends on a `Repository` protocol. The included SQLAlchemy adapter avoids database-specific vector extensions and JSON queries.

| Backend | Install | `AI_DATABASE_URL` |
|---|---|---|
| SQLite | `pip install -e .` | `sqlite:///./agent-insights.db` |
| PostgreSQL | `pip install -e '.[postgres]'` | `postgresql+psycopg://user:password@host/insights` |
| MySQL | `pip install -e '.[mysql]'` | `mysql+pymysql://user:password@host/insights?charset=utf8mb4` |

URL-encode reserved credential characters. Never commit real DB URLs. SQLite is for local/single-host evaluation; PostgreSQL is the first intended multi-worker target. A URL change does not migrate data. `init-db` bootstraps the alpha schema, not versioned migrations. Non-SQL backends need a new repository adapter implementing the same consistency contracts.

SQLite is tested locally. CI includes PostgreSQL/MySQL contract jobs; those engines must pass in your deployment environment before use. SQLAlchemy portability does not imply identical transaction or performance behavior.

## Ingestion and continuous processing

```sh
agent-insights init-db
agent-insights ingest examples/conversations.jsonl
agent-insights worker --once  # drain current queue, discover, exit
agent-insights worker         # poll for new closed conversations, periodic discovery
# separate terminal, same configuration and database
agent-insights serve
```

HTTP ingestion:

```sh
curl -X POST http://127.0.0.1:8766/v1/conversations \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"demo","bot_id":"support","external_id":"new-001","closed_at":"2026-10-25T12:00:00+09:00","messages":[{"role":"customer","text":"Please replace my lost card."},{"role":"assistant","text":"I can help."}]}'
```

Add `Authorization: Bearer <key>` when `AI_API_KEY` is configured. Same workspace/bot/external ID plus identical normalized content is idempotent; changed content returns 409. Timezone-aware closure timestamps are required. Revisions, deletions and in-progress turn analysis are not implemented.

## Classification policy

- Start with an empty registry. Repeated unassigned requests form the first topics.
- Assign new summaries against original-space topic prototypes using cosine similarity and a top-two margin. Prototypes remain stable; automatic drift adaptation is not implemented.
- Discover from bounded pending batches. Require distinct-session support and model-based reuse/novelty decisions. New registration gets a second novelty check when a registry exists. Model judgments can still be wrong.
- Default complete-link clustering is deterministic for fixed vectors/IDs and intended for small batches, **not high-volume clustering**.
- Optional `pip install -e '.[umap]'` plus `AI_CLUSTERER=umap_hdbscan` enables batch-local UMAP/HDBSCAN. Reduced coordinates are temporary; registered prototypes stay in the original embedding space. Tiny batches use complete-link.
- `AI_MAX_TOPICS_PER_BOT` defaults to 128. This is a demo policy, not an optimal universal value. At capacity, new classes remain pending and can expire to `unclassified`.
- Pending work has configurable age, review-count and batch limits. No long-lived candidate group is persisted, so rare themes can be missed across batch boundaries.
- Only topic prototypes are persisted as vectors. Original conversations, summaries, evidence and assignments remain in SQL; retention/deletion is deployment work.
- Embedding-space identity includes provider, endpoint and model ID. Changes fail closed for existing registries. Weight changes hidden behind the same model ID cannot be detected automatically; explicit migration/versioning is required.

Thresholds are experimental defaults. Cosine similarity is not a calibrated probability.

## Dashboard and API

Top 10 uses distinct conversations within a session-close date range. IANA timezone boundaries are converted to UTC half-open intervals. Conversation lists are paginated, and transcripts load on selection. Date changes do not rerun models. `/v1/status` shows the bot's current queue state, not date-filtered counts. `/docs` contains the API schema.

Reports use latest assignments; immutable exports and historical assignment reconstruction are not implemented. There is no upper classification hierarchy; it can later be added as a separate relation without changing topic IDs or assignments.

## Development and validation

```sh
pip install -e '.[dev]'
pytest
ruff check .
python -m build
```

Tests cover HTTP provider contracts, repository/service flow, scoped reads, duplicate ingest, conflict rejection, stale claims, bounded retries, pending expiry, topic caps, distinct counts, date boundaries and embedding-space changes. Mock HTTP tests are not a live vLLM test. Optional UMAP needs separate accuracy/performance evaluation.

## Release boundaries

No personal memories, local filesystem paths, credentials, weights, research PDFs, DSTC12 originals or private generated summaries are included. All bundled examples are original synthetic data. Models, datasets and dependencies retain their own licenses.

This alpha defaults to loopback. The optional shared service key is **not per-user or per-tenant authorization**; it grants access to all requested scopes. Before exposing to untrusted users, add TLS, a tenant-aware authenticated gateway, ingress size/rate limits, backups, retention/deletion, migrations and load testing. Leases have no heartbeat: keep model timeouts/batches within the lease. Details: [operations](docs/operations.md).

[Architecture](docs/architecture.md) · [한국어](docs/README.ko.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

MIT licensed.
