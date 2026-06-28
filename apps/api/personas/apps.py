from django.apps import AppConfig


class PersonasConfig(AppConfig):
    """Índice de personas: registros_fuente (crudo, inmutable), personas_canonicas
    (vista por clustering), cluster_links, pares_negativos y estado_claims."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "personas"
    verbose_name = "Personas"
