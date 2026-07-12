"""Pipeline de deduplicación: bloqueo → scoring → merge.

Entrada: un RegistroFuente (recién insertado/actualizado).
Salida: side-effect — los clusters en personas_canonicas se fusionan si corresponde.

El registro debe ya tener un ClusterLink (post-bootstrap_canonicas). Si no lo
tiene aún, el pipeline lo omite silenciosamente (se puede reintentar después).
"""
import logging

from personas.models import ClusterLink, PersonaCanonica

from .blocking import candidatos
from .merger import elegir_ganador, merge_clusters
from .scoring import UMBRAL_MERGE, score_par

logger = logging.getLogger(__name__)


def dedup_registro(registro) -> int:
    """Corre el pipeline completo para un registro.

    Retorna el número de merges realizados.
    """
    lista = candidatos(registro)
    if not lista:
        return 0

    merges = 0
    for candidato in lista:
        score, metodo = score_par(registro, candidato)
        if score < UMBRAL_MERGE:
            continue

        # Re-fetch links en cada iteración: un merge previo puede haber cambiado
        # la persona_id del registro principal.
        try:
            link_reg = ClusterLink.objects.select_related("persona").get(
                registro_id=registro.id
            )
            link_cand = ClusterLink.objects.select_related("persona").get(
                registro_id=candidato.id
            )
        except ClusterLink.DoesNotExist:
            continue

        if link_reg.persona_id == link_cand.persona_id:
            continue  # ya en el mismo cluster

        ganador_id, perdedor_id = elegir_ganador(link_reg.persona, link_cand.persona)
        merge_clusters(ganador_id, perdedor_id, score, metodo)
        merges += 1

        logger.info(
            "merge: registro=%s + candidato=%s → persona=%s (score=%.2f, metodo=%s)",
            registro.id, candidato.id, ganador_id, score, metodo,
        )

    return merges
