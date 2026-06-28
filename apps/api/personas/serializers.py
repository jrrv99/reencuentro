"""Serializers PÚBLICOS.

LÍNEA ROJA (plan §11/§14, no negociable): la salida pública expone SOLO
nombre, zona, edad aprox, estado, última vez visto y links a fuentes.
NUNCA contacto, cédula cruda, identidad de responders ni face_embedding.

Por diseño defensivo NO usamos `fields = "__all__"` ni exponemos el modelo
RegistroFuente entero: declaramos campo por campo, en allow-list. El test
personas/tests/test_privacidad.py falla si algo prohibido se llegara a filtrar.
"""
from rest_framework import serializers

from .models import PersonaCanonica


class FuenteLinkSerializer(serializers.Serializer):
    """Link de vuelta al origen. Solo nombre de fuente + URL pública. Nada más."""

    fuente = serializers.CharField()
    url_origen = serializers.URLField(allow_null=True)


class PersonaCanonicaPublicSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source="nombre_display", allow_null=True)
    estado = serializers.CharField(source="estado_actual", allow_null=True)
    edad_aprox = serializers.SerializerMethodField()
    ultima_vez_visto = serializers.SerializerMethodField()
    fuentes = serializers.SerializerMethodField()

    class Meta:
        model = PersonaCanonica
        # Allow-list explícita. Cualquier campo NO listado jamás se serializa.
        fields = ["id", "nombre", "zona", "edad_aprox", "estado", "ultima_vez_visto", "fuentes"]

    def _registros(self, persona):
        # registros crudos enlazados a esta persona (vía cluster_links).
        return [link.registro for link in persona.links.all() if link.registro_id]

    def get_edad_aprox(self, persona):
        """Edad en rango (década), nunca el número exacto — es *aprox*."""
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
        vistos, salida = set(), []
        for r in self._registros(persona):
            if r.fuente in vistos:
                continue
            vistos.add(r.fuente)
            salida.append({"fuente": r.fuente, "url_origen": r.url_origen})
        return FuenteLinkSerializer(salida, many=True).data
