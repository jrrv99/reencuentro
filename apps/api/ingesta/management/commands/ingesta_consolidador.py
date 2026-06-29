"""Management command: ingesta del consolidador (aevscraping).

Uso:
    python manage.py ingesta_consolidador --archivo datos_consolidados/todos_registros.json
    python manage.py ingesta_consolidador  # usa CONSOLIDADOR_JSON_PATH del entorno
    python manage.py ingesta_consolidador --fuente dtv  # solo esa fuente
"""
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ingesta.connectors.consolidador import IngestaParseError, ingest_file
from ingesta.models import SyncRun


class Command(BaseCommand):
    help = "Ingesta incremental del JSON del consolidador hacia registros_fuente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            type=str,
            default=None,
            help=(
                "Ruta al JSON del consolidador. "
                "Alternativa: variable de entorno CONSOLIDADOR_JSON_PATH."
            ),
        )
        parser.add_argument(
            "--fuente",
            type=str,
            default=None,
            help="Procesar solo registros de esta fuente (dtv, vtb, …). "
            "Sin este flag se procesan todas.",
        )

    def handle(self, *args, **options):
        ruta = options["archivo"] or os.environ.get("CONSOLIDADOR_JSON_PATH", "")
        if not ruta:
            raise CommandError(
                "Debes pasar --archivo o definir CONSOLIDADOR_JSON_PATH en el entorno."
            )

        fuente = options["fuente"]
        run = SyncRun.objects.create(fuente=fuente, archivo=ruta)

        self.stdout.write(f"Procesando {ruta} (fuente={fuente or 'todas'}) …")
        try:
            stats = ingest_file(ruta, fuente_filtro=fuente)
            run.leidos = stats.leidos
            run.insertados = stats.insertados
            run.actualizados = stats.actualizados
            run.sin_cambio = stats.sin_cambio
            run.omitidos = stats.omitidos
            run.errores = stats.errores
        except IngestaParseError as exc:
            run.fallida = True
            run.error_msg = str(exc)
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            run.errores += 1
            raise CommandError(f"Ingesta falló: {exc}") from exc
        finally:
            run.terminada_at = timezone.now()
            run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo — leídos={stats.leidos} "
                f"+{stats.insertados} actualizados={stats.actualizados} "
                f"={stats.sin_cambio} omitidos={stats.omitidos} errores={stats.errores}"
            )
        )
