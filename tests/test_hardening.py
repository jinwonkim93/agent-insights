import asyncio
import time
from threading import Event

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_workflow import conversation, drain

from agent_insights.api import create_app
from agent_insights.leases import LeaseHeartbeat
from agent_insights.middleware import BodyLimitMiddleware
from agent_insights.storage.sql import LostLease, locks, sessions


def test_heartbeat_renews_and_stops():
    renewed = Event()
    calls = []

    def renew():
        calls.append(1)
        renewed.set()
        return True

    with LeaseHeartbeat(renew, 0.3):
        assert renewed.wait(2)
    count = len(calls)
    time.sleep(0.15)
    assert len(calls) == count


def test_heartbeat_stops_when_ownership_lost():
    attempted = Event()
    calls = []

    def renew():
        calls.append(1)
        attempted.set()
        return False

    with LeaseHeartbeat(renew, 0.3) as heartbeat:
        assert attempted.wait(2)
        heartbeat.thread.join(timeout=2)
        assert not heartbeat.thread.is_alive()
    assert len(calls) == 1


def test_renewals_cannot_revive_expired_or_stolen_leases(repo):
    repo.enqueue(conversation(0))
    job = repo.claim(60, 3)
    assert repo.renew_conversation(job, 120)
    token = repo.acquire_discovery("demo", "support", 60)
    assert repo.renew_discovery("demo", "support", token, 120)
    assert not repo.renew_discovery("demo", "support", "wrong-token", 120)
    with repo.engine.begin() as conn:
        conn.execute(update(sessions).values(lease_until=time.time() - 1))
        conn.execute(update(locks).values(lease_until=time.time() - 1))
    assert not repo.renew_conversation(job, 60)
    assert not repo.renew_discovery("demo", "support", token, 60)
    repo.fail(job, "old-worker", 3)
    assert repo.conversation("demo", "support", job["id"])["status"] == "processing"
    with pytest.raises(LostLease):
        repo.apply_discovery("demo", "support", token, [], 10)


def test_staged_semantic_reuse_recomputes_prototype(repo, service):
    for i in range(4):
        repo.enqueue(conversation(i))
    drain(service)

    class TwoGroups:
        def groups(self, vectors, keys):
            return [[0, 1], [2, 3]]

    class Embeddings:
        space_id = service.embedder.space_id

        def embed(self, texts):
            return [[1.0, 0.0], [1.0, 0.0], [0.6, 0.8], [0.6, 0.8]]

    class SemanticReviewer:
        def generate_json(self, system, payload):
            if payload["topics"]:
                assert payload["topics"][0]["name"] == "Address maintenance"
                return {
                    "action": "assign_existing",
                    "topic_id": payload["topics"][0]["id"],
                    "reason": "Same intent despite different wording",
                }
            return {
                "action": "create",
                "name": "Address maintenance",
                "description": "Update contact addresses",
                "reason": "Recurring request",
            }

    service.clusterer, service.embedder, service.generator = (
        TwoGroups(),
        Embeddings(),
        SemanticReviewer(),
    )
    result = service.discover("demo", "support")
    assert result["created"] == 1
    assert result["assigned"] == 4
    vector = repo.topics("demo", "support")[0]["vector"]
    assert np.allclose(vector, np.array([0.8, 0.4]) / np.linalg.norm([0.8, 0.4]))


def test_streamed_body_limit_without_content_length():
    reached = []

    async def downstream(scope, receive, send):
        reached.append(True)

    app = BodyLimitMiddleware(downstream, max_bytes=4)
    events = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"45", "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(events)

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": "http"}, receive, send))
    assert not reached
    assert sent[0]["status"] == 413


def test_validation_does_not_echo_private_input_and_readiness(repo, settings):
    with TestClient(create_app(settings, repo)) as client:
        response = client.post("/v1/conversations", json={"messages": "private-example-123"})
        assert response.status_code == 422
        assert "private-example-123" not in response.text
        assert "X-Request-ID" in response.headers
        assert client.get("/ready").status_code == 200
        original = repo.check_ready
        repo.check_ready = lambda: (_ for _ in ()).throw(RuntimeError("private-db-url"))
        response = client.get("/ready")
        assert response.status_code == 503
        assert "private-db-url" not in response.text
        repo.check_ready = original


def test_publication_is_atomic_on_invalid_decision(repo, service):
    for i in range(2):
        repo.enqueue(conversation(i))
    drain(service)
    token = repo.acquire_discovery("demo", "support", 60)
    pending = repo.pending("demo", "support", 10, 7, 3)
    with pytest.raises(ValueError):
        repo.apply_discovery(
            "demo",
            "support",
            token,
            [
                {
                    "action": "assign_existing",
                    "topic_id": "nonexistent",
                    "facet_ids": [p["id"] for p in pending],
                }
            ],
            10,
        )
    assert repo.status("demo", "support")["facets"] == {"pending": 2}
    with repo.engine.connect() as conn:
        assert conn.scalar(select(locks.c.token)) == token


def test_migration_fresh_and_repeatable(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from agent_insights.migrate import upgrade

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    upgrade(engine)
    upgrade(engine)
    assert "topics" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text("select version_num from alembic_version")) == "0002"
    engine.dispose()


def test_migration_adopts_legacy_without_losing_data(repo):
    from agent_insights.migrate import upgrade

    c = conversation(0)
    repo.enqueue(c)
    upgrade(repo.engine)
    assert repo.conversation("demo", "support", c.id)["messages"] == [
        m.model_dump() for m in c.messages
    ]


def test_migration_rejects_incomplete_legacy(tmp_path):
    from sqlalchemy import create_engine, text

    from agent_insights.migrate import upgrade

    engine = create_engine(f"sqlite:///{tmp_path / 'incomplete.db'}")
    with engine.begin() as conn:
        conn.execute(text("create table topics (id text primary key)"))
    with pytest.raises(RuntimeError, match="schema"):
        upgrade(engine)
    engine.dispose()


def test_concurrent_workers_have_single_owner(repo, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agent_insights.storage import SQLRepository

    # Separate connections on file SQLite; external CI uses the disposable SQL engine.
    if repo.engine.dialect.name == "sqlite":
        url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    else:
        url = repo.engine.url
    first, second = SQLRepository(url), SQLRepository(url)
    first.initialize()
    first.enqueue(conversation(0))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(lambda r: r.claim(60, 3), [first, second]))
        assert sum(job is not None for job in jobs) == 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(
                pool.map(lambda r: r.acquire_discovery("demo", "support", 60), [first, second])
            )
        assert sum(token is not None for token in tokens) == 1
    finally:
        first.close()
        second.close()


def test_mysql_legacy_float_deadlines_are_upgraded(repo):
    if repo.engine.dialect.name != "mysql":
        pytest.skip("MySQL-specific legacy FLOAT regression")
    from sqlalchemy import text

    from agent_insights.migrate import upgrade

    with repo.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        for table in ("conversations", "discovery_locks"):
            conn.execute(text(f"ALTER TABLE {table} MODIFY lease_until FLOAT NOT NULL"))
    upgrade(repo.engine)
    repo.enqueue(conversation(0))
    job = repo.claim(60, 3)
    with repo.engine.begin() as conn:
        conn.execute(update(sessions).values(lease_until=time.time() - 1))
    assert not repo.renew_conversation(job, 60)
    with pytest.raises(LostLease):
        repo.finish(job, [])
