"""ViewSets para Institucion, Responder y EstadoClaim.

Anillos de acceso (plan §8):
  Institución:   lectura pública | escritura solo staff
  Responder:     lectura/escritura para workspace admin; staff ve todo
  EstadoClaim:   lectura pública | escritura para responders activos
"""
import uuid

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, serializers, status, viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from personas.choices import AutorTipo
from personas.models import EstadoClaim, PersonaCanonica

from .models import Institucion, Responder
from .permissions import IsInstitucionVerificada, IsResponderActivo, IsWorkspaceAdmin
from .serializers import (
    EstadoClaimSerializer,
    EstadoClaimWriteSerializer,
    InstitucionDetailSerializer,
    InstitucionSerializer,
    ResponderCreateSerializer,
    ResponderSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="Listar instituciones"),
    retrieve=extend_schema(summary="Detalle de institución"),
    create=extend_schema(summary="Crear institución (staff)"),
    update=extend_schema(summary="Actualizar institución (staff)"),
    partial_update=extend_schema(summary="Actualizar parcialmente (staff)"),
    destroy=extend_schema(summary="Eliminar institución (staff)"),
)
class InstitucionViewSet(viewsets.ModelViewSet):
    queryset = Institucion.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["tipo", "verificada", "activa"]
    search_fields = ["nombre", "zona"]
    ordering_fields = ["nombre", "created_at"]
    ordering = ["nombre"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InstitucionDetailSerializer
        return InstitucionSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return []
        return [IsAdminUser()]


@extend_schema_view(
    list=extend_schema(summary="Listar responders (workspace)"),
    retrieve=extend_schema(summary="Detalle de responder"),
    create=extend_schema(summary="Crear responder (workspace admin)"),
    update=extend_schema(summary="Actualizar responder (workspace admin)"),
    partial_update=extend_schema(summary="Actualizar parcialmente (workspace admin)"),
    destroy=extend_schema(summary="Desactivar responder (workspace admin)"),
)
class ResponderViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["rol", "activo", "institucion"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return ResponderCreateSerializer
        return ResponderSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            # is_staff ve todo; responders ven su workspace; el queryset lo filtra
            return [IsAuthenticated()]
        if self.action == "create":
            return [IsAuthenticated(), IsWorkspaceAdmin()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsWorkspaceAdmin()]
        return [IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Responder.objects.none()
        if user.is_staff:
            return Responder.objects.select_related("user", "institucion").all()
        if hasattr(user, "responder") and user.responder.activo:
            return Responder.objects.select_related("user", "institucion").filter(
                institucion=user.responder.institucion
            )
        return Responder.objects.none()

    def create(self, request, *args, **kwargs):
        write_ser = self.get_serializer(data=request.data)
        write_ser.is_valid(raise_exception=True)
        self.perform_create(write_ser)
        read_ser = ResponderSerializer(
            write_ser.instance, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(read_ser.data)
        return Response(read_ser.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_staff and hasattr(user, "responder"):
            # Workspace admin: crea solo en su propia institución
            serializer.save(institucion=user.responder.institucion)
        else:
            if not serializer.validated_data.get("institucion"):
                raise serializers.ValidationError(
                    {"institucion": "Los administradores deben especificar la institución."}
                )
            serializer.save()

    def perform_destroy(self, instance):
        # Soft delete: marcar como inactivo en vez de borrar
        instance.activo = False
        instance.save(update_fields=["activo"])


@extend_schema_view(
    list=extend_schema(summary="Listar claims de estado"),
    retrieve=extend_schema(summary="Detalle de un claim"),
    create=extend_schema(summary="Registrar estado (responder)"),
)
class EstadoClaimViewSet(viewsets.GenericViewSet,
                         viewsets.mixins.ListModelMixin,
                         viewsets.mixins.RetrieveModelMixin,
                         viewsets.mixins.CreateModelMixin):
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["persona", "estado", "vigente"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return EstadoClaim.objects.select_related("persona").all()

    def get_serializer_class(self):
        if self.action == "create":
            return EstadoClaimWriteSerializer
        return EstadoClaimSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return []
        return [IsAuthenticated(), IsResponderActivo()]

    def create(self, request, *args, **kwargs):
        # Gate fallecido ANTES de validar el serializer: 403 (autorización) > 400 (validación)
        from personas.choices import EstadoRep
        if request.data.get("estado") == EstadoRep.FALLECIDO:
            perm = IsInstitucionVerificada()
            if not perm.has_permission(request, self):
                return Response({"detail": perm.message}, status=status.HTTP_403_FORBIDDEN)

        write_ser = self.get_serializer(data=request.data)
        write_ser.is_valid(raise_exception=True)
        self.perform_create(write_ser)
        read_ser = EstadoClaimSerializer(
            write_ser.instance, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(read_ser.data)
        return Response(read_ser.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        responder = self.request.user.responder
        claim = serializer.save(
            autor_tipo=AutorTipo.RESPONDER,
            autor_responder=responder,
            vigente=True,
        )
        # Actualiza estado_actual de la canónica
        persona: PersonaCanonica = claim.persona
        persona.estado_actual = claim.estado
        persona.updated_at = timezone.now()
        persona.save(update_fields=["estado_actual", "updated_at"])
