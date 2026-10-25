# Operating the alpha

Configure models/weights and a shared database for the API and worker. Run init-db for a fresh schema, ingest only finalized conversations, and start one worker first. Measure throughput, provider memory, extraction errors, semantic misassignment, reuse rate, pending age, topic growth and DB size.

## Recovery

Provider failures store only exception classes, not model bodies or conversation content. Session attempts are bounded. Expired claims are reclaimable, and stale final writes fail. Failed discovery preserves the current registry and assignments. There is no heartbeat; tasks must fit their lease. If a task exceeds it, reduce batch/input sizes or tune leases/timeouts. Failed jobs are terminal; admin recovery endpoints are not yet implemented.

Do not change embedding models underneath existing topics. An explicit migration is needed. A fresh bot/database represents a deliberate new analysis, not a way to silently change reports.

## Capacity

2,000 sessions/day alone does not establish capacity. Measure message length, request counts, pending fraction and model latency. Transcripts are paginated, but broad period ranking still scans qualifying assignments. Profile before adding daily aggregates or version-aware caches. Parent/child distinct-session counts cannot be summed indiscriminately.

Topic vector caps do not bound original text, summaries, indexes, WAL, backups or replicas. Retention and deletion remain required deployment work.

## Exposure

Use loopback for evaluation. A service-level bearer key is not tenant identity: put a tenant-aware authorization gateway in front before exposing to untrusted users. Add TLS, byte/rate limits (including chunked bodies), backups and protected operational access. Do not log payloads, prompts, model output, credentials or DB URLs.

Provider endpoints are administrator-controlled and may receive customer text. Choose appropriate data handling policies. No external telemetry is implemented.

Integration tests recreate the schema named by TEST_DATABASE_URL: use disposable test databases only.
