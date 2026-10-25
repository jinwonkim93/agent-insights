import os

import pytest

from agent_insights.clustering import CompleteLink
from agent_insights.config import Settings
from agent_insights.providers.demo import DemoEmbedder, DemoGenerator
from agent_insights.service import InsightService
from agent_insights.storage import SQLRepository


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        generation_provider="demo",
        embedding_provider="demo",
        min_sessions_per_topic=2,
    )


@pytest.fixture
def repo():
    # Integration CI supplies a disposable DB URL; no real project DB is touched.
    repository = SQLRepository(os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:"))
    from agent_insights.storage.sql import metadata

    metadata.drop_all(repository.engine)
    repository.initialize()
    yield repository
    repository.close()


@pytest.fixture
def service(repo, settings):
    return InsightService(repo, DemoGenerator(), DemoEmbedder(), CompleteLink(0.8), settings)
