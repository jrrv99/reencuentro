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


class FuenteLinkSerializer(serializers.Serializer):
    """Link de vuelta al origen. Solo nombre de fuente + URL pública. Nada más."""

    fuente = serializers.CharField()
    url_origen = serializers.URLField(allow_null=True)


class RegistroFuenteSerializer(serializers.HyperlinkedModelSerializer):
    """Lista de registros fuente: campos públicos + URL propia."""

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
    """Lista de personas canónicas: campos públicos + computed fields UX.

    Mantiene los SerializerMethodFields del diseño original:
      - edad_aprox   → rango de década (privacidad: nunca la edad exacta)
      - ultima_vez_visto → derivado de los registros enlazados
      - fuentes      → lista deduplicada de links de vuelta (el corazón del producto)
    """

    nombre = serializers.CharField(source="nombre_display", allow_null=True)
    estado = serializers.CharField(source="estado_actual", allow_null=True)
    edad_aprox = serializers.SerializerMethodField()
    ultima_vez_visto = serializers.SerializerMethodField()
    fuentes = serializers.SerializerMethodField()

    class Meta:
        model = PersonaCanonica
        fields = [
            "url",
            "nombre",
            "zona",
            "estado",
            "foto_principal",
            "n_fuentes",
            "edad_aprox",
            "ultima_vez_visto",
            "fuentes",
            "updated_at",
        ]
        extra_kwargs = {
            "url": {"view_name": "v1:persona-detail"},
        }

    def _registros(self, persona):
        # Usa el prefetch_related configurado en PersonaCanonicaViewSet.get_queryset()
        # para evitar N+1. El .all() accede a la caché del prefetch.
        return [link.registro for link in persona.links.all() if link.registro_id]

    def get_edad_aprox(self, persona):
        """Edad en rango de década. Nunca el número exacto — privacidad por diseño."""
        edades = [r.edad for r in self._registros(persona) if r.edad is not None]
        if not edades:
            return None
        edad = round(sum(edades) / len(edades))
        base = (edad // 10) * 10
        return f"{base}-{base + 9}"

    def get_ultima_vez_visto(self, persona):
        fechas = [r.ingested_at for r in self._registros(persona) if r.ingested_at]
        return max(fechas).isoformat() if fechas else None

    def get_fuentes(self, persona):
        """Links de vuelta a cada fuente de origen. Deduplicados por fuente."""
        vistos, salida = set(), []
        for r in self._registros(persona):
            if r.fuente in vistos:
                continue
            vistos.add(r.fuente)
            salida.append({"fuente": r.fuente, "url_origen": r.url_origen})
        return FuenteLinkSerializer(salida, many=True).data


class PersonaCanonicaDetailSerializer(PersonaCanonicaSerializer):
    """Detalle de una persona canónica: añade los registros fuente expandidos inline."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # instance.links usa la caché del prefetch — sin N+1.
        registros = [cl.registro for cl in instance.links.all() if cl.registro_id]
        data["registros"] = RegistroFuenteSerializer(
            registros, many=True, context=self.context
        ).data
        return data
