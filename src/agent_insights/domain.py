import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def identity(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class Message(BaseModel):
    role: Literal["customer", "assistant", "system"]
    text: str = Field(min_length=1, max_length=20000)


class ClosedConversation(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    bot_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    external_id: str = Field(min_length=1, max_length=128)
    closed_at: datetime
    messages: list[Message] = Field(min_length=1, max_length=300)

    @field_validator("closed_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("closed_at requires a timezone offset")
        return value.astimezone(UTC)

    @field_validator("messages")
    @classmethod
    def input_bound(cls, value):
        if sum(len(m.text) for m in value) > 100000:
            raise ValueError("Conversation exceeds 100,000 characters; split upstream")
        if not any(m.role == "customer" for m in value):
            raise ValueError("A customer message is required")
        return value

    @property
    def id(self):
        return identity(self.tenant_id, self.bot_id, self.external_id)

    @property
    def content_hash(self):
        return identity(self.model_dump_json())


class Facet(BaseModel):
    summary: str = Field(min_length=3, max_length=1000)
    evidence: list[int] = Field(min_length=1, max_length=30)


class Extraction(BaseModel):
    facets: list[Facet] = Field(default_factory=list, max_length=20)


class TopicDescription(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=3, max_length=1500)


class TopicDecision(BaseModel):
    action: Literal["assign_existing", "create", "pending"]
    topic_id: str | None = None
    name: str = ""
    description: str = ""
    reason: str = Field(min_length=1, max_length=1000)
