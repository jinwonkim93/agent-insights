"""Initial schema, frozen at revision 0001."""

from alembic import op
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
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

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


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade is not supported; restore a verified backup")
