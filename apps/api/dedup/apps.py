from django.apps import AppConfig


class DedupConfig(AppConfig):
    """Motor compartido: scoring + bloqueo + union-find. El corazón. Hito siguiente."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "dedup"
    verbose_name = "Deduplicación"
