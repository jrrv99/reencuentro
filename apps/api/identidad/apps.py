from django.apps import AppConfig


class IdentidadConfig(AppConfig):
    """Caras (InsightFace + pgvector), pHash y matching.

    Requiere requirements-faces.txt (stack pesado). Hito futuro.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "identidad"
    verbose_name = "Identidad facial"
