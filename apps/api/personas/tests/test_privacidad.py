"""Guardián de la LÍNEA ROJA de privacidad (plan §11/§14).

Si algún día un campo prohibido (contacto, cédula cruda, identidad de responder,
face_embedding) se filtra al serializer público, estos tests DEBEN fallar.
"""
import json

from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from personas.models import ClusterLink, PersonaCanonica, RegistroFuente
from personas.serializers import PersonaCanonicaPublicSerializer

# Mismo REST_FRAMEWORK del proyecto pero sin throttling, para que los tests no
# dependan de Redis ni se vuelvan flaky al re-correrlos dentro de la misma ventana.
RF_SIN_THROTTLE = {
    **settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}

LISTA = "/api/v1/personas/"

# Valores sensibles sembrados en el registro crudo. NINGUNO puede aparecer en la
# respuesta pública, ni como valor ni como nombre de campo.
CONTACTO_SECRETO = "0414-CONTACTO-PRIVADO-555"
CEDULA_SECRETA = "V-13860574"
EMBEDDING = [0.0123] * 512

CAMPOS_PROHIBIDOS = {
    "contacto",
    "cedula",
    "face_embedding",
    "raw_payload",
    "tipo_fuente",  # identidad/origen del responder
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
            contacto=CONTACTO_SECRETO,  # PRIVADO
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

    # --- la prueba que importa --------------------------------------------------
    def _assert_sin_secretos(self, blob: str):
        self.assertNotIn(CONTACTO_SECRETO, blob, "¡Se filtró el contacto!")
        self.assertNotIn(CEDULA_SECRETA, blob, "¡Se filtró la cédula cruda!")
        self.assertNotIn("face_embedding", blob, "¡Se filtró el embedding facial!")
        self.assertNotIn("0.0123", blob, "¡Se filtró un valor del embedding!")
        for campo in CAMPOS_PROHIBIDOS:
            self.assertNotIn(f'"{campo}"', blob, f"¡Campo prohibido expuesto: {campo}!")

    def test_lista_no_filtra_datos_privados(self):
        resp = self.client.get(LISTA)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    def test_detalle_no_filtra_datos_privados(self):
        resp = self.client.get(f"{LISTA}{self.persona.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self._assert_sin_secretos(json.dumps(resp.json()))

    def test_serializer_solo_expone_allowlist(self):
        """Blindaje extra: el set de claves del serializer es EXACTAMENTE el permitido."""
        data = PersonaCanonicaPublicSerializer(self.persona).data
        self.assertEqual(
            set(data.keys()),
            {"id", "nombre", "zona", "edad_aprox", "estado", "ultima_vez_visto", "fuentes"},
        )
        # Las fuentes solo llevan nombre de fuente + URL de vuelta.
        for fuente in data["fuentes"]:
            self.assertEqual(set(fuente.keys()), {"fuente", "url_origen"})

    # --- comportamiento público correcto ---------------------------------------
    def test_expone_campos_publicos_y_linkback(self):
        item = self.client.get(LISTA).json()["results"][0]
        self.assertEqual(item["nombre"], "María Pérez")
        self.assertEqual(item["zona"], "Carabobo")
        self.assertEqual(item["estado"], "encontrado_vivo")
        self.assertEqual(item["edad_aprox"], "30-39")  # aprox, nunca el número exacto
        self.assertIsNotNone(item["ultima_vez_visto"])
        self.assertEqual(item["fuentes"][0]["fuente"], "dtv")
        self.assertEqual(
            item["fuentes"][0]["url_origen"],
            "https://desaparecidos.example/abc-123",
        )

    def test_filtros_busqueda(self):
        self.assertEqual(self.client.get(f"{LISTA}?nombre=maría").json()["count"], 1)
        self.assertEqual(self.client.get(f"{LISTA}?nombre=zoltan").json()["count"], 0)
        self.assertEqual(self.client.get(f"{LISTA}?zona=carabobo").json()["count"], 1)
        self.assertEqual(
            self.client.get(f"{LISTA}?estado=encontrado_vivo").json()["count"], 1
        )
