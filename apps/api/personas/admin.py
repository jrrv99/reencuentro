from django.contrib import admin

from .models import (
    ClusterLink,
    EstadoClaim,
    PersonaCanonica,
    RegistroFuente,
)


@admin.register(RegistroFuente)
class RegistroFuenteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fuente", "tipo", "zona", "estado_rep", "ingested_at")
    list_filter = ("tipo", "fuente", "tipo_fuente", "identificado")
    search_fields = ("nombre", "cedula", "zona")
    # contacto / face_embedding quedan fuera de búsqueda; son datos sensibles.


@admin.register(PersonaCanonica)
class PersonaCanonicaAdmin(admin.ModelAdmin):
    list_display = ("nombre_display", "zona", "estado_actual", "n_fuentes", "updated_at")
    search_fields = ("nombre_display", "cedula", "zona")


# ParNegativo tiene PK compuesta → el admin de Django 5.2 aún no lo soporta.
admin.site.register(ClusterLink)
admin.site.register(EstadoClaim)
