"""Encola dedup_record para todos los RegistroFuente existentes.

Diseñado para correr UNA VEZ post-bootstrap_canonicas sobre los 56k registros
ya cargados. Las corridas normales (post-ingesta) son incrementales: el conector
encola automáticamente un dedup_record por cada upsert.

Throttle: se usa countdown en Celery para repartir la carga en el tiempo y no
saturar el worker. Con --batch=100 (default), cada 100 tareas se añade 1 segundo
de delay → los 56k registros se distribuyen en ~560 segundos (≈9 min).
"""
from django.core.management.base import BaseCommand

from personas.models import RegistroFuente


class Command(BaseCommand):
    help = "Encola dedup_record (Celery) para todos los RegistroFuente existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch",
            type=int,
            default=100,
            help="Cuántas tareas por segundo de delay (default: 100).",
        )
        parser.add_argument(
            "--fuente",
            type=str,
            default=None,
            help="Filtrar por fuente (default: todas).",
        )

    def handle(self, *args, **options):
        from dedup.tasks import dedup_record

        qs = RegistroFuente.objects.all()
        if options["fuente"]:
            qs = qs.filter(fuente=options["fuente"])

        ids = list(qs.values_list("id", flat=True))
        total = len(ids)
        batch = options["batch"]

        self.stdout.write(f"Encolando {total} tareas dedup_record (batch={batch}/s)…")

        for i, registro_id in enumerate(ids):
            dedup_record.apply_async(
                args=[str(registro_id)],
                countdown=i // batch,  # cada `batch` tareas → +1 segundo de delay
            )
            if (i + 1) % 5000 == 0:
                self.stdout.write(f"  {i + 1}/{total} encoladas…")

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {total} tareas encoladas. "
                f"Tiempo estimado: ~{total // batch} segundos con workers activos."
            )
        )
