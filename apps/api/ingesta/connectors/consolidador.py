"""Conector para el consolidador (aevscraping).

Lee datos_consolidados/todos_registros.json (o un delta) y hace UPSERT idempotente
a registros_fuente sobre la clave (fuente, id_origen).

Idempotencia: computa content_hash del registro crudo (sha256, excluyendo
fecha_actualizacion). Si el hash almacenado coincide → sin_cambio, no escribe.
Si difiere → actualizado. Si no existe → insertado.

INVARIANTE del hash: el hash se calcula SIEMPRE sobre el registro tal como llega del
JSON, ANTES de cualquier limpieza (centinelas, parse de blob). Si mañana se mejora
la normalización, el hash no cambia → no se producen "actualizados" falsos.

Privacidad: los campos PRIVADOS (teléfonos, quién encuentra, etc.) van SOLO a
`contacto` como JSON. Nunca al serializer público.
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import transaction

from personas.models import RegistroFuente

logger = logging.getLogger(__name__)


class IngestaParseError(Exception):
    """JSON mal formado o no parseable. Aborta la corrida completa."""


# ---------------------------------------------------------------------------
# Centinelas de cédula (configurable: pasar `centinelas=` a normalizar_centinela)
# ---------------------------------------------------------------------------

#: Set de valores que significan "sin cédula" en la fuente de origen.
#: Comparación case-insensitive + trim. Ampliar aquí al encontrar nuevos patrones.
CENTINELAS_CEDULA: frozenset[str] = frozenset({
    "no registrado",
    "no especificado",
    "n/a",
    "na",
    "desconocido",
    "sin cedula",
    "sin cédula",
    "ninguno",
    "",
})


def normalizar_centinela(
    valor: str | None,
    centinelas: frozenset[str] = CENTINELAS_CEDULA,
) -> str | None:
    """None si valor es un centinela (case-insensitive, strip); original si es real.

    El raw_payload conserva el valor original — esta función solo afecta el campo
    almacenado, no el input del content_hash.
    """
    if valor is None:
        return None
    if valor.strip().lower() in centinelas:
        return None
    return valor


# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------

# Campos excluidos del hash (cambian entre corridas sin que el registro haya cambiado).
_HASH_EXCLUDE = frozenset({"fecha_actualizacion", "content_hash"})

# Campos PRIVADOS que van solo a contacto, nunca al serializer público.
_CAMPOS_PRIVADOS = frozenset({
    "telefono_contacto",
    "encontrado_por",
    "encontrado_por_cedula",
    "telefono_quien_encuentra",
    "nombre_de_quien_lo_busca",
})

# Mapeo de estado del consolidador → estado_rep del plan §4.
_ESTADO_MAP: dict[str, str] = {
    "desaparecido": "sin_contacto",
    "sin contacto": "sin_contacto",
    "sin_contacto": "sin_contacto",
    "encontrado": "encontrado_vivo",
    "encontrado vivo": "encontrado_vivo",
    "encontrado_vivo": "encontrado_vivo",
    "hospitalizado": "hospitalizado",
    "refugiado": "refugiado",
    "fallecido": "fallecido",
}

# Regexp para detectar el marcador de rescate en ultima_ubicacion.
# Parseo best-effort: captura el patrón más frecuente observado.
# El caso general (blobs sin marcador, narrativa mezclada) lo resuelve el hook Ollama.
_RESCATE_RE = re.compile(r"datos\s+cr[íi]ticos", re.IGNORECASE)

# Para la decisión "tiene cédula?": misma lógica que la columna generada cedula_norm.
_SOLO_DIGITOS_RE = re.compile(r"\D")


# ---------------------------------------------------------------------------
# Dataclass de stats
# ---------------------------------------------------------------------------


@dataclass
class RunStats:
    leidos: int = 0
    insertados: int = 0
    actualizados: int = 0
    sin_cambio: int = 0
    omitidos: int = 0
    errores: int = 0


# ---------------------------------------------------------------------------
# Funciones públicas de utilidad (también usadas en tests)
# ---------------------------------------------------------------------------


def compute_content_hash(record: dict[str, Any]) -> str:
    """sha256 del registro crudo excluyendo fecha_actualizacion.

    Nota: el JSON del consolidador actualmente NO incluye content_hash por
    registro. Si en el futuro lo incluye, el if-guard lo reutilizaría.
    El fallback usa json.dumps con sort_keys para determinismo; NO coincide
    con el separador \x1f que usa aevscraping — queda documentado como hilo
    abierto a cerrar cuando se comparta consolidator/lib/registros.py.
    """
    if "content_hash" in record and record["content_hash"]:
        return record["content_hash"]
    filtered = {k: v for k, v in record.items() if k not in _HASH_EXCLUDE}
    canonical = json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Funciones privadas de mapeo
# ---------------------------------------------------------------------------


def _strip_nul(value: Any) -> Any:
    """Postgres TEXT/JSONB rechaza bytes NUL (\x00). Los elimina recursivamente."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


