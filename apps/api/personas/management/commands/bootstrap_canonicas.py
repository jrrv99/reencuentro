"""Crea una PersonaCanonica 1-a-1 por cada RegistroFuente sin ClusterLink.

Precondición del Hito 2a: antes de que el motor de dedup (Hito 2b) fusione
registros en canónicas consolidadas, necesitamos que CADA registro esté
representado en personas_canonicas. Así las APIs `/personas/` y `/registros/`
ya devuelven resultados reales.

Idempotente: una segunda corrida detecta que todos los registros ya tienen
ClusterLink y reporta 0 creadas.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from personas.models import ClusterLink, PersonaCanonica, RegistroFuente


class Command(BaseCommand):
    help = "Crea una PersonaCanonica 1-a-1 por cada RegistroFuente sin ClusterLink (pre-dedup)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lote",
            type=int,
            default=500,
            help="Tamaño del lote de procesamiento (default: 500).",
        )

    def handle(self, *args, **options):
        lote = options["lote"]

        total_sin_link = RegistroFuente.objects.filter(cluster_link__isnull=True).count()
        self.stdout.write(f"Registros sin canónica: {total_sin_link}")

        if total_sin_link == 0:
            self.stdout.write(self.style.SUCCESS("Nada que crear — todos los registros ya tienen canónica."))
            return

        creados = 0
        errores = 0

        registros = RegistroFuente.objects.filter(cluster_link__isnull=True).iterator(chunk_size=lote)
        for registro in registros:
            try:
                with transaction.atomic():
                    persona = PersonaCanonica.objects.create(
                        nombre_display=registro.nombre,
                        zona=registro.zona,
                        estado_actual=registro.estado_rep,
                        foto_principal=registro.foto_url,
                        n_fuentes=1,
                    )
                    ClusterLink.objects.create(
                        registro=registro,
                        persona=persona,
                        score=1.0,
                        metodo="bootstrap",
                        confirmado=True,
                    )
                    creados += 1
            except Exception as exc:
                errores += 1
                self.stderr.write(f"Error en registro {registro.id}: {exc}")

            if creados % lote == 0 and creados > 0:
                self.stdout.write(f"  {creados}/{total_sin_link} creadas…")

        self.stdout.write(
            self.style.SUCCESS(f"Listo: {creados} canónicas creadas, {errores} errores.")
        )
