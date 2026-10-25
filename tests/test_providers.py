import json

import httpx
import pytest

from agent_insights.providers.http import HTTPEmbedder, HTTPGenerator, ProviderError


@pytest.mark.parametrize("kind", ["ollama", "openai"])
def test_generation_and_embedding_wire_contract(kind):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        body = json.loads(request.content)
        assert body["model"] == "model"
        if request.url.path.endswith("generate"):
            return httpx.Response(200, json={"response": '{"facets":[]}'})
        if request.url.path.endswith("completions"):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"facets":[]}'}}]}
            )
        if request.url.path.endswith("embed"):
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    url = "http://server" if kind == "ollama" else "http://server/v1"
    generator = HTTPGenerator(kind, url, "model", transport=transport)
    embedder = HTTPEmbedder(kind, url, "model", transport=transport)
    assert generator.generate_json("schema", {}) == {"facets": []}
    assert embedder.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert seen == (
        ["/api/generate", "/api/embed"]
        if kind == "ollama"
        else ["/v1/chat/completions", "/v1/embeddings"]
    )
    generator.close()
    embedder.close()


def test_provider_errors_do_not_disclose_response():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="secret-account-123"))
    provider = HTTPGenerator("ollama", "http://server", "model", transport=transport)
    with pytest.raises(ProviderError) as exc:
        provider.generate_json("prompt", {})
    assert "secret" not in str(exc.value)


def test_bad_embeddings_are_rejected():
    provider = HTTPEmbedder(
        "ollama",
        "http://server",
        "model",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"embeddings": [[0.0, 0.0]]})
        ),
    )
    with pytest.raises(ProviderError):
        provider.embed(["a"])
