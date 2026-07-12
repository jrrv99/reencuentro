"""Tareas Celery del motor de dedup."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="dedup.tasks.dedup_record",
)
def dedup_record(self, registro_id: str) -> int:
    """Corre el pipeline de dedup para un RegistroFuente. Retriable con backoff."""
    from personas.models import RegistroFuente

    from .pipeline import dedup_registro

    try:
        registro = RegistroFuente.objects.get(id=registro_id)
    except RegistroFuente.DoesNotExist:
        logger.warning("dedup_record: registro %s no existe, ignorando", registro_id)
        return 0

    try:
        merges = dedup_registro(registro)
        logger.debug("dedup_record: registro=%s merges=%d", registro_id, merges)
        return merges
    except Exception as exc:
        logger.exception("dedup_record: error en registro %s", registro_id)
        raise self.retry(exc=exc)
