import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from agent_insights.domain import ClosedConversation
from agent_insights.storage.sql import Conflict, LostLease, facets, sessions


def conversation(index, tenant="demo", bot="support", text="Change my address"):
    return ClosedConversation(
        tenant_id=tenant,
        bot_id=bot,
        external_id=f"test-{index}",
        closed_at=datetime(2026, 10, 1, 12, tzinfo=UTC) + timedelta(days=index),
        messages=[{"role": "customer", "text": text}],
    )


def drain(service):
    for _ in range(20):
        if not service.process_one():
            return
    raise AssertionError("Queue did not drain")


def test_closed_session_incremental_workflow(repo, service):
    c1, c2 = conversation(0), conversation(1)
    repo.enqueue(c1)
    repo.enqueue(c2)
    assert repo.enqueue(c1) == (c1.id, False)
    drain(service)
    assert service.discover("demo", "support")["created"] == 1
    topic = repo.topics("demo", "support")[0]
    before = repo.conversation("demo", "support", c1.id)["facets"]
    repo.enqueue(conversation(2))
    drain(service)
    assert repo.topics("demo", "support")[0]["id"] == topic["id"]
    assert repo.list_topics("demo", "support")[0]["count"] == 3
    assert repo.conversation("demo", "support", c1.id)["facets"] == before
    assert service.discover("demo", "support")["status"] == "idle"
    assert repo.status("other", "support")["registered_topics"] == 0
    assert repo.conversation("other", "support", c1.id) is None
    assert repo.list_conversations("other", "support", topic_id=topic["id"]) == []
    assert (
        repo.list_topics("demo", "support", datetime(2026, 10, 2), datetime(2026, 10, 3))[0][
            "count"
        ]
        == 1
    )


def test_conflicting_reingest_rejected(repo):
    repo.enqueue(conversation(0))
    with pytest.raises(Conflict):
        repo.enqueue(conversation(0, text="Replace my card"))


def test_topic_cap_leaves_requests_pending(repo, service, settings):
    settings.max_topics_per_bot = 1
    for i, text in enumerate(["Change address", "Change address", "Replace card", "Replace card"]):
        repo.enqueue(conversation(i, text=text))
    drain(service)
    service.discover("demo", "support")
    assert len(repo.topics("demo", "support")) == 1
    assert repo.status("demo", "support")["facets"]["pending"] == 2


def test_retry_limit_and_invalid_evidence(repo, service, settings):
    class InvalidGenerator:
        def generate_json(self, *args):
            return {"facets": [{"summary": "Bad evidence", "evidence": [999]}]}

    service.generator = InvalidGenerator()
    repo.enqueue(conversation(0))
    drain(service)
    assert repo.status("demo", "support")["conversations"] == {"failed": 1}
    assert repo.conversation("demo", "support", conversation(0).id)["facets"] == []


def test_stale_worker_cannot_commit(repo):
    repo.enqueue(conversation(0))
    first = repo.claim(60, 3)
    assert repo.claim(60, 3) is None
    with repo.engine.begin() as conn:
        conn.execute(update(sessions).values(lease_until=time.time() - 1))
    second = repo.claim(60, 3)
    with pytest.raises(LostLease):
        repo.finish(first, [])
    repo.finish(second, [])
    assert repo.status("demo", "support")["conversations"] == {"done": 1}


def test_pending_expiration_and_discovery_lock(repo, service):
    repo.enqueue(conversation(0))
    drain(service)
    with repo.engine.begin() as conn:
        conn.execute(update(facets).values(reviews=3))
    token = repo.acquire_discovery("demo", "support", 60)
    assert token
    assert service.discover("demo", "support") == {"status": "busy"}
    repo.release_discovery("demo", "support", token)
    assert service.discover("demo", "support")["status"] == "idle"
    assert repo.status("demo", "support")["facets"] == {"unclassified": 1}


def test_embedding_space_change_fails_closed(repo, service):
    for i in range(2):
        repo.enqueue(conversation(i))
    drain(service)
    service.discover("demo", "support")
    service.embedder.space_id = "different-model"
    repo.enqueue(conversation(2))
    drain(service)
    assert repo.conversation("demo", "support", conversation(2).id)["status"] == "failed"
    assert repo.list_topics("demo", "support")[0]["count"] == 2


def test_two_requests_one_topic_counted_once(repo, service):
    for i in range(2):
        repo.enqueue(conversation(i))
    drain(service)
    service.discover("demo", "support")
    c = conversation(2)
    repo.enqueue(c)
    job = repo.claim(60, 3)
    topic_id = repo.topics("demo", "support")[0]["id"]
    repo.finish(
        job,
        [
            {"summary": "first", "evidence": [0], "topic_id": topic_id},
            {"summary": "second", "evidence": [0], "topic_id": topic_id},
        ],
    )
    assert repo.list_topics("demo", "support")[0]["count"] == 3


def test_repository_rejects_cross_bot_topic_write(repo, service):
    for i in range(2):
        repo.enqueue(conversation(i))
    drain(service)
    service.discover("demo", "support")
    target = repo.topics("demo", "support")[0]["id"]
    repo.enqueue(conversation(3, bot="other"))
    job = repo.claim(60, 3)
    with pytest.raises(ValueError):
        repo.finish(job, [{"summary": "attempt", "evidence": [0], "topic_id": target}])
    assert repo.conversation("demo", "other", job["id"])["facets"] == []
    assert repo.conversation("demo", "other", job["id"])["status"] == "processing"


def test_scope_identity_is_case_sensitive(repo):
    a = conversation(0, tenant="Demo", bot="Support")
    b = conversation(0, tenant="demo", bot="support")
    repo.enqueue(a)
    repo.enqueue(b)
    assert len(repo.list_conversations("Demo", "Support")) == 1
    assert len(repo.list_conversations("demo", "support")) == 1
    assert repo.list_conversations("Demo", "support") == []
    assert set(repo.bots()) == {("Demo", "Support"), ("demo", "support")}
