"""Crea personas_canonicas desde registros_fuente, agrupando por cédula.

Dos fases:
  1. Registros CON cedula_norm: se agrupan por cedula_norm (todos los que
     comparten cédula → UNA sola PersonaCanonica). Garantiza que el número
     de canónicas sea menor al de registros fuente.
  2. Registros SIN cedula_norm: sin señal para agrupar → 1-a-1.

Invariante: CANTIDAD_CANONICAS ≤ CANTIDAD_REGISTROS, y estrictamente menor
en cuanto exista alguna cédula compartida entre fuentes (que es el caso normal).

Idempotente: filtra registros que ya tienen ClusterLink; segunda corrida = 0.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from personas.choices import MetodoCluster
from personas.models import ClusterLink, PersonaCanonica, RegistroFuente


def _mejor_representante(registros: list[dict]) -> dict:
    """Elige el registro con más campos rellenos como representante del grupo."""
    campos = ("nombre", "zona", "foto_url", "estado_rep")
    return max(registros, key=lambda r: sum(1 for c in campos if r.get(c)))


class Command(BaseCommand):
    help = (
        "Crea personas_canonicas desde registros_fuente. "
        "Agrupa por cedula_norm (una canónica por cédula compartida). "
        "Garantiza CANTIDAD_CANONICAS < CANTIDAD_REGISTROS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--lote",
            type=int,
            default=500,
            help="Tamaño del lote para registros sin cédula (default: 500).",
        )

    def handle(self, *args, **options):
        lote = options["lote"]

        total_sin_link = RegistroFuente.objects.filter(cluster_link__isnull=True).count()
        self.stdout.write(f"Registros sin canónica: {total_sin_link}")

        if total_sin_link == 0:
            self.stdout.write(
                self.style.SUCCESS("Nada que crear — todos los registros ya tienen canónica.")
            )
            return

        creadas = 0
        errores = 0
        links_creados = 0

        # ── Fase 1: agrupar por cedula_norm ────────────────────────────────────
        self.stdout.write("Fase 1: agrupando por cédula…")

        # Carga solo los campos necesarios para construir la canónica.
        # GeneratedField db_persist=True → columna real en Postgres, queryable.
        registros_con_cedula = list(
            RegistroFuente.objects.filter(cluster_link__isnull=True)
            .exclude(cedula_norm="")
            .values("id", "cedula_norm", "nombre", "zona", "estado_rep", "foto_url")
            .iterator(chunk_size=1000)
        )

        grupos: dict[str, list[dict]] = defaultdict(list)
        for r in registros_con_cedula:
            grupos[r["cedula_norm"]].append(r)

        n_grupos = len(grupos)
        n_registros_con_cedula = len(registros_con_cedula)
        self.stdout.write(
            f"  {n_registros_con_cedula} registros con cédula → {n_grupos} grupos únicos"
            f" (ahorro: {n_registros_con_cedula - n_grupos} canónicas)"
        )

        for cedula_norm, grupo in grupos.items():
            rep = _mejor_representante(grupo)
            try:
                with transaction.atomic():
                    persona = PersonaCanonica.objects.create(
                        nombre_display=rep["nombre"],
                        zona=rep["zona"],
                        estado_actual=rep["estado_rep"],
                        foto_principal=rep["foto_url"],
                        n_fuentes=len(grupo),
                    )
                    ClusterLink.objects.bulk_create([
                        ClusterLink(
                            registro_id=r["id"],
                            persona=persona,
                            score=1.0,
                            metodo=MetodoCluster.CEDULA,
                            confirmado=True,
                        )
                        for r in grupo
                    ])
                    creadas += 1
                    links_creados += len(grupo)
            except Exception as exc:
                errores += 1
                self.stderr.write(f"Error en grupo cédula {cedula_norm!r}: {exc}")

        self.stdout.write(f"  Fase 1 lista: {creadas} canónicas creadas para {links_creados} registros.")

        # ── Fase 2: registros sin cédula → 1-a-1 ──────────────────────────────
        self.stdout.write("Fase 2: registros sin cédula (1-a-1)…")

        sin_cedula_qs = RegistroFuente.objects.filter(
            cluster_link__isnull=True, cedula_norm=""
        )
        n_sin_cedula = sin_cedula_qs.count()
        creadas_fase2 = 0

        for registro in sin_cedula_qs.iterator(chunk_size=lote):
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
                        metodo=MetodoCluster.BOOTSTRAP,
                        confirmado=True,
                    )
                    creadas_fase2 += 1
                    links_creados += 1
            except Exception as exc:
                errores += 1
                self.stderr.write(f"Error en registro {registro.id}: {exc}")

            if creadas_fase2 % lote == 0 and creadas_fase2 > 0:
                self.stdout.write(f"  {creadas_fase2}/{n_sin_cedula} sin-cédula…")

        creadas += creadas_fase2

        self.stdout.write(
            self.style.SUCCESS(
                f"\nResumen:\n"
                f"  Registros procesados : {links_creados}\n"
                f"  Canónicas creadas    : {creadas}\n"
                f"  Reducción            : {links_creados - creadas} registros fusionados por cédula\n"
                f"  Errores              : {errores}"
            )
        )
