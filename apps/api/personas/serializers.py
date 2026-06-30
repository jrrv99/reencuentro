"""Serializers PÚBLICOS — patrón lista / detalle con HyperlinkedModelSerializer.

LÍNEA ROJA (plan §11/§14/§15, no negociable): la salida pública expone SOLO
los campos de PUBLIC_REGISTRO_FIELDS y los campos públicos de PersonaCanonica.
NUNCA contacto, cédula cruda, face_embedding, raw_payload ni identidad de responders.

Convención obligatoria (plan §15):
  - Base: HyperlinkedModelSerializer. Relaciones = URLs en lista.
  - Detalle: to_representation expande relaciones inline.
  - allow-list en fields = [...]. Si no está en fields, no existe en el output.
    NUNCA se filtra con `if campo in ...`.
"""
from rest_framework import serializers

from .models import PersonaCanonica, RegistroFuente

# Campos públicos de RegistroFuente (plan §15). Esta constante es la allow-list
# autoritativa — cualquier cambio aquí se refleja en la API y en los tests.
PUBLIC_REGISTRO_FIELDS = [
    "url",
    "fuente",
    "url_origen",
    "tipo",
    "nombre",
    "edad",
    "sexo",
    "zona",
    "ubicacion",
    "descripcion",
    "foto_url",
    "estado_rep",
    "tipo_fuente",
    "confianza",
    "ingested_at",
]


class RegistroFuenteSerializer(serializers.HyperlinkedModelSerializer):
    """Lista de registros fuente: campos públicos + URL canónica."""

    class Meta:
        model = RegistroFuente
        fields = PUBLIC_REGISTRO_FIELDS
        extra_kwargs = {
            "url": {"view_name": "v1:registro-detail"},
        }


class RegistroFuenteDetailSerializer(RegistroFuenteSerializer):
    """Detalle de un registro fuente: expande la PersonaCanonica enlazada inline."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        persona = None
        link = getattr(instance, "cluster_link", None)
        if link is not None and link.persona_id:
            persona = PersonaCanonicaSerializer(link.persona, context=self.context).data
        data["persona"] = persona
        return data


class PersonaCanonicaSerializer(serializers.HyperlinkedModelSerializer):
    """Lista de personas canónicas: campos públicos de la entidad resuelta."""

    class Meta:
        model = PersonaCanonica
        fields = [
            "url",
            "nombre_display",
            "zona",
            "estado_actual",
            "foto_principal",
            "n_fuentes",
            "updated_at",
        ]
        extra_kwargs = {
            "url": {"view_name": "v1:persona-detail"},
        }


class PersonaCanonicaDetailSerializer(PersonaCanonicaSerializer):
    """Detalle de una persona canónica: expande los registros fuente enlazados inline."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # instance.links es el prefetch de ClusterLink.select_related("registro")
        # configurado en PersonaCanonicaViewSet.get_queryset(). Acceder con .all()
        # usa la caché del prefetch y evita el N+1.
        registros = [cl.registro for cl in instance.links.all() if cl.registro_id]
        data["registros"] = RegistroFuenteSerializer(
            registros, many=True, context=self.context
        ).data
        return data
