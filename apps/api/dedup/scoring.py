"""Scoring por par — matriz cédula × cara del plan §5.

En Fase 0 (sin cara, Hito 4 pendiente) solo se usa la columna "sin foto" de la
matriz. Cuando se integre InsightFace (Hito 4), se añade el término cara aquí.

Score base (sin cédula):
    score = 0.5·sim_nombre + 0.2·sim_edad + 0.2·sim_zona + 0.1·sim_cara
    En Fase 0 sim_cara = 0 (conservador; la cara eleva el score, no lo baja).

Umbrales:
    ≥ UMBRAL_MERGE   → merge automático
    ≥ UMBRAL_REVISION → cola de revisión (futuro)
    < UMBRAL_REVISION → personas distintas
"""
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from personas.choices import MetodoCluster
from personas.models import RegistroFuente

UMBRAL_MERGE = 0.85
UMBRAL_REVISION = 0.60


def score_par(a: RegistroFuente, b: RegistroFuente) -> tuple[float, str]:
    """Devuelve (score 0-1, metodo). Implementa la matriz §5, columna sin-foto.

    Retorna:
        (1.0, 'cedula')  — cédula igual, fusión inmediata
        (score, 'fuzzy') — resto de casos
    """
    # Matriz §5 — columna "sin foto":
    if a.cedula_norm and b.cedula_norm:
        lev = Levenshtein.distance(a.cedula_norm, b.cedula_norm)

        if lev == 0:
            # igual + sin foto → fusión
            return 1.0, MetodoCluster.CEDULA

        if lev <= 2:
            # ≈igual + sin foto → revisión (no merge automático)
            base = _score_base(a, b)
            return max(base, UMBRAL_REVISION), MetodoCluster.FUZZY

        # distinta + sin foto → fuzzy normal, penalizado
        return _score_base(a, b) * 0.8, MetodoCluster.FUZZY

    # Sin cédula en alguno → fuzzy puro de nombre/edad/zona
    return _score_base(a, b), MetodoCluster.FUZZY


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _score_base(a: RegistroFuente, b: RegistroFuente) -> float:
    """Base: 0.5·nombre + 0.2·edad + 0.2·zona. sim_cara = 0 hasta Hito 4."""
    sim_nombre = fuzz.token_sort_ratio(
        a.nombre_norm or "", b.nombre_norm or ""
    ) / 100.0

    sim_edad = _sim_edad(a.edad, b.edad)
    sim_zona = _sim_zona(a.zona, b.zona)

    return 0.5 * sim_nombre + 0.2 * sim_edad + 0.2 * sim_zona
    # + 0.1 * sim_cara  ← Hito 4: descomentar cuando InsightFace esté integrado


def _sim_edad(edad_a: int | None, edad_b: int | None) -> float:
    if edad_a is None or edad_b is None:
        return 0.5  # neutral si falta
    return 1.0 if abs(edad_a - edad_b) <= 3 else 0.0


def _sim_zona(zona_a: str | None, zona_b: str | None) -> float:
    if not zona_a or not zona_b:
        return 0.0
    return 1.0 if zona_a.strip().lower() == zona_b.strip().lower() else 0.0
