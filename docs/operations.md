# Deployment and operations

The repository provides a hardened reference service, not a certification of production readiness. Qualify model accuracy, throughput and your SQL engine before enabling unattended processing.

## Schema and rollout

Back up the database and verify restoration first. Run `agent-insights migrate` once as a deployment job, then set `AI_AUTO_CREATE_SCHEMA=false` on the API and workers. The Alembic baseline supports a fresh database or a complete legacy schema matching the baseline's columns, type affinities and primary keys. Incomplete/mismatched schemas fail closed. Inspect constraints and indexes on legacy databases separately. Future schema changes must use new immutable revisions; do not edit revision 0001. Destructive downgrades are intentionally unsupported.

The default `AI_AUTO_CREATE_SCHEMA=true` remains a local quick-start convenience. `init-db` creates tables but does not replace migrations. Migration jobs must be serialized by the deployment system. Stop workers during incompatible upgrades. Test migrations on a restored production-sized copy before rollout.

The Dockerfile runs as a non-root user with automatic schema creation disabled and PostgreSQL support installed. Supply `AI_DATABASE_URL`, `AI_API_KEY` and model settings through your deployment's secret manager. Run the same image with `migrate`, `serve`, or `worker` as separate jobs/processes. Use an external database or explicitly mounted writable storage; the container filesystem is not durable storage.

## Health and diagnostics

`/health` is liveness. `/ready` checks database connectivity and the expected tables, not model availability or semantic quality. In schema-managed mode startup fails when tables are absent. Monitor both API and worker: an available API does not imply a progressing queue.

Responses include a generated `X-Request-ID`; application HTTP logs include this identifier, method, status and duration, without query strings or bodies. Session failure logs include an internal job ID and exception class only. Database job errors also store classes only. Never enable provider/SQL debug logging on customer traffic. Uvicorn access logs may include query parameters; use deployment logging/redaction policies appropriate to your identifiers.

Monitor queued/processing/failed counts, oldest pending age, discovery duration, topic growth, extraction quality, assignment accuracy and model latency. `/v1/status` exposes counts; backlog-age metrics, tracing and a metrics exporter are not yet implemented.

## Ownership and recovery

Background heartbeats renew conversation/discovery leases every third of the configured lease. Renewals require the current token and an unexpired lease. They cannot revive expired ownership. Final publication also checks ownership and is transactional. If renewal fails, publication fails once ownership expires; model calls may still finish, but stale workers cannot publish. Size leases for scheduler pauses and database stalls, not just one model request.

Session attempts are bounded. Expired claims are reclaimable; failed discovery leaves assignments and registrations unchanged. Failed jobs remain terminal; there is no automatic infinite retry or public administrative reset API. Investigate the cause and use a controlled operational recovery procedure. Provider failures may consume repeated calls before the attempt limit. A failed discovery batch is retried as a unit; completed LLM decisions are not checkpointed.

Do not change embedding weights underneath existing topics. Endpoint/model identity checks catch configuration changes, not silently replaced weights at an unchanged endpoint. Use an immutable deployment/model version and an explicit vector migration.

## Security boundary

The bearer key grants access to the whole service, not one tenant. Deploy behind a tenant-aware authorization gateway before allowing untrusted users. Setting tenant_id in a query is not authorization. Add TLS, rate limits, connection/read deadlines, backups and protected operational access. The API bounds actual body bytes, including chunked requests, and suppresses input echoes in validation errors. This does not replace gateway resource limits or slow-client protection.

Provider endpoints are administrator-controlled and may receive conversation text. No external telemetry is implemented. Retention/deletion and edit propagation remain deployment work; topic caps do not bound transcripts, indexes or backups.

## Capacity and release gates

2,000 sessions/day alone does not establish capacity. Benchmark message lengths, request counts, pending fractions, slow/failing providers and concurrent workers. Rankings count distinct sessions in SQL but broad date ranges still scan qualifying assignments. Profile before introducing aggregates or caches.

Run the SQL contract suite against disposable PostgreSQL/MySQL databases, not a customer database: tests recreate application tables. Local SQLite tests and SQL compilation are insufficient evidence of cross-database concurrency. CI runs contract tests on both engines. Docker build/run and a production-scale soak test must pass in your deployment environment before rollout.
