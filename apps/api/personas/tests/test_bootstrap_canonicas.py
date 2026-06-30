"""Tests del management command bootstrap_canonicas.

La invariante central: CANTIDAD_CANONICAS < CANTIDAD_REGISTROS siempre que
alguna cédula aparezca en más de un registro (caso normal con datos reales).
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from personas.models import ClusterLink, PersonaCanonica, RegistroFuente


def _registro(n, fuente="dtv", cedula=None, zona="Caracas", **kwargs):
    return RegistroFuente.objects.create(
        tipo="buscado",
        fuente=fuente,
        id_origen=f"{fuente}-{n}",
        nombre=f"Persona {n}",
        zona=zona,
        cedula=cedula,
        **kwargs,
    )


class BootstrapAgrupabledPorCedulaTests(TestCase):
    """La garantía principal: misma cedula_norm → una sola PersonaCanonica."""

    def test_misma_cedula_en_dos_fuentes_genera_una_sola_canonica(self):
        r1 = _registro(1, fuente="dtv", cedula="V-12345678")
        r2 = _registro(2, fuente="vtb", cedula="12345678")  # mismo número, distinto formato

        call_command("bootstrap_canonicas", stdout=StringIO())

        # Una sola canónica para los dos registros
        self.assertEqual(PersonaCanonica.objects.count(), 1)
        self.assertEqual(ClusterLink.objects.count(), 2)

        persona = PersonaCanonica.objects.get()
        self.assertEqual(persona.n_fuentes, 2)

        link1 = ClusterLink.objects.get(registro=r1)
        link2 = ClusterLink.objects.get(registro=r2)
        self.assertEqual(link1.persona, persona)
        self.assertEqual(link2.persona, persona)
        self.assertEqual(link1.metodo, "cedula")
        self.assertEqual(link2.metodo, "cedula")
        self.assertTrue(link1.confirmado)
        self.assertTrue(link2.confirmado)

    def test_cedulas_distintas_generan_canonicas_distintas(self):
        _registro(1, cedula="V-11111111")
        _registro(2, cedula="V-22222222")

        call_command("bootstrap_canonicas", stdout=StringIO())

        self.assertEqual(PersonaCanonica.objects.count(), 2)
        self.assertEqual(ClusterLink.objects.count(), 2)

    def test_n_registros_sin_cedula_genera_n_canonicas(self):
        _registro(1, cedula=None)
        _registro(2, cedula=None)
        _registro(3, cedula=None)

        call_command("bootstrap_canonicas", stdout=StringIO())

        self.assertEqual(PersonaCanonica.objects.count(), 3)
        self.assertEqual(ClusterLink.objects.count(), 3)

        for link in ClusterLink.objects.all():
            self.assertEqual(link.metodo, "bootstrap")

    def test_mix_con_y_sin_cedula(self):
        # 3 registros con misma cédula (1 canónica) + 2 sin cédula (2 canónicas)
        _registro(1, fuente="dtv", cedula="V-99999999")
        _registro(2, fuente="vtb", cedula="V-99999999")
        _registro(3, fuente="venapp", cedula="V-99999999")
        _registro(4, cedula=None)
        _registro(5, cedula=None)

        call_command("bootstrap_canonicas", stdout=StringIO())

        # 1 (por cédula) + 2 (sin cédula) = 3
        self.assertEqual(PersonaCanonica.objects.count(), 3)
        self.assertEqual(ClusterLink.objects.count(), 5)
        # La canónica por cédula tiene n_fuentes=3
        persona_cedula = PersonaCanonica.objects.get(n_fuentes=3)
        self.assertEqual(ClusterLink.objects.filter(persona=persona_cedula).count(), 3)


class BootstrapCanonicasIdempotenciaTests(TestCase):

    def test_segunda_corrida_no_duplica(self):
        _registro(1, cedula="V-12345678")
        _registro(2, cedula="V-12345678")  # misma cédula
        _registro(3, cedula=None)

        call_command("bootstrap_canonicas", stdout=StringIO())
        call_command("bootstrap_canonicas", stdout=StringIO())

        self.assertEqual(PersonaCanonica.objects.count(), 2)  # 1 por cédula + 1 sin
        self.assertEqual(ClusterLink.objects.count(), 3)

    def test_no_toca_registros_con_link_existente(self):
        r_existente = _registro(1, cedula="V-11111111")
        persona_original = PersonaCanonica.objects.create(nombre_display="Ya tenía")
        ClusterLink.objects.create(
            registro=r_existente,
            persona=persona_original,
            score=1.0,
            metodo="manual",
            confirmado=True,
        )
        r_nuevo = _registro(2, cedula="V-11111111")  # misma cédula, sin link

        call_command("bootstrap_canonicas", stdout=StringIO())

        # r_existente sigue en persona_original; r_nuevo tiene su propia canónica
        link_existente = ClusterLink.objects.get(registro=r_existente)
        self.assertEqual(link_existente.persona, persona_original)
        self.assertEqual(link_existente.metodo, "manual")

        link_nuevo = ClusterLink.objects.get(registro=r_nuevo)
        self.assertNotEqual(link_nuevo.persona, persona_original)
        self.assertEqual(link_nuevo.metodo, "cedula")


class BootstrapRepresentanteTests(TestCase):
    """El representante del grupo es el registro con más campos rellenos."""

    def test_representante_es_el_mas_completo(self):
        # r1 tiene solo nombre; r2 tiene nombre+zona+foto+estado
        _registro(1, cedula="V-12345678", zona=None, foto_url=None, estado_rep=None)
        _registro(
            2,
            fuente="vtb",
            cedula="V-12345678",
            zona="Carabobo",
            foto_url="https://img.example/foto.jpg",
            estado_rep="encontrado_vivo",
        )

        call_command("bootstrap_canonicas", stdout=StringIO())

        persona = PersonaCanonica.objects.get()
        self.assertEqual(persona.zona, "Carabobo")
        self.assertEqual(persona.foto_principal, "https://img.example/foto.jpg")
        self.assertEqual(persona.estado_actual, "encontrado_vivo")

    def test_copia_campos_de_registro_a_canonica(self):
        _registro(1, cedula=None, estado_rep="encontrado_vivo", foto_url="https://x.com/f.jpg")

        call_command("bootstrap_canonicas", stdout=StringIO())

        persona = PersonaCanonica.objects.get()
        self.assertEqual(persona.estado_actual, "encontrado_vivo")
        self.assertEqual(persona.foto_principal, "https://x.com/f.jpg")
