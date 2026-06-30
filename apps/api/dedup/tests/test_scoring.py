"""Tests del scoring — verifica la matriz cédula × cara (columna sin foto)."""
from django.test import TestCase

from dedup.scoring import UMBRAL_MERGE, UMBRAL_REVISION, score_par
from personas.models import RegistroFuente


def _reg(n, fuente="dtv", **kwargs):
    r = RegistroFuente.objects.create(
        tipo="buscado", fuente=fuente, id_origen=f"{fuente}-{n}", **kwargs
    )
    return RegistroFuente.objects.get(id=r.id)


class MatrizCedulaSinFotoTests(TestCase):
    """Columna 'sin foto' de la matriz §5 del plan maestro."""

    def test_cedula_igual_merge_inmediato(self):
        a = _reg(1, cedula="V-12345678", nombre="Juan Pérez", zona="Caracas")
        b = _reg(2, fuente="vtb", cedula="V-12345678", nombre="Juan Perez", zona="Caracas")
        score, metodo = score_par(a, b)
        self.assertEqual(score, 1.0)
        self.assertEqual(metodo, "cedula")

    def test_cedula_aproximada_zona_revision(self):
        # lev=1 entre cedula_norms ('12345678' vs '12345679') → revisión, no merge
        a = _reg(1, cedula="V-12345678", nombre="Juan Pérez", zona="Carabobo")
        b = _reg(2, fuente="vtb", cedula="V-12345679", nombre="Juan Pérez", zona="Carabobo")
        score, metodo = score_par(a, b)
        self.assertGreaterEqual(score, UMBRAL_REVISION)
        self.assertLess(score, UMBRAL_MERGE)
        self.assertEqual(metodo, "fuzzy")

    def test_cedula_distinta_penaliza(self):
        # cédulas distintas + nombre idéntico → score penalizado
        a = _reg(1, cedula="V-11111111", nombre="Juan Pérez", zona="Caracas")
        b = _reg(2, fuente="vtb", cedula="V-99999999", nombre="Juan Pérez", zona="Caracas")
        score_distinta, _ = score_par(a, b)

        # El mismo par SIN cédula daría un score mayor
        a2 = _reg(3, nombre="Juan Pérez", zona="Caracas")
        b2 = _reg(4, fuente="vtb", nombre="Juan Pérez", zona="Caracas")
        score_sin_cedula, _ = score_par(a2, b2)

        self.assertLess(score_distinta, score_sin_cedula)


class ScoreBaseTests(TestCase):
    """Score base (sin cédula): nombre + edad + zona."""

    def test_nombre_igual_zona_igual_alto(self):
        a = _reg(1, nombre="María García", zona="Carabobo")
        b = _reg(2, fuente="vtb", nombre="María García", zona="Carabobo")
        score, _ = score_par(a, b)
        self.assertGreaterEqual(score, 0.7)

    def test_edad_dentro_rango_suma(self):
        a = _reg(1, nombre="Ana López", zona="Caracas", edad=30)
        b = _reg(2, fuente="vtb", nombre="Ana López", zona="Caracas", edad=32)
        score_con_edad, _ = score_par(a, b)

        a2 = _reg(3, nombre="Ana López", zona="Caracas", edad=30)
        b2 = _reg(4, fuente="vtb", nombre="Ana López", zona="Caracas", edad=50)
        score_sin_rango, _ = score_par(a2, b2)

        self.assertGreater(score_con_edad, score_sin_rango)

    def test_personas_distintas_score_bajo(self):
        a = _reg(1, nombre="Pedro Hernández", zona="Caracas")
        b = _reg(2, fuente="vtb", nombre="Luisa Martínez", zona="Mérida")
        score, _ = score_par(a, b)
        self.assertLess(score, UMBRAL_REVISION)