def _map_estado(raw: str | None) -> str:
    if not raw:
        return "sin_contacto"
    return _ESTADO_MAP.get(raw.strip().lower(), raw.strip().lower())


def _derive_tipo(estado_rep: str) -> str:
    if estado_rep in ("encontrado_vivo", "hospitalizado", "refugiado", "fallecido"):
        return "encontrado"
    return "buscado"


def _parse_ultima_ubicacion(texto: str | None) -> tuple[str | None, str | None]:
    """Separa la ubicación real de la narrativa de rescate (best-effort).

    Cuando el regex NO matchea: conserva ultima_ubicacion intacta como ubicacion
    (con posible ruido). El hook Ollama limpiará los blobs complejos.

    Retorna (ubicacion, descripcion_extra).
    """
    if not texto:
        return None, None
    m = _RESCATE_RE.search(texto)
    if m:
        ubicacion = texto[: m.start()].strip() or None
        descripcion_extra = texto[m.start() :].strip()
        return ubicacion, descripcion_extra
    # Sin marcador: toda la cadena va a ubicacion, sin truncar nada.
    return texto.strip() or None, None


def _build_contacto(record: dict[str, Any]) -> str | None:
    """Extrae los campos PRIVADOS en un JSON blob para el campo contacto."""
    privados = {k: v for k, v in record.items() if k in _CAMPOS_PRIVADOS and v}
    return json.dumps(privados, ensure_ascii=False) if privados else None


def _map_record(record: dict[str, Any]) -> dict[str, Any]:
    """Transforma un registro crudo del consolidador en campos de RegistroFuente.

    IMPORTANTE: no modifica el dict `record`. El raw_payload almacena el registro
    original tal cual, y el content_hash (calculado antes de llamar a esta función)
    sigue siendo el del crudo.
    """
    estado_rep = _map_estado(record.get("estado"))
    tipo = _derive_tipo(estado_rep)
    ubicacion, descripcion_extra = _parse_ultima_ubicacion(record.get("ultima_ubicacion"))

    descripcion_parts = [
        p
        for p in (record.get("observaciones"), descripcion_extra)
        if p and p.strip()
    ]
    descripcion = "\n\n".join(descripcion_parts) or None

    # TODO (Tier-C / Ollama): si descripcion contiene blobs muy sucios o
    # ultima_ubicacion mezclaba narrativa compleja, llamar aquí al extractor LLM
    # con confianza reducida. Por ahora se deja como punto de extensión.

    # Normalización de cédula: centinelas → None. El crudo queda en raw_payload.
    cedula_cruda = record.get("cedula")
    cedula_limpia = normalizar_centinela(cedula_cruda)

    # INVARIANTE: "tiene cédula?" se evalúa SIEMPRE sobre cedula_norm_local
    # (dígitos no vacíos), NUNCA sobre el campo crudo.
    # "No registrado" es truthy → rompería la decisión si se usara como bool.
    # La DB genera cedula_norm con la misma lógica; aquí lo replicamos para
    # tomar decisiones en el conector sin depender de un campo generado.
    cedula_norm_local = _SOLO_DIGITOS_RE.sub("", cedula_limpia or "")
    tiene_cedula = bool(cedula_norm_local)

    # TODO (Hito 2 / CNE §5 del plan de migración): si tiene_cedula, consultar
    # ve-cedula-service (VE_CEDULA_SERVICE_BASE_URL / _TOKEN, endpoint
    # /v1/cedula/{nac}/{num}) para validar y actualizar cedula_estado en
    # personas_canonicas. Solo si hay dígitos reales — nunca con centinelas.
    # if tiene_cedula:
    #     validar_cedula_cne(cedula_norm_local, record.get("nombre"))

    # TODO (es_menor, plan §8 / Hito 2): si record.get("es_menor") is True,
    # aplicar restricciones de privacidad reforzadas: no exponer edad exacta,
    # restringir actualizaciones de estado "encontrado" a respondedores verificados,
    # y elevar el umbral de confianza requerido para cualquier merge.
    # El campo queda preservado en raw_payload para consumo posterior.
    _ = tiene_cedula  # evita F841 hasta que se implemente el TODO del CNE

    fields: dict[str, Any] = {
        "fuente": record.get("fuente", ""),
        "id_origen": str(record.get("id", "")),
        "tipo": tipo,
        "nombre": record.get("nombre"),
        "cedula": cedula_limpia,  # None si era centinela; original si era real
        "edad": record.get("edad"),  # nunca castear a 0; None significa desconocida
        "sexo": record.get("sexo"),
        "zona": record.get("zona"),
        "ubicacion": ubicacion,
        "descripcion": descripcion,
        "foto_url": record.get("foto_url"),
        "url_origen": record.get("url_origen"),
        "estado_rep": estado_rep,
        "tipo_fuente": "familiar",
        "confianza": float(record.get("confianza", 1.0)),
        "raw_payload": record,   # original sin modificar: preserva cedula cruda, es_menor, etc.
        "contacto": _build_contacto(record),
    }
    # NUL bytes en TEXT/JSONB abortan el INSERT. Se limpian aquí, después del hash
    # (el hash se calculó sobre el crudo original, el invariante se preserva).
    return _strip_nul(fields)


