"""Optional in-process nightly scheduler for the embeddings sync — an alternative to an
external cron/Docker-Compose `embeddings-job` profile run, toggled by `EMBEDDINGS_SCHEDULE_ENABLED`.
Kept entirely separate from the FastAPI request path: failures here must never affect webhook
availability, so each run is wrapped and logged defensively.

Wire it up from `app.main.lifespan` if/when you want in-process scheduling:

    from app.jobs.scheduler import start_scheduler, stop_scheduler
    scheduler = start_scheduler(settings)
    ...
    stop_scheduler(scheduler)
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.jobs.embed_products import run_embedding_sync
from app.logging_setup import get_logger

logger = get_logger(__name__)

_JOB_ID = "nightly_embeddings_sync"
_DEFAULT_HOUR = 2  # low-traffic window


def start_scheduler(settings: Settings, *, hour: int = _DEFAULT_HOUR) -> AsyncIOScheduler | None:
    if not settings.embeddings_schedule_enabled:
        logger.info("scheduler_disabled")
        return None

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_sync_job,
        trigger=CronTrigger(hour=hour, minute=0),
        id=_JOB_ID,
        kwargs={"settings": settings},
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("scheduler_started", job_id=_JOB_ID, hour=hour)
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped", job_id=_JOB_ID)


async def _run_sync_job(settings: Settings) -> None:
    try:
        stats = await run_embedding_sync(settings=settings)
        logger.info("scheduled_embeddings_sync_completed", **stats)
    except Exception:
        logger.exception("scheduled_embeddings_sync_failed")
