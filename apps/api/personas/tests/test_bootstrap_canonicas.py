"""Tests del management command bootstrap_canonicas."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from personas.models import ClusterLink, PersonaCanonica, RegistroFuente


def _registro(n, **kwargs):
    return RegistroFuente.objects.create(
        tipo="buscado",
        fuente="dtv",
        id_origen=f"test-{n}",
        nombre=f"Persona {n}",
        zona="Caracas",
        **kwargs,
    )


class BootstrapCanonicasTests(TestCase):
    def test_crea_canonicas_para_registros_sin_link(self):
        r1 = _registro(1)
        r2 = _registro(2)

        out = StringIO()
        call_command("bootstrap_canonicas", stdout=out)

        self.assertEqual(PersonaCanonica.objects.count(), 2)
        self.assertEqual(ClusterLink.objects.count(), 2)

        link1 = ClusterLink.objects.get(registro=r1)
        self.assertEqual(link1.metodo, "bootstrap")
        self.assertEqual(link1.score, 1.0)
        self.assertTrue(link1.confirmado)
        self.assertEqual(link1.persona.nombre_display, "Persona 1")
        self.assertEqual(link1.persona.zona, "Caracas")

        self.assertIn("2", out.getvalue())

    def test_idempotente_segunda_corrida_no_duplica(self):
        _registro(1)
        call_command("bootstrap_canonicas", stdout=StringIO())

        # Segunda corrida: nada nuevo
        out = StringIO()
        call_command("bootstrap_canonicas", stdout=out)

        self.assertEqual(PersonaCanonica.objects.count(), 1)
        self.assertEqual(ClusterLink.objects.count(), 1)
        self.assertIn("0", out.getvalue())

    def test_no_toca_registros_con_link_existente(self):
        r_con_link = _registro(1)
        persona = PersonaCanonica.objects.create(nombre_display="Ya tenía", zona="Lara")
        ClusterLink.objects.create(
            registro=r_con_link, persona=persona, score=1.0, metodo="cedula", confirmado=True
        )
        r_sin_link = _registro(2)

        call_command("bootstrap_canonicas", stdout=StringIO())

        # Solo se crea la canónica para r_sin_link
        self.assertEqual(PersonaCanonica.objects.count(), 2)
        # El link de r_con_link sigue apuntando a la persona original
        self.assertEqual(ClusterLink.objects.get(registro=r_con_link).persona, persona)
        # r_sin_link ahora tiene link (método bootstrap)
        self.assertEqual(ClusterLink.objects.get(registro=r_sin_link).metodo, "bootstrap")

    def test_copia_campos_de_registro_a_canonica(self):
        _registro(1, estado_rep="encontrado_vivo", foto_url="https://example.com/foto.jpg")

        call_command("bootstrap_canonicas", stdout=StringIO())

        persona = PersonaCanonica.objects.get()
        self.assertEqual(persona.estado_actual, "encontrado_vivo")
        self.assertEqual(persona.foto_principal, "https://example.com/foto.jpg")
