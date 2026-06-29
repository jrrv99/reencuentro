"""Conector para el consolidador (aevscraping).

Lee datos_consolidados/todos_registros.json (o un delta) y hace UPSERT idempotente
a registros_fuente sobre la clave (fuente, id_origen).

Idempotencia: computa content_hash del registro crudo (sha256, excluyendo
fecha_actualizacion). Si el hash almacenado coincide → sin_cambio, no escribe.
Si difiere → actualizado. Si no existe → insertado.

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
_RESCATE_RE = re.compile(r"datos\s+cr[íi]ticos", re.IGNORECASE)


@dataclass
class RunStats:
    leidos: int = 0
    insertados: int = 0
    actualizados: int = 0
    sin_cambio: int = 0
    omitidos: int = 0
    errores: int = 0


def compute_content_hash(record: dict[str, Any]) -> str:
    """sha256 del registro crudo excluyendo fecha_actualizacion.

    Si el JSON del consolidador ya incluye un campo content_hash pre-calculado,
    ese valor tiene prioridad (misma definición de columnas que usa aevscraping).
    """
    if "content_hash" in record and record["content_hash"]:
        return record["content_hash"]
    filtered = {k: v for k, v in record.items() if k not in _HASH_EXCLUDE}
    canonical = json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _map_estado(raw: str | None) -> str:
    if not raw:
        return "sin_contacto"
    return _ESTADO_MAP.get(raw.strip().lower(), raw.strip().lower())


def _derive_tipo(estado_rep: str) -> str:
    if estado_rep in ("encontrado_vivo", "hospitalizado", "refugiado", "fallecido"):
        return "encontrado"
    return "buscado"


def _parse_ultima_ubicacion(texto: str | None) -> tuple[str | None, str | None]:
    """Separa la ubicación real de la narrativa de rescate.

    Retorna (ubicacion, descripcion_extra).
    El blob "DATOS CRÍTICOS PARA RESCATE ..." y cualquier narrativa que lo
    preceda (pero no forme parte de la ubicación) se manda a descripcion.
    """
    if not texto:
        return None, None
    m = _RESCATE_RE.search(texto)
    if m:
        ubicacion = texto[: m.start()].strip() or None
        descripcion_extra = texto[m.start() :].strip()
        return ubicacion, descripcion_extra
    return texto.strip() or None, None


def _build_contacto(record: dict[str, Any]) -> str | None:
    """Extrae los campos PRIVADOS en un JSON blob para el campo contacto."""
    privados = {k: v for k, v in record.items() if k in _CAMPOS_PRIVADOS and v}
    return json.dumps(privados, ensure_ascii=False) if privados else None


def _map_record(record: dict[str, Any]) -> dict[str, Any]:
    """Transforma un registro crudo del consolidador en campos de RegistroFuente."""
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

    return {
        "fuente": record.get("fuente", ""),
        "id_origen": str(record.get("id", "")),
        "tipo": tipo,
        "nombre": record.get("nombre"),
        "cedula": record.get("cedula"),
        "edad": record.get("edad"),
        "sexo": record.get("sexo"),
        "zona": record.get("zona"),
        "ubicacion": ubicacion,
        "descripcion": descripcion,
        "foto_url": record.get("foto_url"),
        "url_origen": record.get("url_origen"),
        "estado_rep": estado_rep,
        "tipo_fuente": "familiar",
        "confianza": float(record.get("confianza", 1.0)),
        "raw_payload": record,
        "contacto": _build_contacto(record),
    }


def ingest_file(archivo: str | Path, fuente_filtro: str | None = None) -> RunStats:
    """Lee un JSON del consolidador y hace UPSERT idempotente a registros_fuente.

    Args:
        archivo: Ruta al JSON (array de registros).
        fuente_filtro: Si se pasa, solo procesa registros de esa fuente.

    Returns:
        RunStats con los contadores de la corrida.
    """
    stats = RunStats()
    path = Path(archivo)

    with path.open(encoding="utf-8") as f:
        records: list[dict[str, Any]] = json.load(f)

    if fuente_filtro:
        records = [r for r in records if r.get("fuente") == fuente_filtro]

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

    return stats


@transaction.atomic
def _process_record(record: dict[str, Any], stats: RunStats) -> None:
    fuente = record.get("fuente", "")
    id_origen = str(record.get("id", ""))

    if not fuente or not id_origen:
        stats.omitidos += 1
        return

    new_hash = compute_content_hash(record)

    existing = RegistroFuente.objects.filter(
        fuente=fuente, id_origen=id_origen
    ).first()

    if existing is not None:
        if existing.content_hash == new_hash:
            stats.sin_cambio += 1
            return
        # Actualizar campos que pueden haber cambiado.
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
