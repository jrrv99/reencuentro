"""Workspaces institucionales y responders con acceso privilegiado.

Multi-tenant para acceso; mono-tenant para la data (plan §7):
  - La institución gobierna membresía y permisos.
  - El índice de personas es global — un doctor ve reportes de todo el país.
"""
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.functions import Now

from personas.functions import GenRandomUUID

from .choices import RolResponder, TipoInstitucion

User = get_user_model()


class Institucion(models.Model):
    id = models.UUIDField(primary_key=True, db_default=GenRandomUUID(), editable=False)
    nombre = models.TextField()
    tipo = models.TextField(choices=TipoInstitucion.choices, default=TipoInstitucion.HOSPITAL)
    zona = models.TextField(null=True, blank=True, help_text="Ciudad/estado de referencia")
    verificada = models.BooleanField(
        default=False,
        help_text=(
            "Solo admins pueden marcar verificada. "
            "Desbloquea acciones sensibles (registrar fallecido, etc.)."
        ),
    )
    activa = models.BooleanField(default=True)
    dominio_email = models.TextField(
        null=True,
        blank=True,
        help_text="Dominio institucional (p.ej. hvargas.gob.ve) para auto-verificar responders.",
    )
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "instituciones"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    @property
    def fuente_slug(self):
        """Slug estable para RegistroFuente.fuente. Ej: 'hospital_a1b2c3d4'."""
        return f"{self.tipo}_{str(self.id)[:8]}"


class Responder(models.Model):
    id = models.UUIDField(primary_key=True, db_default=GenRandomUUID(), editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="responder")
    institucion = models.ForeignKey(
        Institucion, on_delete=models.CASCADE, related_name="responders"
    )
    rol = models.TextField(choices=RolResponder.choices, default=RolResponder.MIEMBRO)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "responders"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} @ {self.institucion}"
