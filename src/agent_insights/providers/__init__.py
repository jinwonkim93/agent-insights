from .demo import DemoEmbedder, DemoGenerator
from .http import HTTPEmbedder, HTTPGenerator


def build_providers(settings):
    generator = (
        DemoGenerator()
        if settings.generation_provider == "demo"
        else HTTPGenerator(
            settings.generation_provider,
            settings.generation_url,
            settings.generation_model,
            settings.generation_api_key.get_secret_value(),
            settings.timeout_seconds,
        )
    )
    embedder = (
        DemoEmbedder()
        if settings.embedding_provider == "demo"
        else HTTPEmbedder(
            settings.embedding_provider,
            settings.embedding_url,
            settings.embedding_model,
            settings.embedding_api_key.get_secret_value(),
            settings.timeout_seconds,
        )
    )
    return generator, embedder
