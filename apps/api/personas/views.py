"""ViewSets — lectura pública + escritura restringida a responders (plan §15/§9).

Anillos de acceso:
  Lectura pública  → sin auth, read-only, privacy-filter en serializer
  Escritura        → JWT + Responder activo (POST /registros/ para hospitales)

Convención obligatoria:
  get_serializer_class devuelve el serializer de lista, detalle o escritura según acción.
"""
import uuid

from django.db import transaction
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .choices import TipoFuente
from .filters import PersonaCanonicaFilter, RegistroFuenteFilter
from .models import ClusterLink, PersonaCanonica, RegistroFuente
from .serializers import (
    PersonaCanonicaDetailSerializer,
    PersonaCanonicaSerializer,
    RegistroFuenteDetailSerializer,
    RegistroFuenteSerializer,
    RegistroFuenteWriteSerializer,
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
            "Útil para debug/admin y para el frontend. Solo expone campos públicos."
        ),
    ),
    retrieve=extend_schema(
        summary="Detalle de un registro fuente + persona canónica enlazada inline",
    ),
    create=extend_schema(
        summary="Registrar persona (responder — JWT requerido)",
        description=(
            "Crea un RegistroFuente desde el workspace del responder autenticado. "
            "Fuente, tipo_fuente y confianza se derivan de la institución. "
            "El campo 'contacto' es privado y no aparece en la respuesta."
        ),
    ),
)
class RegistroFuenteViewSet(viewsets.ModelViewSet):
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
    http_method_names = ["get", "post", "head", "options"]  # sin PUT/PATCH/DELETE

    def get_serializer_class(self):
        if self.action == "create":
            return RegistroFuenteWriteSerializer
        if self.action == "retrieve":
            return RegistroFuenteDetailSerializer
        return RegistroFuenteSerializer

    def get_permissions(self):
        if self.action == "create":
            from instituciones.permissions import IsResponderActivo
            return [IsAuthenticated(), IsResponderActivo()]
        return []

    def get_queryset(self):
        if self.action == "retrieve":
            return RegistroFuente.objects.select_related("cluster_link__persona")
        return RegistroFuente.objects.all()

    def create(self, request, *args, **kwargs):
        write_ser = self.get_serializer(data=request.data)
        write_ser.is_valid(raise_exception=True)

        # Gate fallecido: requiere institución verificada
        if write_ser.validated_data.get("estado_rep") == "fallecido":
            from instituciones.permissions import IsInstitucionVerificada
            perm = IsInstitucionVerificada()
            if not perm.has_permission(request, self):
                return Response({"detail": perm.message}, status=status.HTTP_403_FORBIDDEN)

        self.perform_create(write_ser)
        read_ser = RegistroFuenteSerializer(
            write_ser.instance, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(read_ser.data)
        return Response(read_ser.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        responder = self.request.user.responder
        institucion = responder.institucion
        confianza = 0.9 if institucion.verificada else 0.7
        tipo_fuente = (
            institucion.tipo
            if institucion.tipo in (
                TipoFuente.HOSPITAL, TipoFuente.CLINICA,
                TipoFuente.OFICIAL, TipoFuente.PARTNER,
            )
            else TipoFuente.RESCATISTA
        )
        registro = serializer.save(
            fuente=institucion.fuente_slug,
            tipo_fuente=tipo_fuente,
            confianza=confianza,
            id_origen=str(uuid.uuid4()),
        )
        transaction.on_commit(lambda: _encolar_dedup(str(registro.id)))


def _encolar_dedup(registro_id: str) -> None:
    try:
        from dedup.tasks import dedup_record
        dedup_record.delay(registro_id)
    except Exception:
        import logging
        logging.getLogger(__name__).debug(
            "dedup_record no encolado para %s (broker no disponible)", registro_id
        )
