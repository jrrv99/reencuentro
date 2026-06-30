"""Tareas Celery de la app ingesta."""
import logging
import os

from celery import shared_task
from django.utils import timezone

from ingesta.connectors.consolidador import IngestaParseError, ingest_file
from ingesta.models import SyncRun

logger = logging.getLogger(__name__)


@shared_task(name="ingesta.ingesta_consolidador")
def ingesta_consolidador(
    archivo: str | None = None,
    fuente: str | None = None,
) -> dict:
    """Ingesta incremental del JSON del consolidador (aevscraping).

    Args:
        archivo: Ruta al JSON. Si es None, lee CONSOLIDADOR_JSON_PATH del entorno.
        fuente: Filtrar solo esta fuente. None = todas.
    """
    ruta = archivo or os.environ.get("CONSOLIDADOR_JSON_PATH", "")
    if not ruta:
        raise ValueError(
            "Debes pasar `archivo` o definir CONSOLIDADOR_JSON_PATH en el entorno."
        )

    run = SyncRun.objects.create(fuente=fuente, archivo=ruta)
    try:
        stats = ingest_file(ruta, fuente_filtro=fuente)
        run.leidos = stats.leidos
        run.insertados = stats.insertados
        run.actualizados = stats.actualizados
        run.sin_cambio = stats.sin_cambio
        run.omitidos = stats.omitidos
        run.errores = stats.errores
    except IngestaParseError as exc:
        # Fallo total: el archivo no era JSON válido. Ningún registro fue procesado.
        run.fallida = True
        run.error_msg = str(exc)
        raise
    except Exception:
        logger.exception("ingesta_consolidador falló para archivo=%s", ruta)
        run.errores += 1
        raise
    finally:
        run.terminada_at = timezone.now()
        run.save()

    logger.info(
        "SyncRun %s — leídos=%d +%d ~%d =%d omitidos=%d errores=%d",
        run.id,
        run.leidos,
        run.insertados,
        run.actualizados,
        run.sin_cambio,
        run.omitidos,
        run.errores,
    )
    return {
        "run_id": str(run.id),
        "leidos": run.leidos,
        "insertados": run.insertados,
        "actualizados": run.actualizados,
        "sin_cambio": run.sin_cambio,
        "omitidos": run.omitidos,
        "errores": run.errores,
    }
