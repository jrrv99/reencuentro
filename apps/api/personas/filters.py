"""Filtros del buscador público: ?nombre=&zona=&estado=."""
import django_filters

from .models import PersonaCanonica


class PersonaCanonicaFilter(django_filters.FilterSet):
    # Búsqueda por nombre: insensible a acentos y mayúsculas (el punto del plan:
    # una familia teclea "maria" y debe encontrar "María"). El fuzzy/trigram real
    # es del motor de dedup (hito siguiente); aquí basta unaccent + icontains.
    nombre = django_filters.CharFilter(
        field_name="nombre_display", lookup_expr="unaccent__icontains"
    )
    zona = django_filters.CharFilter(
        field_name="zona", lookup_expr="unaccent__icontains"
    )
    estado = django_filters.CharFilter(
        field_name="estado_actual", lookup_expr="iexact"
    )

    class Meta:
        model = PersonaCanonica
        fields = ["nombre", "zona", "estado"]
