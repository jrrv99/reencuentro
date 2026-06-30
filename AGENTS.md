# AGENTS.md

Guidance for AI coding agents working in this repository. Mirrors `CLAUDE.md` — both files must stay in sync.

## Project status

**Fase 0 — en curso.** Hitos completados:
- Esqueleto del monorepo (`apps/api/` Django + `config/` + 5 apps registradas)
- `infra/` compose completo: Postgres+pgvector, Redis, **y el servicio `api` Django**
- App `personas`: modelos del plan §3 (con `nombre_norm`/`cedula_norm` generados, índices GIN-trigram, HNSW), migraciones 0001–0003
- App `ingesta`: conector idempotente del consolidador (upsert sobre `(fuente, id_origen)`, `content_hash`, centinelas de cédula, `SyncRun`)
- **56k registros reales cargados en local**
- `GET /api/v1/personas/` funcional (buscador público, privacy-filtered)

**En construcción ahora:** `RegistroFuenteViewSet` + refactor a `HyperlinkedModelSerializer` con expansión inline en detalle (plan §9).

**Pendiente:** motor de dedup (Hito 2b), caras (`identidad`), instituciones/responders, Next.js.

**Fuentes de verdad:**
- `plans/plan_migracion_datos.md` — arquitectura de datos y APIs
- `plans/plan_maestro_desaparecidos.md` — diseño completo del sistema
- Leer siempre el plan relevante antes de construir.

---

## What this is

Agregador con resolución de identidades para desaparecidos tras el terremoto Venezuela 2026. No es otro registro: ingiere de los registros existentes, deduplica entre ellos y expone una sola búsqueda que muestra cada persona una vez y enlaza de vuelta a cada origen.

---

## Repo layout

```
reencuentro/
├── apps/api/
│   ├── config/        # settings, celery, urls
│   ├── personas/      # modelos + serializers + views + filters
│   ├── ingesta/       # conector consolidador + SyncRun + Celery task
│   ├── dedup/         # [pendiente]
│   ├── identidad/     # [pendiente]
│   └── instituciones/ # [pendiente]
├── infra/             # docker-compose, .env
└── plans/             # plan maestro + plan de migración
```

---

## API design — patrón obligatorio (plan §9)

### ViewSets
`ReadOnlyModelViewSet`. Siempre `get_serializer_class` para separar lista de detalle:

```python
def get_serializer_class(self):
    if self.action == "retrieve":
        return MiRecursoDetailSerializer
    return MiRecursoSerializer
```

### Serializers lista / detalle
- **Lista:** `HyperlinkedModelSerializer` con `HyperlinkedRelatedField` para relaciones (devuelve URLs).
- **Detalle:** hereda del de lista, sobreescribe `to_representation` para expandir relaciones inline con el serializer del recurso relacionado.

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

### Privacidad — allow-list estricta (línea roja)
`contacto`, `face_embedding`, `raw_payload`, `cedula` cruda y datos de responder **NUNCA** en serializers públicos. La lista está en `fields = [...]` del Meta. Si no está en `fields`, no existe. **Nunca filtrar con `if`.**

```python
PUBLIC_REGISTRO_FIELDS = [
    "url", "fuente", "url_origen", "tipo", "nombre",
    "edad", "sexo", "zona", "ubicacion", "descripcion",
    "foto_url", "estado_rep", "tipo_fuente", "confianza", "ingested_at",
]
```

---

## Hard constraints — líneas rojas

- **El público NO se autentica.** Buscar/reportar es anónimo. Cuenta = solo responders/instituciones.
- **`contacto` es PRIVADO, siempre.** Nunca en ningún serializer público.
- **`fallecido` requiere corroboración.** No puede marcarlo un solo workspace provisional.
- **Sin cédula, NUNCA auto-merge.** La cara surfacea candidatos, no decide.
- **Biometría como último recurso.** Descarta imagen cruda de cédula tras verificación.

---

## Conventions

- **Idioma del proyecto: español** — nombres de tabla/columna, vocabulario de dominio. Siempre en español.
- `nombre_norm`: STORED generated column con `immutable_unaccent()` (wrapper IMMUTABLE sobre `unaccent` STABLE). No usar `unaccent()` directo — rompe migraciones.
- `cedula_norm`: `regexp_replace(..., '\D', '', 'g')` — es IMMUTABLE en Postgres, sin wrapper.
- Privacidad: allow-list en `fields`, nunca field-level filtering.
- Sin comentarios obvios. Solo comentar el WHY no-obvio.

---

## Commands

```bash
# Stack completo
cd infra && docker compose up -d

# Solo infra (db + redis):
cd infra && docker compose up -d db redis

# Comandos Django en contenedor:
docker compose exec api python manage.py migrate
docker compose exec api python manage.py test
docker compose exec api python manage.py ingesta_consolidador --archivo /tmp/archivo.json
docker cp /ruta/local/archivo.json reencuentro_api:/tmp/archivo.json

# Local (sin Docker para la API):
cd apps/api && set -a && . ../../infra/.env && set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
.venv/bin/ruff check .
.venv/bin/python manage.py makemigrations --check --dry-run
```

**URLs clave** (bajo `/api/v1/`): `personas/`, `registros/` (en construcción), `schema/`, `docs/`, `redoc/`.
