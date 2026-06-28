from django.apps import AppConfig


class IngestaConfig(AppConfig):
    """Conectores Tier A/B/C como tareas Celery aisladas. Hito futuro."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "ingesta"
    verbose_name = "Ingesta de fuentes"
