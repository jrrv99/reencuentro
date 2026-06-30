"""Filtros del buscador público: ?nombre=&zona=&estado=&fuente=&tipo_fuente=…"""
import django_filters

from .models import PersonaCanonica, RegistroFuente


class PersonaCanonicaFilter(django_filters.FilterSet):
    # Búsqueda por nombre: insensible a acentos y mayúsculas (plan §15).
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


class RegistroFuenteFilter(django_filters.FilterSet):
    zona = django_filters.CharFilter(
        field_name="zona", lookup_expr="unaccent__icontains"
    )
    fuente = django_filters.CharFilter(field_name="fuente", lookup_expr="iexact")
    estado_rep = django_filters.CharFilter(
        field_name="estado_rep", lookup_expr="iexact"
    )
    tipo_fuente = django_filters.CharFilter(
        field_name="tipo_fuente", lookup_expr="iexact"
    )

    class Meta:
        model = RegistroFuente
        fields = ["fuente", "zona", "estado_rep", "tipo_fuente"]
