"""Tests end-to-end del pipeline de dedup."""
from django.test import TestCase

from dedup.pipeline import dedup_registro
from personas.models import ClusterLink, ParNegativo, PersonaCanonica, RegistroFuente


def _reg(n, fuente="dtv", **kwargs):
    r = RegistroFuente.objects.create(
        tipo="buscado", fuente=fuente, id_origen=f"{fuente}-{n}", **kwargs
    )
    return RegistroFuente.objects.get(id=r.id)


def _con_canonica(**kwargs):
    """Crea registro + PersonaCanonica + ClusterLink (estado post-bootstrap)."""
    r = _reg(**kwargs)
    p = PersonaCanonica.objects.create(
        nombre_display=r.nombre,
        zona=r.zona,
        estado_actual=r.estado_rep,
        n_fuentes=1,
    )
    ClusterLink.objects.create(
        registro=r, persona=p, score=1.0, metodo="bootstrap", confirmado=True
    )
    return r, p


class PipelineMergeTests(TestCase):
    def test_merge_por_cedula_igual(self):
        r1, _ = _con_canonica(n=1, cedula="V-12345678", nombre="Juan Pérez", zona="Caracas")
        r2, _ = _con_canonica(n=2, fuente="vtb", cedula="V-12345678", nombre="Juan Perez", zona="Caracas")

        self.assertEqual(PersonaCanonica.objects.count(), 2)

        merges = dedup_registro(r1)

        self.assertEqual(merges, 1)
        self.assertEqual(PersonaCanonica.objects.count(), 1)
        self.assertEqual(ClusterLink.objects.count(), 2)
        # Ambos links apuntan a la misma canónica
        persona_ids = set(ClusterLink.objects.values_list("persona_id", flat=True))
        self.assertEqual(len(persona_ids), 1)

    def test_n_fuentes_actualizado_tras_merge(self):
        r1, _ = _con_canonica(n=1, cedula="V-99999999", nombre="Ana Gómez", zona="Lara")
        r2, _ = _con_canonica(n=2, fuente="vtb", cedula="V-99999999", nombre="Ana Gomez", zona="Lara")

        dedup_registro(r1)

        persona = PersonaCanonica.objects.get()
        self.assertEqual(persona.n_fuentes, 2)

    def test_no_merge_bajo_umbral(self):
        r1, _ = _con_canonica(n=1, nombre="Carlos López", zona="Caracas")
        _, _ = _con_canonica(n=2, fuente="vtb", nombre="Luisa Martínez", zona="Mérida")

        merges = dedup_registro(r1)

        self.assertEqual(merges, 0)
        self.assertEqual(PersonaCanonica.objects.count(), 2)

    def test_respeta_par_negativo(self):
        r1, _ = _con_canonica(n=1, cedula="V-12345678", nombre="María Pérez", zona="Carabobo")
        r2, _ = _con_canonica(n=2, fuente="vtb", cedula="V-12345678", nombre="María Pérez", zona="Carabobo")
        ParNegativo.objects.create(registro_a=r1, registro_b=r2)

        merges = dedup_registro(r1)

        self.assertEqual(merges, 0)
        self.assertEqual(PersonaCanonica.objects.count(), 2)

    def test_registro_sin_link_no_falla(self):
        """Si el registro no tiene ClusterLink aún, el pipeline termina sin error."""
        r = _reg(n=1, cedula="V-12345678", nombre="Test", zona="Caracas")
        _con_canonica(n=2, fuente="vtb", cedula="V-12345678", nombre="Test", zona="Caracas")

        # r no tiene ClusterLink — no debe explotar
        merges = dedup_registro(r)
        self.assertEqual(merges, 0)

    def test_merge_multiple_candidatos(self):
        """Un registro puede mergear varios candidatos en una sola corrida."""
        r1, _ = _con_canonica(n=1, cedula="V-77777777", nombre="Pedro Salazar", zona="Aragua")
        _con_canonica(n=2, fuente="vtb", cedula="V-77777777", nombre="Pedro Salazar", zona="Aragua")
        _con_canonica(n=3, fuente="venapp", cedula="V-77777777", nombre="Pedro Salazar", zona="Aragua")

        self.assertEqual(PersonaCanonica.objects.count(), 3)

        dedup_registro(r1)

        self.assertEqual(PersonaCanonica.objects.count(), 1)
        self.assertEqual(ClusterLink.objects.count(), 3)
