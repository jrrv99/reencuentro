from django.contrib import admin

from .models import SyncRun


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "fuente",
        "iniciada_at",
        "terminada_at",
        "leidos",
        "insertados",
        "actualizados",
        "sin_cambio",
        "errores",
        "fallida",
    )
    list_filter = ("fuente", "fallida")
    readonly_fields = (
        "id",
        "fuente",
        "archivo",
        "iniciada_at",
        "terminada_at",
        "leidos",
        "insertados",
        "actualizados",
        "sin_cambio",
        "omitidos",
        "errores",
        "fallida",
        "error_msg",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
