import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from secrets import compare_digest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .domain import ClosedConversation
from .middleware import BodyLimitMiddleware
from .storage import SQLRepository
from .storage.sql import Conflict


def date_window(start: date | None, end: date | None, tz: str):
    if start and end and start > end:
        raise HTTPException(422, "start must not be later than end")
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Unknown IANA timezone") from None

    def boundary(day):
        return datetime.combine(day, datetime.min.time(), zone).astimezone(UTC).replace(tzinfo=None)

    try:
        return boundary(start) if start else None, boundary(
            end + timedelta(days=1)
        ) if end else None
    except OverflowError:
        raise HTTPException(422, "Date out of range") from None


def create_app(settings=None, repository=None):
    settings = settings or Settings()
    owned = repository is None
    repository = repository or SQLRepository(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if settings.auto_create_schema:
            repository.initialize()
        repository.check_ready()
        yield
        if owned:
            repository.close()

    app = FastAPI(title="Agent Insights", version="0.1.0a1", lifespan=lifespan)
    app.state.repository = repository
    app.add_middleware(BodyLimitMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default response echoes input, which may contain conversation data.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()
                ]
            },
        )

    def authorize(authorization: str = Header(default="")):
        expected = settings.api_key.get_secret_value()
        if expected and not compare_digest(authorization.encode(), ("Bearer " + expected).encode()):
            raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def basic_headers(request: Request, call_next):
        # Bounded models validate actual content. Put a body-size limit at the ingress in production.
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if size < 0:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if size > 2_000_000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        response = await call_next(request)
        logging.getLogger(__name__).info(
            "http_request request_id=%s method=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0a1"}

    @app.get("/ready")
    def ready():
        try:
            repository.check_ready()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    @app.post("/v1/conversations", status_code=202, dependencies=[Depends(authorize)])
    def ingest(conversation: ClosedConversation):
        try:
            identifier, created = repository.enqueue(conversation)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        return {"id": identifier, "created": created}

    @app.get("/v1/topics", dependencies=[Depends(authorize)])
    def topics(
        tenant_id: str,
        bot_id: str,
        start: date | None = None,
        end: date | None = None,
        timezone: str = "UTC",
        limit: int = Query(10, ge=1, le=200),
    ):
        lower, upper = date_window(start, end, timezone)
        return {
            "items": repository.list_topics(tenant_id, bot_id, lower, upper, limit),
            "start": start,
            "end": end,
            "timezone": timezone,
            "basis": "session_closed_at",
            "assignment_basis": "latest",
        }

    @app.get("/v1/conversations", dependencies=[Depends(authorize)])
    def conversations(
        tenant_id: str,
        bot_id: str,
        start: date | None = None,
        end: date | None = None,
        timezone: str = "UTC",
        topic_id: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ):
        lower, upper = date_window(start, end, timezone)
        return {
            "items": repository.list_conversations(
                tenant_id, bot_id, lower, upper, topic_id, offset, limit
            ),
            "offset": offset,
        }

    @app.get("/v1/conversations/{conversation_id}", dependencies=[Depends(authorize)])
    def conversation(conversation_id: str, tenant_id: str, bot_id: str):
        result = repository.conversation(tenant_id, bot_id, conversation_id)
        if result is None:
            raise HTTPException(404, "Conversation not found")
        return result

    @app.get("/v1/status", dependencies=[Depends(authorize)])
    def status(tenant_id: str, bot_id: str):
        return repository.status(tenant_id, bot_id)

    web = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web / "index.html")

    return app
