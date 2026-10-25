"""Portable SQL adapter. No database-specific vector extension is required."""

import time
import uuid
from datetime import timedelta

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    event,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from ..domain import identity, utcnow

metadata = MetaData()
sessions = Table(
    "conversations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("scope_id", String(64), nullable=False),
    Column("bot_id", String(100), nullable=False),
    Column("external_id", String(128), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("closed_at", DateTime, nullable=False),
    Column("messages", JSON, nullable=False),
    Column("status", String(24), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("lease_until", Float, nullable=False, default=0),
    Column("claim_token", String(36)),
    Column("error", String(120)),
)
Index("ix_conversation_scope_date", sessions.c.scope_id, sessions.c.closed_at)
Index("ix_conversation_jobs", sessions.c.status, sessions.c.lease_until)
topics = Table(
    "topics",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("scope_id", String(64), nullable=False),
    Column("bot_id", String(100), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", Text, nullable=False),
    Column("vector", JSON, nullable=False),
    Column("space_id", String(64), nullable=False),
    Column("created_at", DateTime, nullable=False),
)
Index("ix_topic_scope", topics.c.scope_id)
facets = Table(
    "facets",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("conversation_id", String(64), ForeignKey("conversations.id"), nullable=False),
    Column("summary", Text, nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("status", String(24), nullable=False),
    Column("topic_id", String(36), ForeignKey("topics.id")),
    Column("reviews", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False),
)
Index("ix_facet_conversation", facets.c.conversation_id)
Index("ix_facet_topic", facets.c.topic_id, facets.c.conversation_id)
locks = Table(
    "discovery_locks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("token", String(36)),
    Column("lease_until", Float, nullable=False, default=0),
)


def scope(table, tenant, bot):
    # Hash preserves case-sensitive scope identity even on case-insensitive SQL collations.
    return table.c.scope_id == identity(tenant, bot)


def window(start, end):
    terms = []
    if start is not None:
        terms.append(sessions.c.closed_at >= start)
    if end is not None:
        terms.append(sessions.c.closed_at < end)
    return terms


class Conflict(ValueError):
    pass


class LostLease(RuntimeError):
    pass


class SQLRepository:
    def __init__(self, url):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def foreign_keys(conn, record):
                conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        metadata.create_all(self.engine)

    def enqueue(self, conversation):
        values = dict(
            id=conversation.id,
            tenant_id=conversation.tenant_id,
            scope_id=identity(conversation.tenant_id, conversation.bot_id),
            bot_id=conversation.bot_id,
            external_id=conversation.external_id,
            content_hash=conversation.content_hash,
            closed_at=conversation.closed_at.replace(tzinfo=None),
            messages=[m.model_dump() for m in conversation.messages],
            status="queued",
            attempts=0,
            lease_until=0,
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(sessions.insert().values(**values))
            return conversation.id, True
        except IntegrityError:
            with self.engine.connect() as conn:
                row = (
                    conn.execute(select(sessions).where(sessions.c.id == conversation.id))
                    .mappings()
                    .first()
                )
            if row and row["content_hash"] == conversation.content_hash:
                return conversation.id, False
            raise Conflict(
                "ID already exists with different content; revisions are not supported yet"
            )

    def claim(self, lease_seconds, max_attempts):
        now = time.time()
        eligible = and_(
            sessions.c.attempts < max_attempts,
            or_(
                sessions.c.status == "queued",
                and_(sessions.c.status == "processing", sessions.c.lease_until < now),
            ),
        )
        with self.engine.begin() as conn:
            # Exhausted crashed jobs must not remain 'processing' forever.
            conn.execute(
                update(sessions)
                .where(
                    sessions.c.status == "processing",
                    sessions.c.lease_until < now,
                    sessions.c.attempts >= max_attempts,
                )
                .values(status="failed", error="Lease expired after final attempt")
            )
            row = conn.execute(
                select(sessions.c.id)
                .where(eligible)
                .order_by(sessions.c.closed_at, sessions.c.id)
                .limit(1)
            ).first()
            if not row:
                return None
            token = str(uuid.uuid4())
            changed = conn.execute(
                update(sessions)
                .where(sessions.c.id == row.id, eligible)
                .values(
                    status="processing",
                    claim_token=token,
                    lease_until=now + lease_seconds,
                    attempts=sessions.c.attempts + 1,
                )
            )
            if changed.rowcount != 1:
                return None
            return dict(
                conn.execute(select(sessions).where(sessions.c.id == row.id)).mappings().one()
            )

    def topics(self, tenant, bot):
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(topics).where(scope(topics, tenant, bot)).order_by(topics.c.id)
                ).mappings()
            ]

    def finish(self, job, extracted):
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(sessions)
                .where(
                    sessions.c.id == job["id"],
                    sessions.c.claim_token == job["claim_token"],
                    sessions.c.status == "processing",
                    sessions.c.lease_until > time.time(),
                )
                .values(status="done", error=None, lease_until=0)
            )
            if changed.rowcount != 1:
                raise LostLease("Conversation claim expired or was replaced")
            scoped_topics = set(
                conn.execute(
                    select(topics.c.id).where(scope(topics, job["tenant_id"], job["bot_id"]))
                ).scalars()
            )
            if any(
                item.get("topic_id") and item["topic_id"] not in scoped_topics for item in extracted
            ):
                raise ValueError("Assigned topic is outside this bot")
            for i, item in enumerate(extracted):
                conn.execute(
                    facets.insert().values(
                        id=identity(job["id"], str(i)),
                        conversation_id=job["id"],
                        summary=item["summary"],
                        evidence=item["evidence"],
                        status="assigned" if item.get("topic_id") else "pending",
                        topic_id=item.get("topic_id"),
                        reviews=0,
                        created_at=utcnow(),
                    )
                )

    def fail(self, job, error, max_attempts):
        with self.engine.begin() as conn:
            conn.execute(
                update(sessions)
                .where(
                    sessions.c.id == job["id"],
                    sessions.c.claim_token == job["claim_token"],
                    sessions.c.status == "processing",
                )
                .values(
                    status="failed" if job["attempts"] >= max_attempts else "queued",
                    error=error[:120],
                    lease_until=0,
                )
            )

    def pending(self, tenant, bot, limit, max_days, max_reviews):
        cutoff = utcnow() - timedelta(days=max_days)
        with self.engine.begin() as conn:
            ids = select(sessions.c.id).where(scope(sessions, tenant, bot))
            conn.execute(
                update(facets)
                .where(
                    facets.c.conversation_id.in_(ids),
                    facets.c.status == "pending",
                    or_(facets.c.created_at <= cutoff, facets.c.reviews >= max_reviews),
                )
                .values(status="unclassified")
            )
            query = (
                select(facets)
                .join(sessions)
                .where(scope(sessions, tenant, bot), facets.c.status == "pending")
                .order_by(facets.c.created_at, facets.c.id)
                .limit(limit)
            )
            return [dict(r) for r in conn.execute(query).mappings()]

    def acquire_discovery(self, tenant, bot, seconds):
        key = identity(tenant, bot)
        try:
            with self.engine.begin() as conn:
                conn.execute(locks.insert().values(id=key, lease_until=0))
        except IntegrityError:
            pass
        token = str(uuid.uuid4())
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(locks)
                .where(locks.c.id == key, locks.c.lease_until < time.time())
                .values(token=token, lease_until=time.time() + seconds)
            )
            return token if changed.rowcount == 1 else None

    def release_discovery(self, tenant, bot, token):
        with self.engine.begin() as conn:
            conn.execute(
                update(locks)
                .where(locks.c.id == identity(tenant, bot), locks.c.token == token)
                .values(lease_until=0)
            )

    def apply_discovery(self, tenant, bot, token, decisions, max_topics):
        counts = {"created": 0, "assigned": 0, "reviewed": 0, "capped": 0}
        with self.engine.begin() as conn:
            # A conditional write holds this bot's lock row until commit on supported SQL engines.
            changed = conn.execute(
                update(locks)
                .where(
                    locks.c.id == identity(tenant, bot),
                    locks.c.token == token,
                    locks.c.lease_until > time.time(),
                )
                .values(lease_until=locks.c.lease_until)
            )
            if changed.rowcount != 1:
                raise LostLease("Discovery lease expired; no changes committed")
            existing = {
                r.id for r in conn.execute(select(topics.c.id).where(scope(topics, tenant, bot)))
            }
            allowed = select(sessions.c.id).where(scope(sessions, tenant, bot))
            for decision in decisions:
                ids = decision["facet_ids"]
                active = list(
                    conn.execute(
                        select(facets.c.id).where(
                            facets.c.id.in_(ids),
                            facets.c.conversation_id.in_(allowed),
                            facets.c.status == "pending",
                        )
                    ).scalars()
                )
                if not active:
                    continue
                target = decision.get("topic_id")
                if decision["action"] == "create":
                    if len(existing) >= max_topics:
                        counts["capped"] += len(active)
                        target = None
                    else:
                        target = str(uuid.uuid4())
                        conn.execute(
                            topics.insert().values(
                                id=target,
                                tenant_id=tenant,
                                scope_id=identity(tenant, bot),
                                bot_id=bot,
                                name=decision["name"],
                                description=decision["description"],
                                vector=decision["vector"],
                                space_id=decision["space_id"],
                                created_at=utcnow(),
                            )
                        )
                        existing.add(target)
                        counts["created"] += 1
                if target is not None and target not in existing:
                    raise ValueError("Target topic is outside this bot")
                conn.execute(
                    update(facets)
                    .where(facets.c.id.in_(active))
                    .values(
                        topic_id=target,
                        status="assigned" if target else "pending",
                        reviews=facets.c.reviews + 1,
                    )
                )
                counts["assigned"] += len(active) if target else 0
                counts["reviewed"] += len(active)
        return counts

    def list_topics(self, tenant, bot, start=None, end=None, limit=10):
        count = func.count(func.distinct(sessions.c.id)).label("count")
        query = (
            select(topics.c.id, topics.c.name, topics.c.description, count)
            .select_from(topics.join(facets).join(sessions))
            .where(
                scope(topics, tenant, bot),
                scope(sessions, tenant, bot),
                facets.c.status == "assigned",
                *window(start, end),
            )
        )
        query = query.group_by(topics.c.id, topics.c.name, topics.c.description)
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    query.order_by(count.desc(), topics.c.id).limit(limit)
                ).mappings()
            ]

    def list_conversations(
        self, tenant, bot, start=None, end=None, topic_id=None, offset=0, limit=20
    ):
        query = select(
            sessions.c.id,
            sessions.c.external_id,
            sessions.c.closed_at,
            sessions.c.status,
            sessions.c.error,
        ).where(scope(sessions, tenant, bot), *window(start, end))
        if topic_id:
            query = query.where(
                sessions.c.id.in_(
                    select(facets.c.conversation_id).where(
                        facets.c.topic_id == topic_id, facets.c.status == "assigned"
                    )
                )
            )
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    query.order_by(sessions.c.closed_at.desc(), sessions.c.id)
                    .offset(offset)
                    .limit(limit)
                ).mappings()
            ]

    def conversation(self, tenant, bot, conversation_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(sessions).where(
                        sessions.c.id == conversation_id, scope(sessions, tenant, bot)
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            result = {
                k: row[k] for k in ("id", "external_id", "closed_at", "status", "messages", "error")
            }
            result["facets"] = [
                dict(r)
                for r in conn.execute(
                    select(
                        facets.c.id,
                        facets.c.summary,
                        facets.c.evidence,
                        facets.c.status,
                        facets.c.topic_id,
                        facets.c.reviews,
                    ).where(facets.c.conversation_id == conversation_id)
                ).mappings()
            ]
            return result

    def status(self, tenant, bot):
        with self.engine.connect() as conn:
            jobs = dict(
                conn.execute(
                    select(sessions.c.status, func.count())
                    .where(scope(sessions, tenant, bot))
                    .group_by(sessions.c.status)
                ).all()
            )
            states = dict(
                conn.execute(
                    select(facets.c.status, func.count())
                    .join(sessions)
                    .where(scope(sessions, tenant, bot))
                    .group_by(facets.c.status)
                ).all()
            )
            total = conn.scalar(
                select(func.count()).select_from(topics).where(scope(topics, tenant, bot))
            )
        return {"conversations": jobs, "facets": states, "registered_topics": total}

    def bots(self):
        with self.engine.connect() as conn:
            return [
                (row.tenant_id, row.bot_id)
                for row in conn.execute(
                    select(sessions.c.scope_id, sessions.c.tenant_id, sessions.c.bot_id).distinct()
                )
            ]

    def close(self):
        self.engine.dispose()
