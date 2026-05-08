from celery import Celery

from celery.schedules import crontab

from core.config import settings

celery_app = Celery(
    "worker", broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=["app.worker.tasks"],
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "cleanup-tokens-midnight": {
        "task": "app.worker.tasks.cleanup_expired_tokens",
        "schedule": crontab(minute=0),
    },
    "sync-stuck-orders-every-30m": {
        "task": "app.worker.tasks.sync_stuck_orders",
        "schedule": crontab(minute="*/30"),
    },
}
