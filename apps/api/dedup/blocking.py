"""Bloqueo: dado un registro, devuelve candidatos a ser la misma persona.

Evita O(n²) limitando las comparaciones a registros que comparten algún
atributo fuerte: zona, cédula exacta, o nombre con similitud trigram > 0.5.

El shortlist resultante va al módulo de scoring (nunca toda la tabla).
Respeta PareNegativo: registros ya juzgados como distintos no vuelven a aparecer.
"""
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q

from personas.models import ParNegativo, RegistroFuente

UMBRAL_TRGM_NOMBRE = 0.5
MAX_CANDIDATOS_ZONA_CEDULA = 500
MAX_CANDIDATOS_NOMBRE = 300


def candidatos(registro: RegistroFuente) -> list[RegistroFuente]:
    """Devuelve la lista de candidatos a comparar contra `registro`.

    Criterios OR:
      - misma zona
      - mismo cedula_norm exacto (el duplicado típico entre fuentes)
      - similitud trigram de nombre_norm ≥ 0.5

    Excluye: el propio registro y todos sus pares_negativos conocidos.
    """
    excluir = _ids_excluidos(registro)

    ids_zona_cedula = _bloqueo_zona_cedula(registro, excluir)
    ids_nombre = _bloqueo_nombre(registro, excluir)

    todos_ids = ids_zona_cedula | ids_nombre
    if not todos_ids:
        return []

    return list(RegistroFuente.objects.filter(id__in=todos_ids))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _ids_excluidos(registro: RegistroFuente) -> set:
    negativos_b = set(
        ParNegativo.objects.filter(registro_a_id=registro.id)
        .values_list("registro_b_id", flat=True)
    )
    negativos_a = set(
        ParNegativo.objects.filter(registro_b_id=registro.id)
        .values_list("registro_a_id", flat=True)
    )
    return {registro.id} | negativos_b | negativos_a


def _bloqueo_zona_cedula(registro: RegistroFuente, excluir: set) -> set:
    q = Q()
    if registro.zona:
        q |= Q(zona=registro.zona)
    if registro.cedula_norm:
        q |= Q(cedula_norm=registro.cedula_norm)
    if not q:
        return set()
    return set(
        RegistroFuente.objects.filter(q)
        .exclude(id__in=excluir)
        .values_list("id", flat=True)[:MAX_CANDIDATOS_ZONA_CEDULA]
    )


def _bloqueo_nombre(registro: RegistroFuente, excluir: set) -> set:
    if not registro.nombre_norm:
        return set()
    return set(
        RegistroFuente.objects.annotate(
            sim_nombre=TrigramSimilarity("nombre_norm", registro.nombre_norm)
        )
        .filter(sim_nombre__gte=UMBRAL_TRGM_NOMBRE)
        .exclude(id__in=excluir)
        .values_list("id", flat=True)[:MAX_CANDIDATOS_NOMBRE]
    )
