from fastapi.testclient import TestClient
from test_workflow import conversation

from agent_insights.api import create_app
from agent_insights.config import Settings


def test_auth_ingest_scope_and_dates(repo):
    settings = Settings(_env_file=None, api_key="test-key")
    with TestClient(create_app(settings, repo)) as client:
        assert client.get("/health").status_code == 200
        params = {"tenant_id": "demo", "bot_id": "support"}
        assert client.get("/v1/topics", params=params).status_code == 401
        client.headers["Authorization"] = "Bearer test-key"
        assert (
            client.post(
                "/v1/conversations", json=conversation(0).model_dump(mode="json")
            ).status_code
            == 202
        )
        assert (
            client.post("/v1/conversations", json=conversation(0).model_dump(mode="json")).json()[
                "created"
            ]
            is False
        )
        changed = conversation(0, text="Other request").model_dump(mode="json")
        assert client.post("/v1/conversations", json=changed).status_code == 409
        assert len(client.get("/v1/conversations", params=params).json()["items"]) == 1
        assert (
            client.get(
                "/v1/conversations/" + conversation(0).id,
                params={"tenant_id": "other", "bot_id": "support"},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/v1/topics", params={**params, "start": "2026-10-03", "end": "2026-10-01"}
            ).status_code
            == 422
        )
        assert (
            client.get("/v1/topics", params={**params, "timezone": "No/SuchZone"}).status_code
            == 422
        )
        assert client.get("/v1/conversations", params={**params, "limit": 1000}).status_code == 422
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200


def test_timezone_date_boundaries(repo):
    repo.enqueue(conversation(0))  # 12:00 UTC, 21:00 Seoul
    with TestClient(create_app(Settings(_env_file=None), repo)) as client:
        p = {"tenant_id": "demo", "bot_id": "support", "timezone": "Asia/Seoul"}
        assert (
            len(
                client.get(
                    "/v1/conversations", params={**p, "start": "2026-10-01", "end": "2026-10-01"}
                ).json()["items"]
            )
            == 1
        )
        assert (
            len(
                client.get("/v1/conversations", params={**p, "start": "2026-10-02"}).json()["items"]
            )
            == 0
        )


def test_malformed_length_does_not_crash(repo):
    with TestClient(create_app(Settings(_env_file=None), repo)) as client:
        assert client.get("/health", headers={"Content-Length": "invalid"}).status_code == 400
        assert client.get("/health", headers={"Content-Length": "2000001"}).status_code == 413
