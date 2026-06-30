"""Serializers para Institucion, Responder y EstadoClaim (escritura)."""
from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from personas.models import EstadoClaim, PersonaCanonica

from .models import Institucion, Responder

User = get_user_model()


# ---------------------------------------------------------------------------
# Institución
# ---------------------------------------------------------------------------


class InstitucionSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Institucion
        fields = [
            "url", "nombre", "tipo", "zona", "verificada", "activa",
            "dominio_email", "created_at",
        ]
        extra_kwargs = {
            "url": {"view_name": "v1:institucion-detail"},
            "created_at": {"read_only": True},
        }


class InstitucionDetailSerializer(InstitucionSerializer):
    n_responders = serializers.SerializerMethodField()

    class Meta(InstitucionSerializer.Meta):
        fields = InstitucionSerializer.Meta.fields + ["n_responders"]

    @extend_schema_field(serializers.IntegerField())
    def get_n_responders(self, obj):
        return obj.responders.filter(activo=True).count()


# ---------------------------------------------------------------------------
# Responder
# ---------------------------------------------------------------------------


class ResponderSerializer(serializers.HyperlinkedModelSerializer):
    nombre_completo = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    institucion = serializers.HyperlinkedRelatedField(
        view_name="v1:institucion-detail", read_only=True
    )

    class Meta:
        model = Responder
        fields = [
            "url", "nombre_completo", "email", "institucion", "rol", "activo", "created_at",
        ]
        extra_kwargs = {"url": {"view_name": "v1:responder-detail"}}

    @extend_schema_field(serializers.CharField())
    def get_nombre_completo(self, obj):
        return obj.user.get_full_name() or obj.user.username


class ResponderCreateSerializer(serializers.Serializer):
    """Crea Django User + Responder atómicamente."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    rol = serializers.ChoiceField(choices=["miembro", "admin"], default="miembro")
    # institucion es opcional: workspace admins lo omiten (el view lo inyecta de su propio workspace)
    institucion = serializers.PrimaryKeyRelatedField(
        queryset=Institucion.objects.all(), required=False, allow_null=True
    )

    def validate_email(self, email):
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return email.lower()

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        email = validated_data.pop("email")
        first_name = validated_data.pop("first_name")
        last_name = validated_data.pop("last_name")
        rol = validated_data.pop("rol", "miembro")
        institucion = validated_data.pop("institucion", None)

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        return Responder.objects.create(user=user, institucion=institucion, rol=rol)


# ---------------------------------------------------------------------------
# EstadoClaim (lectura pública + escritura para responders)
# ---------------------------------------------------------------------------


class EstadoClaimSerializer(serializers.HyperlinkedModelSerializer):
    persona = serializers.HyperlinkedRelatedField(
        view_name="v1:persona-detail", read_only=True
    )

    class Meta:
        model = EstadoClaim
        fields = [
            "url", "persona", "estado", "ubicacion",
            "autor_tipo", "vigente", "disputado", "created_at",
        ]
        extra_kwargs = {"url": {"view_name": "v1:claim-detail"}}


ESTADOS_VALIDOS = {
    "sin_contacto", "encontrado_vivo", "herido",
    "hospitalizado", "refugiado", "fallecido",
}


class EstadoClaimWriteSerializer(serializers.ModelSerializer):
    """Escritura de claims por responders. La vista inyecta autor_tipo y autor_id."""

    class Meta:
        model = EstadoClaim
        fields = ["persona", "estado", "ubicacion", "corrobora_a"]

    def validate_estado(self, value):
        if value not in ESTADOS_VALIDOS:
            raise serializers.ValidationError(
                f"Estado no válido. Opciones: {', '.join(sorted(ESTADOS_VALIDOS))}"
            )
        return value

    def validate(self, data):
        if data.get("estado") == "fallecido" and not data.get("corrobora_a"):
            raise serializers.ValidationError(
                {"corrobora_a": "Registrar 'fallecido' requiere corroboración (corrobora_a)."}
            )
        return data
