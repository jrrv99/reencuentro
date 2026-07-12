from django.apps import AppConfig


class InstitucionesConfig(AppConfig):
    """Workspaces, responders, validación y auditoría.

    Multi-tenant SOLO para acceso (la data de personas es global). Hito futuro.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "instituciones"
    verbose_name = "Instituciones y responders"
