"""App Celery. Implementação completa na Fase 3."""
from __future__ import annotations

# TODO Fase 3:
# from celery import Celery
# from celery.schedules import crontab
# from app.config import get_settings
#
# settings = get_settings()
# celery = Celery("viatu", broker=settings.redis_url, backend=settings.celery_result_backend)
# celery.conf.update(
#     task_acks_late=True,
#     task_reject_on_worker_lost=True,
#     worker_prefetch_multiplier=1,
#     task_time_limit=120,
#     timezone=settings.app_timezone,
# )
# celery.conf.beat_schedule = {
#     "sweep-watches": {
#         "task": "app.tasks.sweep_active_watches",
#         "schedule": crontab(minute="*/30"),
#     },
#     "reprime-cookies": {
#         "task": "app.tasks.reprime_cookies",
#         "schedule": crontab(minute=0, hour="*/4"),
#     },
# }
