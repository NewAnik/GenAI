"""Liveness/readiness endpoints. `/readyz` actually pings Postgres and Qdrant — but Qdrant being
down is *not* fatal (the hybrid search degrades to SQL-only filtering), so it's reported as a
"degraded" component rather than failing the whole probe."""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import get_session
from app.logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    components: dict[str, str] = {}

    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception:
        logger.exception("readyz_postgres_check_failed")
        components["postgres"] = "down"

    qdrant_client = getattr(request.app.state, "qdrant_client", None)
    if qdrant_client is None:
        components["qdrant"] = "not_configured"
    else:
        try:
            await qdrant_client.get_collections()
            components["qdrant"] = "ok"
        except Exception:
            logger.warning("readyz_qdrant_check_failed")
            components["qdrant"] = "degraded"

    # Postgres is the only hard dependency — semantic search/Qdrant degrades gracefully to
    # SQL-only catalog filtering (see `search.hybrid_search`), so it never fails readiness alone.
    overall_ok = components.get("postgres") == "ok"
    body = {"status": "ok" if overall_ok else "down", "components": components}
    return JSONResponse(
        content=body,
        status_code=status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
