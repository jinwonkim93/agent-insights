# Architecture

```text
API / JSONL ──> Repository port ──> SQLAlchemy ──> SQLite / PostgreSQL / MySQL
                       ↑
                  analysis worker
                   ├─ Generator ──> Ollama / OpenAI-compatible / custom
                   ├─ Embedder ───> Ollama / OpenAI-compatible / custom
                   └─ Clusterer ──> complete-link / batch UMAP+HDBSCAN
```

`ports.py` defines contracts. The service knows no HTTP endpoints, SQL tables or vendor SDKs. Implement generation and embedding independently and wire providers through the factory or inject them directly into `InsightService`. Databases implement the repository contract including atomic publication, scope checks, idempotency and lease fencing—not just CRUD.

## Storage

- Conversations: scope, external ID, input hash, actual closure timestamp, messages, processing status, claim lease/token and attempts.
- Facets: summary, customer evidence indexes, assigned/pending/unclassified state, conversation/topic references, first analysis time and review count.
- Topics: stable UUID, scope, name, description, original-space prototype, embedding-space identity and creation time.
- Discovery locks: per-bot expiring claim.

No per-facet vector is persisted. Topic vectors are portable JSON arrays; larger registries may require a dedicated search adapter. Keep new search adapters separate from data ownership.

## Processing contracts

Identical input registration is a no-op; changed content under the same ID is rejected. Analysis transitions queued → processing → done. Failures retry up to the maximum and then become failed. Expired claims can be reclaimed, but old workers cannot commit after lease expiry or token replacement. Extraction and assignment are published in one transaction.

Discovery reads bounded pending requests under a per-bot lease. It serializes final publication and checks the topic cap inside the transaction. Concurrent session analysis may use an older registry and leave a request pending for the next pass. Existing assigned requests and topic IDs are not rewritten.

Daily clusters are temporary. The registry starts empty and grows only through registration decisions. At its cap, registration stops, but existing-topic reuse continues; pending expires independently. A fixed cap trades off fine-grained coverage. It is not a semantic guarantee against future diversity.

## Optional future hierarchy

There is no upper hierarchy now. If needed, add separate categories and versioned category-topic relations referencing stable topic IDs. Keep embeddings, request assignment and the topic-ranking API unchanged. Parent counts require a distinct-session union, not a sum of child counts.

## Alpha limitations

No raw-data deletion/edit propagation, model migration, immutable exports, schema migrations, tenant quotas, heartbeat, cancellation or vector-index adapter. Complete-link is bounded small-batch reference code. SQL concurrency behavior must be validated per database. Semantic quality requires labeled evaluation beyond unit tests.
