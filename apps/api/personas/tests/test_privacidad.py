"""Guardián de la LÍNEA ROJA de privacidad (plan §11/§14/§15).

Si algún día un campo prohibido (contacto, cédula cruda, face_embedding,
raw_payload) se filtra al serializer público, estos tests DEBEN fallar.

Nota: tipo_fuente SÍ es público en RegistroFuente (está en PUBLIC_REGISTRO_FIELDS
del plan §15), por lo que puede aparecer en respuestas que expandan registros
inline (ej. detalle de PersonaCanonica). Los campos verdaderamente prohibidos
son los enumerados en CAMPOS_PROHIBIDOS abajo.
"""
import json

from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from personas.models import ClusterLink, PersonaCanonica, RegistroFuente
from personas.serializers import PersonaCanonicaSerializer

RF_SIN_THROTTLE = {
    **settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}

LISTA_PERSONAS = "/api/v1/personas/"
LISTA_REGISTROS = "/api/v1/registros/"

CONTACTO_SECRETO = "0414-CONTACTO-PRIVADO-555"
CEDULA_SECRETA = "V-13860574"
EMBEDDING = [0.0123] * 512

# Campos que NUNCA pueden aparecer en ningún response público.
CAMPOS_PROHIBIDOS = {
    "contacto",
    "cedula",
    "face_embedding",
    "raw_payload",
    "responder",
    "responder_id",
}


@override_settings(REST_FRAMEWORK=RF_SIN_THROTTLE)
class PrivacidadPublicaTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.persona = PersonaCanonica.objects.create(
            nombre_display="María Pérez",
            cedula=CEDULA_SECRETA,
            zona="Carabobo",
            estado_actual="encontrado_vivo",
        )
        cls.registro = RegistroFuente.objects.create(
            tipo="buscado",
            fuente="dtv",
            id_origen="abc-123",
            url_origen="https://desaparecidos.example/abc-123",
            nombre="María Pérez",
            cedula=CEDULA_SECRETA,
            edad=34,
            zona="Carabobo",
            contacto=CONTACTO_SECRETO,
            face_embedding=EMBEDDING,
            tipo_fuente="hospital",
        )
        ClusterLink.objects.create(
            registro=cls.registro,
            persona=cls.persona,
            metodo="cedula",
            score=1.0,
            confirmado=True,
        )

    def _assert_sin_secretos(self, blob: str):
        self.assertNotIn(CONTACTO_SECRETO, blob, "¡Se filtró el contacto!")
        self.assertNotIn(CEDULA_SECRETA, blob, "¡Se filtró la cédula cruda!")
        self.assertNotIn("face_embedding", blob, "¡Se filtró el embedding facial!")
        self.assertNotIn("0.0123", blob, "¡Se filtró un valor del embedding!")
        for campo in CAMPOS_PROHIBIDOS:
            self.assertNotIn(f'"{campo}"', blob, f"¡Campo prohibido expuesto: {campo}!")

    # --- personas/ ---------------------------------------------------------------

    def test_lista_personas_no_filtra_datos_privados(self):
        resp = self.client.get(LISTA_PERSONAS)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    def test_detalle_persona_no_filtra_datos_privados(self):
        resp = self.client.get(f"{LISTA_PERSONAS}{self.persona.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    def test_serializer_lista_persona_expone_solo_allowlist(self):
        """El set de claves del serializer de lista es EXACTAMENTE el permitido."""
        factory = APIRequestFactory()
        request = factory.get(LISTA_PERSONAS)
        data = PersonaCanonicaSerializer(self.persona, context={"request": request}).data
        self.assertEqual(
            set(data.keys()),
            {"url", "nombre_display", "zona", "estado_actual", "foto_principal", "n_fuentes", "updated_at"},
        )

    # --- registros/ --------------------------------------------------------------

    def test_lista_registros_no_filtra_datos_privados(self):
        resp = self.client.get(LISTA_REGISTROS)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    def test_detalle_registro_no_filtra_datos_privados(self):
        resp = self.client.get(f"{LISTA_REGISTROS}{self.registro.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    # --- comportamiento público correcto -----------------------------------------

    def test_lista_personas_expone_campos_publicos(self):
        item = self.client.get(LISTA_PERSONAS).json()["results"][0]
        self.assertEqual(item["nombre_display"], "María Pérez")
        self.assertEqual(item["zona"], "Carabobo")
        self.assertEqual(item["estado_actual"], "encontrado_vivo")
        self.assertIn("url", item)
        self.assertIn("n_fuentes", item)

    def test_detalle_persona_expande_registros_inline(self):
        data = self.client.get(f"{LISTA_PERSONAS}{self.persona.id}/").json()
        self.assertIn("registros", data)
        self.assertEqual(len(data["registros"]), 1)
        reg = data["registros"][0]
        self.assertEqual(reg["fuente"], "dtv")
        self.assertEqual(reg["nombre"], "María Pérez")
        self.assertIn("url", reg)

    def test_detalle_registro_expande_persona_inline(self):
        data = self.client.get(f"{LISTA_REGISTROS}{self.registro.id}/").json()
        self.assertIn("persona", data)
        self.assertIsNotNone(data["persona"])
        self.assertEqual(data["persona"]["nombre_display"], "María Pérez")

    def test_filtros_busqueda_personas(self):
        self.assertEqual(self.client.get(f"{LISTA_PERSONAS}?nombre=maría").json()["count"], 1)
        self.assertEqual(self.client.get(f"{LISTA_PERSONAS}?nombre=zoltan").json()["count"], 0)
        self.assertEqual(self.client.get(f"{LISTA_PERSONAS}?zona=carabobo").json()["count"], 1)
        self.assertEqual(
            self.client.get(f"{LISTA_PERSONAS}?estado=encontrado_vivo").json()["count"], 1
        )

    def test_filtros_busqueda_registros(self):
        self.assertEqual(self.client.get(f"{LISTA_REGISTROS}?fuente=dtv").json()["count"], 1)
        self.assertEqual(self.client.get(f"{LISTA_REGISTROS}?fuente=vtb").json()["count"], 0)
        self.assertEqual(
            self.client.get(f"{LISTA_REGISTROS}?estado_rep=encontrado_vivo").json()["count"], 0
        )
        self.assertEqual(self.client.get(f"{LISTA_REGISTROS}?zona=carabobo").json()["count"], 1)