# ---------------------------------------------------------------------------
# Funciones principales
# ---------------------------------------------------------------------------


def ingest_file(
    archivo: str | Path,
    fuente_filtro: str | None = None,
    on_progress=None,
    progress_interval: int = 1000,
) -> RunStats:
    """Lee un JSON del consolidador y hace UPSERT idempotente a registros_fuente.

    Args:
        archivo: Ruta al JSON (array de registros).
        fuente_filtro: Si se pasa, solo procesa registros de esa fuente.
        on_progress: Callable(stats, total) invocado cada progress_interval registros.
        progress_interval: Cada cuántos registros llamar on_progress.

    Returns:
        RunStats con los contadores de la corrida.

    Raises:
        IngestaParseError: Si el archivo no es JSON válido. Aborta antes de
            escribir nada — nunca ingesta parcial.
    """
    stats = RunStats()
    path = Path(archivo)

    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise IngestaParseError(
            f"JSON inválido en '{path}': "
            f"línea {exc.lineno}, columna {exc.colno} — {exc.msg}"
        ) from exc

    if not isinstance(raw, list):
        raise IngestaParseError(
            f"JSON inválido en '{path}': se esperaba un array de registros, "
            f"se obtuvo {type(raw).__name__}"
        )
    records: list[dict[str, Any]] = raw

    if fuente_filtro:
        records = [r for r in records if r.get("fuente") == fuente_filtro]

    total = len(records)
    for record in records:
        stats.leidos += 1
        try:
            _process_record(record, stats)
        except Exception:
            logger.exception(
                "Error procesando registro id=%s fuente=%s",
                record.get("id"),
                record.get("fuente"),
            )
            stats.errores += 1
        if on_progress and stats.leidos % progress_interval == 0:
            on_progress(stats, total)

    return stats


@transaction.atomic
def _process_record(record: dict[str, Any], stats: RunStats) -> None:
    fuente = record.get("fuente", "")
    id_origen = str(record.get("id", ""))

    if not fuente or not id_origen:
        stats.omitidos += 1
        return

    # Hash calculado sobre el crudo, ANTES de cualquier limpieza (invariante).
    new_hash = compute_content_hash(record)

    existing = RegistroFuente.objects.filter(
        fuente=fuente, id_origen=id_origen
    ).first()

    if existing is not None:
        # Si el registro fue creado fuera de ingesta (sin hash), lo tratamos como
        # "actualizar y sellar": el contador queda inflado una vez, pero el hash
        # queda seteado y las corridas posteriores funcionan correctamente.
        if existing.content_hash is not None and existing.content_hash == new_hash:
            stats.sin_cambio += 1
            return
        fields = _map_record(record)
        fields["content_hash"] = new_hash
        for attr, val in fields.items():
            setattr(existing, attr, val)
        existing.save()
        stats.actualizados += 1
    else:
        fields = _map_record(record)
        fields["content_hash"] = new_hash
        RegistroFuente.objects.create(**fields)
        stats.insertados += 1
