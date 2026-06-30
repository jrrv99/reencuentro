"""ViewSets públicos read-only — patrón lista/detalle del plan §15.

Anillo de acceso "lectura pública": read-only + throttling fuerte +
privacy-filter en el serializer. Sin autenticación: el público nunca se registra.

Convención obligatoria:
  get_serializer_class devuelve el serializer de lista o detalle según la acción.
"""
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, viewsets

from .filters import PersonaCanonicaFilter, RegistroFuenteFilter
from .models import ClusterLink, PersonaCanonica, RegistroFuente
from .serializers import (
    PersonaCanonicaDetailSerializer,
    PersonaCanonicaSerializer,
    RegistroFuenteDetailSerializer,
    RegistroFuenteSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="Buscar personas",
        description=(
            "Busca personas canónicas por nombre, zona y/o estado. Cada resultado "
            "aparece una sola vez y enlaza de vuelta a sus fuentes de origen. "
            "Solo expone datos públicos."
        ),
    ),
    retrieve=extend_schema(
        summary="Detalle de una persona + registros fuente expandidos inline",
    ),
)
class PersonaCanonicaViewSet(viewsets.ReadOnlyModelViewSet):
    filterset_class = PersonaCanonicaFilter
    filter_backends = [
        # DjangoFilterBackend lo inyecta settings.DEFAULT_FILTER_BACKENDS;
        # aquí declaramos explícitamente los tres para documentación y control.
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = ["nombre_display", "zona"]
    ordering_fields = ["updated_at", "n_fuentes"]
    ordering = ["-updated_at"]
    throttle_scope = "busqueda"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PersonaCanonicaDetailSerializer
        return PersonaCanonicaSerializer

    def get_queryset(self):
        return PersonaCanonica.objects.prefetch_related(
            Prefetch(
                "links",
                queryset=ClusterLink.objects.select_related("registro"),
            )
        ).order_by("-updated_at")


@extend_schema_view(
    list=extend_schema(
        summary="Listar registros fuente",
        description=(
            "Listado filtrable de registros crudos (1 por fuente por reporte). "
            "Útil para debug/admin y para el frontend que quiere ver de dónde "
            "viene cada dato. Solo expone campos públicos."
        ),
    ),
    retrieve=extend_schema(
        summary="Detalle de un registro fuente + persona canónica enlazada inline",
    ),
)
class RegistroFuenteViewSet(viewsets.ReadOnlyModelViewSet):
    filterset_class = RegistroFuenteFilter
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = ["nombre", "zona"]
    ordering_fields = ["ingested_at", "confianza"]
    ordering = ["-ingested_at"]
    throttle_scope = "busqueda"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return RegistroFuenteDetailSerializer
        return RegistroFuenteSerializer

    def get_queryset(self):
        if self.action == "retrieve":
            return RegistroFuente.objects.select_related("cluster_link__persona")
        return RegistroFuente.objects.all()
