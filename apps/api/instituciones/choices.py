"""Enums (TextChoices) de la app instituciones."""
from django.db import models


class TipoInstitucion(models.TextChoices):
    HOSPITAL = "hospital", "Hospital"
    CLINICA = "clinica", "Clínica"
    ORGANIZACION = "organizacion", "Organización"
    OFICIAL = "oficial", "Ente oficial"
    PARTNER = "partner", "Partner (Cruz Roja / Prot. Civil)"


class RolResponder(models.TextChoices):
    MIEMBRO = "miembro", "Miembro"
    ADMIN = "admin", "Admin de workspace"
