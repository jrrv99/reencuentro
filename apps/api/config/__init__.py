# Expone la app de Celery cuando Django arranca, para que @shared_task la encuentre.
from .celery import app as celery_app

__all__ = ("celery_app",)
