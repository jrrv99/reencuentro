"""Tests del módulo de bloqueo."""
from django.test import TestCase

from dedup.blocking import candidatos
from personas.models import ClusterLink, ParNegativo, PersonaCanonica, RegistroFuente


def _reg(n, fuente="dtv", **kwargs):
    r = RegistroFuente.objects.create(
        tipo="buscado", fuente=fuente, id_origen=f"{fuente}-{n}", **kwargs
    )
    return RegistroFuente.objects.get(id=r.id)  # refresca columnas generadas


class BloqueoZonaTests(TestCase):
    def test_misma_zona_es_candidato(self):
        r1 = _reg(1, zona="Caracas", nombre="Ana López")
        r2 = _reg(2, zona="Caracas", nombre="Pedro Gómez")
        _reg(3, zona="Valencia", nombre="Otro Nombre")

        ids = {c.id for c in candidatos(r1)}
        self.assertIn(r2.id, ids)

    def test_zona_distinta_no_es_candidato_sin_otra_señal(self):
        r1 = _reg(1, zona="Caracas")
        r2 = _reg(2, zona="Maracaibo")

        ids = {c.id for c in candidatos(r1)}
        self.assertNotIn(r2.id, ids)


class BloqueoNombreTests(TestCase):
    def test_nombre_similar_es_candidato(self):
        r1 = _reg(1, nombre="María del Carmen Pérez")
        r2 = _reg(2, fuente="vtb", nombre="Maria Carmen Perez")

        ids = {c.id for c in candidatos(r1)}
        self.assertIn(r2.id, ids)

    def test_nombre_diferente_no_es_candidato_sin_otra_señal(self):
        r1 = _reg(1, nombre="María Pérez", zona=None)
        r2 = _reg(2, nombre="Carlos Rodríguez", zona=None)

        ids = {c.id for c in candidatos(r1)}
        self.assertNotIn(r2.id, ids)


class BloqueoExclusionTests(TestCase):
    def test_excluye_propio_registro(self):
        r1 = _reg(1, zona="Caracas")
        ids = {c.id for c in candidatos(r1)}
        self.assertNotIn(r1.id, ids)

    def test_excluye_pares_negativos_registro_a(self):
        r1 = _reg(1, zona="Caracas")
        r2 = _reg(2, zona="Caracas")
        ParNegativo.objects.create(registro_a=r1, registro_b=r2)

        ids = {c.id for c in candidatos(r1)}
        self.assertNotIn(r2.id, ids)

    def test_excluye_pares_negativos_registro_b(self):
        r1 = _reg(1, zona="Caracas")
        r2 = _reg(2, zona="Caracas")
        ParNegativo.objects.create(registro_a=r2, registro_b=r1)

        ids = {c.id for c in candidatos(r1)}
        self.assertNotIn(r2.id, ids)

    def test_sin_zona_ni_nombre_devuelve_vacio(self):
        r1 = _reg(1, zona=None, nombre=None)
        _reg(2, zona=None, nombre=None)

        self.assertEqual(candidatos(r1), [])
