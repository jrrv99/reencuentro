"""Merge de clusters — union-find sobre PersonaCanonica.

"Cluster" = conjunto de RegistroFuente que apuntan a la misma PersonaCanonica
vía ClusterLink. Fusionar dos clusters = reasignar todos los links del cluster
perdedor al ganador y borrar la PersonaCanonica perdedora.

Regla de desempate: el cluster con más n_fuentes es el ganador (más datos = mejor
representante). En caso de empate, gana el de menor UUID (determinista).

Invariante: raw data nunca se destruye. Solo se borran PersonaCanonica vacías.
"""
import logging

from django.db import transaction

from personas.models import ClusterLink, PersonaCanonica

logger = logging.getLogger(__name__)


def merge_clusters(
    persona_a_id,
    persona_b_id,
    score: float,
    metodo: str,
) -> None:
    """Fusiona el cluster de persona_b en el de persona_a (a = ganador).

    Post-condición: todos los ClusterLink que apuntaban a persona_b ahora
    apuntan a persona_a. PersonaCanonica persona_b es eliminada.
    n_fuentes de persona_a = conteo real de links.
    """
    if persona_a_id == persona_b_id:
        return

    with transaction.atomic():
        # Reasignar todos los links del perdedor al ganador.
        actualizados = ClusterLink.objects.filter(persona_id=persona_b_id).update(
            persona_id=persona_a_id,
            score=score,
            metodo=metodo,
        )
        # Actualizar n_fuentes del ganador con el conteo real post-merge.
        n = ClusterLink.objects.filter(persona_id=persona_a_id).count()
        PersonaCanonica.objects.filter(id=persona_a_id).update(n_fuentes=n)
        # Eliminar la canónica vacía (todos sus links ya se reasignaron).
        PersonaCanonica.objects.filter(id=persona_b_id).delete()

        logger.debug(
            "merge: %s ← %s (score=%.2f, metodo=%s, links_movidos=%d)",
            persona_a_id, persona_b_id, score, metodo, actualizados,
        )


def elegir_ganador(persona_a: PersonaCanonica, persona_b: PersonaCanonica):
    """Devuelve (ganador_id, perdedor_id). Gana el cluster con más fuentes."""
    if persona_a.n_fuentes > persona_b.n_fuentes:
        return persona_a.id, persona_b.id
    if persona_b.n_fuentes > persona_a.n_fuentes:
        return persona_b.id, persona_a.id
    # Empate: desempate determinista por UUID (menor gana)
    return (persona_a.id, persona_b.id) if persona_a.id < persona_b.id else (persona_b.id, persona_a.id)
