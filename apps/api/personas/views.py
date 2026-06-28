"""Buscador público read-only sobre personas_canonicas.

Anillo de acceso "lectura pública" (plan §14): read-only + throttling fuerte +
privacy-filter en el serializer. Sin autenticación: el público nunca se registra.
"""
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets

from .filters import PersonaCanonicaFilter
from .models import ClusterLink, PersonaCanonica
from .serializers import PersonaCanonicaPublicSerializer


@extend_schema_view(
    list=extend_schema(
        summary="Buscar personas",
        description=(
            "Busca personas canónicas por nombre, zona y/o estado. Cada resultado "
            "aparece una sola vez y enlaza de vuelta a sus fuentes de origen. "
            "Solo expone datos públicos."
        ),
    ),
    retrieve=extend_schema(summary="Detalle de una persona + links a fuentes"),
)
class PersonaCanonicaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PersonaCanonicaPublicSerializer
    filterset_class = PersonaCanonicaFilter
    ordering_fields = ["updated_at"]
    ordering = ["-updated_at"]
    throttle_scope = "busqueda"

    def get_queryset(self):
        # Prefetch de los registros crudos enlazados, para edad/última-vez/fuentes
        # sin N+1. Nunca exponemos esos registros crudos directamente.
        return (
            PersonaCanonica.objects.all()
            .prefetch_related(
                Prefetch(
                    "links",
                    queryset=ClusterLink.objects.select_related("registro"),
                )
            )
            .order_by("-updated_at")
        )
