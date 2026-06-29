"""Modelos de la app ingesta.

SyncRun: registra cada corrida de un conector (espejo de la tabla `carga`/`runs`
del consolidador), con contadores por categoría de resultado.
"""
from django.db import models
from django.db.models.functions import Now

from personas.functions import GenRandomUUID


class SyncRun(models.Model):
    """Una corrida de un conector de ingesta."""

    id = models.UUIDField(
        primary_key=True, db_default=GenRandomUUID(), editable=False
    )
    fuente = models.TextField(
        null=True, blank=True, help_text="Fuente ingerida (None = todas las del archivo)"
    )
    archivo = models.TextField(
        null=True, blank=True, help_text="Ruta al archivo JSON procesado"
    )
    iniciada_at = models.DateTimeField(db_default=Now())
    terminada_at = models.DateTimeField(null=True, blank=True)

    leidos = models.IntegerField(default=0)
    insertados = models.IntegerField(default=0)
    actualizados = models.IntegerField(default=0)
    sin_cambio = models.IntegerField(default=0)
    omitidos = models.IntegerField(default=0)
    errores = models.IntegerField(default=0)

    class Meta:
        db_table = "ingesta_sync_runs"
        ordering = ["-iniciada_at"]

    def __str__(self):
        return (
            f"SyncRun {self.id} — {self.fuente or 'todas'} "
            f"(+{self.insertados} ~{self.actualizados} ={self.sin_cambio})"
        )
