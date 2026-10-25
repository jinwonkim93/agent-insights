import argparse
import json
import time
from datetime import UTC, datetime, timedelta

from .clustering import CompleteLink, UMAPDiscovery
from .config import Settings
from .domain import ClosedConversation
from .providers import build_providers
from .service import InsightService
from .storage import SQLRepository


def main():
    parser = argparse.ArgumentParser(description="Closed-conversation topic analytics")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Start the local API/dashboard")
    sub.add_parser("init-db", help="Create the alpha schema (not a migration engine)")
    ingest = sub.add_parser("ingest", help="Import closed conversations from JSONL")
    ingest.add_argument("path")
    worker = sub.add_parser("worker", help="Process queued sessions; discover topics periodically")
    worker.add_argument(
        "--once", action="store_true", help="Drain current queue, discover, then exit"
    )
    worker.add_argument("--poll-seconds", type=float, default=2)
    worker.add_argument("--discover-seconds", type=float, default=60)
    sub.add_parser("demo", help="Seed and process ORIGINAL synthetic data; requires demo providers")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        if (
            settings.host not in {"127.0.0.1", "localhost", "::1"}
            and not settings.api_key.get_secret_value()
        ):
            parser.error("Set AI_API_KEY before binding a non-loopback address")
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
        return
    repo = SQLRepository(settings.database_url)
    repo.initialize()
    generator = embedder = None
    try:
        if args.command == "init-db":
            print("Schema initialized")
            return
        if args.command == "ingest":
            with open(args.path, encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        identifier, created = repo.enqueue(
                            ClosedConversation.model_validate_json(line)
                        )
                        print(json.dumps({"id": identifier, "created": created}))
            return
        if args.command == "demo":
            if settings.generation_provider != "demo" or settings.embedding_provider != "demo":
                parser.error(
                    "demo requires AI_GENERATION_PROVIDER=demo and AI_EMBEDDING_PROVIDER=demo"
                )
            for i in range(12):
                question = [
                    "Please change my address",
                    "I lost my card; please replace it",
                    "What is my account balance?",
                ][i % 3]
                repo.enqueue(
                    ClosedConversation(
                        tenant_id="demo",
                        bot_id="support",
                        external_id=f"sample-{i}",
                        closed_at=datetime(2026, 10, 1, 12, tzinfo=UTC) + timedelta(days=i),
                        messages=[
                            {"role": "customer", "text": question},
                            {"role": "assistant", "text": "I can help with that request."},
                        ],
                    )
                )
        generator, embedder = build_providers(settings)
        clusterer = (
            UMAPDiscovery(
                settings.umap_dimensions,
                settings.min_sessions_per_topic,
                settings.discovery_similarity,
            )
            if settings.clusterer == "umap_hdbscan"
            else CompleteLink(settings.discovery_similarity)
        )
        service = InsightService(repo, generator, embedder, clusterer, settings)
        last_discovery = 0
        while True:
            worked = service.process_one()
            # Drain queued conversations before discovery in one-shot/demo mode.
            once = args.command == "demo" or args.once
            if once and worked:
                continue
            if once or time.monotonic() - last_discovery >= args.discover_seconds:
                for tenant, bot in repo.bots():
                    try:
                        result = service.discover(tenant, bot)
                        print(json.dumps({"discovery": result}), flush=True)
                    except Exception as exc:
                        print(json.dumps({"discovery_error": type(exc).__name__}), flush=True)
                last_discovery = time.monotonic()
            if once:
                break
            if not worked:
                time.sleep(max(0.1, args.poll_seconds))
    finally:
        for provider in (generator, embedder):
            if provider is not None and hasattr(provider, "close"):
                provider.close()
        repo.close()
