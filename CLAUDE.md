# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Fase 0 — en curso.** Hitos completados:
- Esqueleto del monorepo (`apps/api/` Django + `config/` + 5 apps registradas)
- `infra/` compose completo: Postgres+pgvector, Redis, **y el servicio `api` Django**
- App `personas`: modelos del plan §3 (con `nombre_norm`/`cedula_norm` generados, índices GIN-trigram, HNSW, partial-unique), migraciones 0001–0003 (extensiones, esquema, reconciliación de cédula)
- App `ingesta`: conector idempotente del consolidador (upsert sobre `(fuente, id_origen)`, `content_hash`, centinelas de cédula, parseo no-silencioso, `SyncRun`)
- **56k registros reales cargados en local** vía `ingesta_consolidador`
- `GET /api/v1/personas/` funcional (buscador público, privacy-filtered, `PersonaCanonicaViewSet`)

**En construcción ahora:** ViewSet APIs completas — `RegistroFuenteViewSet` + refactor a `HyperlinkedModelSerializer` con expansión inline en detalle (plan §9).

**Pendiente:** motor de dedup (Hito 2b), stack de caras (`identidad`), instituciones/responders, frontend Next.js.

**El plan es la fuente de verdad** — leerlo antes de construir. `plans/plan_migracion_datos.md` para arquitectura de datos/APIs; `plans/plan_maestro_desaparecidos.md` para el diseño completo del sistema.

---

## What this is

`reencuentro` es un **agregador con resolución de identidades** para desaparecidos tras el terremoto Venezuela 2026. No es otro registro — ingiere de los registros existentes, deduplica entre ellos y expone **una sola búsqueda** que muestra a cada persona una vez y enlaza de vuelta a cada origen. Unifica las plataformas existentes y les manda tráfico.

---

## Stack

| Concern | Tech |
|---|---|
| Core API + dedup + admin | Django / DRF (`drf-spectacular`, `django-filter`, `simplejwt`) |
| Ingest & matching jobs | Celery + Celery Beat |
| Canonical store + text fuzzy | PostgreSQL (`pg_trgm`, `unaccent`) |
| Face search | **pgvector**, embeddings 512-D, HNSW + cosine (`<=>`) |
| Cache + broker | Redis |
| Connector/webhook orchestration | n8n |
| Free-text extraction from social posts | Ollama (LLM local) |
| Public search (read-heavy) | Next.js en Vercel/Cloudflare |
| Edge / cache / rate-limit | Cloudflare |
| Face stack | InsightFace (`buffalo_l`, ArcFace, ONNX); `imagehash` pHash; `rapidfuzz` |

---

## Repo layout

```
reencuentro/
├── apps/
│   ├── api/               # Django/DRF + Celery
│   │   ├── config/        # settings, celery, urls
│   │   ├── personas/      # registros_fuente, personas_canonicas, cluster_links, claims, negativos
│   │   ├── ingesta/       # conectores Tier A/B/C (Celery tasks) + SyncRun
│   │   ├── dedup/         # scoring + blocking + union-find  [pendiente]
│   │   ├── identidad/     # caras (insightface+pgvector), phash  [pendiente]
│   │   └── instituciones/ # workspaces, responders, auditoría  [pendiente]
│   └── web/               # Next.js  [pendiente]
├── infra/                 # docker-compose (db + redis + api), .env templates
└── plans/                 # plan maestro + plan de migración
```

---

## Core architecture

**Raw data is never destroyed.** Three-layer identity resolution:
- `registros_fuente` — crudo, 1 fila por reporte por fuente. Canónico e inmutable.
- `personas_canonicas` — la entidad resuelta. Es una *vista* construida por clustering. Si el dedup se equivoca, se re-clusteriza sin perder nada.
- `cluster_links` — qué registros crudos son la misma persona (`score`, `metodo`, `confirmado`). `pares_negativos` = "ya se juzgó que NO son la misma".

**Motor de dedup único** (`dedup/`), compartido por los 3 sistemas. En cada insert/cambio (vía Celery): normalizar → bloqueo → scoring por par → umbrales → union-find respetando `pares_negativos`. **Cédula match = 1.0 auto-merge. Sin cédula, NUNCA auto-merge** — la cara surfacea candidatos, no decide.

**Estados como claims versionados, atribuidos y reversibles** (`estado_claims`). `personas_canonicas.estado_actual` = el claim `vigente` más confiable. Rollback por cuenta = marcar `vigente=false` en todos los claims de un `autor_id`.

**Multi-tenant para acceso, mono-tenant para la data.** `institucion_id` gobierna solo membresía/permisos. El índice de personas es global — un doctor debe matchear contra reportes de todo el país.

---

## API design conventions (plan §9)

### ViewSets
`ReadOnlyModelViewSet` para recursos públicos. El ViewSet elige el serializer según la acción:

