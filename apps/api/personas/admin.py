from django.contrib import admin

from .models import (
    ClusterLink,
    EstadoClaim,
    ParNegativo,
    PersonaCanonica,
    RegistroFuente,
)


@admin.register(RegistroFuente)
class RegistroFuenteAdmin(admin.ModelAdmin):
    list_display = ("fuente", "nombre", "zona", "estado_rep", "tipo_fuente", "ingested_at")
    search_fields = ("nombre", "cedula_norm")
    list_filter = ("fuente", "estado_rep", "tipo_fuente")
    readonly_fields = ("nombre_norm", "cedula_norm", "ingested_at")
    # contacto / face_embedding / raw_payload quedan fuera de search; son datos sensibles.


class ClusterLinkInline(admin.TabularInline):
    model = ClusterLink
    fk_name = "persona"
    extra = 0
    can_delete = False
    readonly_fields = ("registro", "score", "metodo", "confirmado")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PersonaCanonica)
class PersonaCanonicaAdmin(admin.ModelAdmin):
    list_display = ("nombre_display", "zona", "estado_actual", "n_fuentes", "updated_at")
    search_fields = ("nombre_display", "cedula", "zona")
    readonly_fields = ("updated_at",)
    inlines = [ClusterLinkInline]


# ParNegativo tiene PK compuesta → el admin de Django 5.2 aún no lo soporta.
admin.site.register(EstadoClaim)
