from django.contrib import admin

from .models import Institucion, Responder


class ResponderInline(admin.TabularInline):
    model = Responder
    fields = ("user", "rol", "activo", "created_at")
    readonly_fields = ("created_at",)
    extra = 0
    show_change_link = True


@admin.register(Institucion)
class InstitucionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "zona", "verificada", "activa", "created_at")
    list_filter = ("tipo", "verificada", "activa")
    search_fields = ("nombre", "zona", "dominio_email")
    readonly_fields = ("id", "created_at")
    inlines = [ResponderInline]
    fieldsets = (
        (None, {"fields": ("id", "nombre", "tipo", "zona")}),
        ("Estado", {"fields": ("verificada", "activa")}),
        ("Integración", {"fields": ("dominio_email",)}),
        ("Auditoría", {"fields": ("created_at",)}),
    )

    actions = ["marcar_verificada", "marcar_no_verificada"]

    @admin.action(description="Marcar como verificadas")
    def marcar_verificada(self, request, queryset):
        queryset.update(verificada=True)

    @admin.action(description="Marcar como no verificadas")
    def marcar_no_verificada(self, request, queryset):
        queryset.update(verificada=False)


@admin.register(Responder)
class ResponderAdmin(admin.ModelAdmin):
    list_display = ("user", "institucion", "rol", "activo", "created_at")
    list_filter = ("rol", "activo", "institucion")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    readonly_fields = ("id", "created_at")
    raw_id_fields = ("user",)
    autocomplete_fields = []