```python
def get_serializer_class(self):
    if self.action == "retrieve":
        return MiRecursoDetailSerializer
    return MiRecursoSerializer
```

### Serializers — patrón lista / detalle
Base `HyperlinkedModelSerializer`. En lista las relaciones son `HyperlinkedRelatedField` (URLs). En detalle `to_representation` las expande inline con el serializer del recurso relacionado:

```python
class PersonaCanonicaDetailSerializer(PersonaCanonicaSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        registros_qs = instance.cluster_links.select_related("registro")
        data["registros"] = RegistroFuenteSerializer(
            [cl.registro for cl in registros_qs],
            many=True, context=self.context,
        ).data
        return data
```

### Privacidad — allow-list estricta
`contacto`, `face_embedding`, `raw_payload`, `cedula` cruda y datos de responder **nunca aparecen en serializers públicos**. La allow-list está en `fields = [...]` del Meta. Si el campo no está en `fields`, no existe en el output — nunca se filtra con `if`.

```python
PUBLIC_REGISTRO_FIELDS = [
    "url", "fuente", "url_origen", "tipo", "nombre",
    "edad", "sexo", "zona", "ubicacion", "descripcion",
    "foto_url", "estado_rep", "tipo_fuente", "confianza", "ingested_at",
]
```

### Filtros
`django-filter` + `SearchFilter` + `OrderingFilter` en todos los ViewSets. Búsqueda por nombre: `__unaccent__icontains` (insensible a acentos — eso es el punto del plan).

---

## Hard constraints — líneas rojas

- **El público NO se autentica.** Buscar/reportar es anónimo. Cuenta = solo para escribir verdad autoritativa sobre otros (responders/instituciones).
- **`contacto` es PRIVADO, siempre.** Nunca en ningún serializer público; los responders tampoco lo ven — el sistema notifica a la familia.
- **Serializers públicos exponen SOLO:** nombre, zona, edad aprox, estado, última vez visto, links a fuentes. **Nunca** `contacto`, cédula cruda, identidad de responder ni `face_embedding`. Nunca un endpoint de volcado masivo de fotos/embeddings.
- **`fallecido` requiere corroboración.** Institución verificada + segundo aporte o fuente oficial. Un solo workspace provisional no puede marcar muertos.
- **Biometría como último recurso.** Al verificar identidad fuerte: guarda solo el resultado + embedding y descarta la imagen cruda de la cédula.
- **No somos oficiales.** Decirlo claro; tener ruta de corrección/takedown; minimizar PII pública.

---

## Access rings

- **Lectura pública** (búsqueda) → API key simple + throttling fuerte + privacy filter. Read-only.
- **Ingesta** (fuentes cooperantes) → token por fuente.
- **Acciones de responder** → JWT (`simplejwt`) + gate por rol.

API versionada `/api/v1/` desde el día uno.

---

## Conventions

- **Idioma del proyecto: español** — plan, README, nombres de tabla/columna (`registros_fuente`, `personas_canonicas`, `nombre_norm`) y vocabulario de dominio. Siempre en español.
- `registros_fuente.nombre_norm` es una STORED generated column. Postgres exige funciones IMMUTABLE allí; `unaccent()` es STABLE → la migración `personas/0001_extensions.py` crea `immutable_unaccent()`. No reemplazar por `unaccent()` directo o las migraciones se rompen.
- `cedula_norm` usa `regexp_replace(..., '\D', '', 'g')` que sí es IMMUTABLE en Postgres — sin wrapper.

---

## Commands

El backend Django vive en `apps/api/`. El compose levanta todo el stack (db + redis + api).

```bash
# Stack completo (db + redis + api con hot-reload)
cd infra && docker compose up -d

# Solo infra (db + redis), API local:
cd infra && docker compose up -d db redis

# Migraciones y comandos dentro del contenedor:
docker compose exec api python manage.py migrate
docker compose exec api python manage.py test
docker compose exec api python manage.py ingesta_consolidador --archivo /tmp/todos_registros.json

# Copiar un archivo al contenedor:
docker cp /ruta/local/archivo.json reencuentro_api:/tmp/archivo.json

# Alternativa local (sin Docker para la API):
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt
cd apps/api && set -a && . ../../infra/.env && set +a
apps/api/.venv/bin/python manage.py migrate
apps/api/.venv/bin/python manage.py runserver

# Lint:
apps/api/.venv/bin/ruff check apps/api
# CI (falla si hay drift de modelos):
apps/api/.venv/bin/python manage.py makemigrations --check --dry-run
```

**URLs clave** (bajo `/api/v1/`):
- `personas/` — buscador público
- `registros/` — registros fuente (en construcción)
- `schema/` — OpenAPI JSON
- `docs/` — Swagger UI
- `redoc/` — ReDoc
