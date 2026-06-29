# Plan de Migración (v2) — `personas` intacta como fuente → `registros_fuente` limpia
### Integrar la operación del equipo (Supabase viva + worker PHP + bot) con el plan maestro

> Reemplaza la v1 ("adoptar `personas` en sitio"). Decisión corregida: **NO** se evoluciona `personas`; se deja intacta y se **ingiere** a una `registros_fuente` limpia. Audiencia: Ricardo + Claude Code.

---

## 0. Reglas de oro

1. **Sistema vivo:** `personas` en Supabase la escribe un worker PHP (AWS) y la lee un bot de WhatsApp. **No se toca** — ni columnas, ni nombres, ni datos.
2. **Probar en local primero:** todo se valida contra Postgres local (`pgvector/pgvector:pg17`) con una muestra de `personas`, antes de prod. (El free tier de Supabase no aguanta el volumen de pruebas.)
3. **Aditivo y no destructivo:** las tablas nuevas son tuyas; `personas` queda como fuente read-only.

## 0.1 Realidad de los datos (por qué esta topología)

Producción real = 3 tablas: `personas`, `documentos_vectoriales` (pgvector), `whatsapp_bot_logs`. El resto del schema son borradores.

`personas` está **sucia**: los campos no significan lo que dicen. Ejemplo real — `ultima_ubicacion` de una fila contenía la ubicación + "DATOS CRÍTICOS PARA RESCATE" + narrativa de rescate, todo junto. Muchas filas **sin cédula** y **sin URL de origen**. → Adoptarla en sitio haría que el modelo "limpio" sea la tabla sucia disfrazada. Se necesita un **borde de limpieza**.

---

## 1. Topología

```
scrapers → XLSX (recurrente)  ──► TU ingesta ──► registros_fuente (LIMPIA, tuya, con Fuente)
                                  (parse+limpia)        │ normalizar → validar CNE → dedup/cluster
                                                        ▼
                                                 personas_canonicas (+ cluster_links, claims, negativos)
                                                        │
                                                        ▼  TU nueva API
                                                  bot de WhatsApp (tras corte) + search público
```

**La fuente cruda es el XLSX del scraping, NO `personas`.** Razón: `personas` ya es el output (mal) procesado del worker PHP sobre ese mismo XLSX — merge destructivo por cédula, `Fuente` borrada, blobs mal parseados. El XLSX es la materia prima real y conserva la `Fuente`. Ingerir desde ahí evita heredar los errores del PHP.

**`personas` NO se ingiere.** Queda como la tabla legacy que sirve al bot **solo durante la coexistencia**. Al cortar, el bot pasa a consumir TU nueva API (que lee la canónica). La tabla `personas` **no se borra** — solo deja de consumirse. Sin sistemas vivos divergiendo a largo plazo.

**El XLSX es un feed RECURRENTE** (los scrapers lo regeneran cada cierto tiempo con actualizaciones + nuevos). La ingesta debe ser **idempotente e incremental** (ver §3).

- **Dev/pruebas:** Postgres local (`pgvector/pgvector:pg17`) con una muestra del XLSX.
- **Prod:** Django + sus tablas (`registros_fuente`, canónicas) en Supabase, al lado de `personas`. Las dos capas (cruda + canónica) **no son duplicación** — son origen/auditoría vs. búsqueda limpia, por diseño.

---

## 2. Esquema

### 2.1 `personas` — INTACTA
No se altera. Solo se modela en Django (unmanaged) **si** hace falta el backfill de data interna (§3.2); para el feed normal del XLSX no se usa.
```python
class PersonaLegacy(models.Model):
    # campos espejo; solo lectura, solo para el backfill único de data interna
    class Meta:
        managed = False
        db_table = 'personas'
```

### 2.2 `registros_fuente` — TUYA, limpia (CreateModel normal)
Columnas: `tipo` (buscado|encontrado), `fuente`, `id_origen`, `url_origen`, `nombre`, `nombre_norm`, `cedula`, `cedula_norm` (solo dígitos), `edad`, `sexo`, `zona`, `ubicacion`, `descripcion`, `foto_url`, `foto_phash`, `face_embedding vector(512)`, `estado_rep`, `contacto` (PRIVADO), `tipo_fuente`, `confianza`, `raw_payload jsonb`, `ingested_at`.
- **Sin unique sobre `cedula`.** Índices: gin trigram en `nombre_norm`, btree en `cedula_norm`, hnsw en `face_embedding`.
- Unicidad de ingesta: `unique (fuente, id_origen)`.

### 2.3 Capa canónica — TUYA (CreateModel normal)
`personas_canonicas` (con `cedula_estado` [confirmada|conflicto|sin_confirmar, default sin_confirmar] y `cedula_confirmada_por` [responder|oficial|cne|consenso, nullable]), `cluster_links`, `estado_claims`, `pares_negativos`. Tal cual el plan maestro §3 + revisión de cédula.

> Como **no** se adopta `personas`, no hace falta `SeparateDatabaseAndState` ni `--fake-initial`. Todas tus tablas son migraciones normales. Limpio.

---

## 3. El conector de ingesta (app `ingesta`)

### 3.1 Feed recurrente del consolidador → `registros_fuente`
**Fuente real:** el repo `aevscraping` corre un **consolidador** que mantiene un maestro llaveado por `(fuente, id)`, calcula `content_hash` (16 columnas, excluye `fecha_actualizacion`) y clasifica nuevos/actualizados/sin_cambio. Produce `datos_consolidados/todos_registros.json` (el XLSX es solo un volcado de ese JSON) y un **delta por corrida**.

**Clave de idempotencia (CONFIRMADA):** `(fuente, id_origen)` donde `id_origen = id` del consolidador. Ese `id` es **determinístico y estable**: cada scraper lo deriva del id propio de la fuente (`uuidToBigInt(person.id)` / `uuid.UUID(val).int % …` con fallback `sha256`). Misma persona → mismo id en cada corrida. Guardar como **TEXT** (no int; preservan precisión del bigint a propósito). Upsert sobre `(fuente, id_origen)`. Caveat: módulo a bigint → colisión ínfima dentro de una fuente, acotada por la llave compuesta.

**Qué consumir (preferencia):**
1. **El delta por corrida** (nuevos + actualizados) → ingesta incremental barata, no los 240k cada vez. **Ideal a futuro:** que el consolidador suba el delta a TU endpoint Django (`lib/api.py` ya sube a una API) en vez de al PHP → reemplaza el worker PHP limpiamente.
2. Si no, `todos_registros.json` completo (más limpio que parsear XLSX).
3. Último recurso, el XLSX.

**Reusar su `content_hash`** (misma definición de columnas, excluyendo `fecha_actualizacion`) para que tu "actualizado vs sin_cambio" coincida con el de ellos y la ingesta sea idempotente igual.

**Mapeo + limpieza (el borde):**
- `fuente` = `fuente` del registro. `id_origen` = `id` (TEXT).
- `cedula` → cruda + `cedula_norm`. Muchas vacías: OK, sin llave dura.
- `nombre` → + `nombre_norm`.
- `ultima_ubicacion` → **parsear el blob**: ubicación real vs. narrativa de rescate/"DATOS CRÍTICOS" → a `descripcion`.
- `observaciones` → `descripcion`. `estado` → `estado_rep` (§4). `tipo` derivado del estado.
- PRIVADOS (teléfonos, cédula de quien encuentra, quién busca) → `contacto`; nunca al serializer público.
- `raw_payload` = registro crudo completo en jsonb.
- Ollama (tier-C) para los blobs peores; `confianza` más baja.

> El `consolidator/lib/cotejo.py` ya hace matching cross-source (emite alertas, no fusiona). Complementario a tu motor de dedup; vale leerlo, pero el tuyo (matriz cédula×cara + canónica) es superior.

### 3.2 Backfill único de data interna de `personas`
El XLSX es scraping **externo**; `personas` puede tener data entrada **dentro** del sistema (estados "Encontrado" del bot, correcciones manuales, hospital) que ningún scraper produce.
- **VERIFICAR:** ¿hay data en `personas` que no venga del XLSX?
- Si sí → management command de **backfill único** de esos registros a `registros_fuente` como `fuente='legacy-interno'`, aparte del feed recurrente. Si no → ignorar `personas` por completo.

### 3.3 Coexistencia y corte
Durante la coexistencia, el bot lee `personas` (vía PHP). Tu canónica se construye en paralelo desde el XLSX. **Solo una sirve al bot a la vez** (feature flag): al cortar, el bot pasa a tu API. `personas` no se borra; deja de consumirse.

---

## 4. Enum de estado (reconciliado, conservar los del equipo)

| Legacy | `estado_rep` |
|---|---|
| Desaparecido | `sin_contacto` (o conservar label) |
| Encontrado | `encontrado_vivo` |
| Hospitalizado | `hospitalizado` |
| Refugiado | `refugiado` |
| Fallecido | `fallecido` |

El estado vive como `estado_claims` (versionado/atribuido/reversible). Mientras tanto, `registros_fuente.estado_rep` guarda el último estado reportado por la fuente.

---

## 5. Cédula como señal corroborante (no llave dura)

- Sin unique; `cedula_norm` para bloqueo fuzzy (solo cuando no hay foto).
- Matriz cédula×cara del plan maestro §5; ítem `cedula_conflicto` en la cola de revisión.
- **Servicio CNE ya existe:** el worker PHP usa `ve-cedula-service` (`VE_CEDULA_SERVICE_BASE_URL`/`_TOKEN`, endpoint `/v1/cedula/{nac}/{num}`, Bearer, cache + rate-limit ~150ms) que devuelve el `nombre_real` del registro civil. **Este es el "SENIAT" del plan.** Conseguir el token y reusarlo como **confirmación de cédula** (`cedula_estado=confirmada` si el nombre coincide). Jamás fusiona ni sobrescribe por esto.

> Nota de riesgo heredado: el worker PHP ya hace merge destructivo por cédula (gana el de `strlen` mayor). Eso ya ocurrió y es irrecuperable; importas el estado actual de cada fila, no lo sobrescrito.

---

## 6. Privacidad

El serializer público **nunca** expone los campos privados (§3). Filtrado por allow-list a nivel de serializer, no de query. Vigente desde el Hito 1.

---

## 7. Orden de ejecución

0. **Local listo:** `infra/` con `pgvector/pgvector:pg17`; conseguir una muestra del XLSX (~2k filas, anonimizada).
1. **Migraciones:** reconciliar cédula en los modelos §3 (quitar unique, agregar `cedula_norm`, `cedula_estado`, `cedula_confirmada_por`) + crear canónicas. Todas CreateModel normales.
2. **Verificar la clave de idempotencia** (¿`ID` del XLSX estable?) y si `personas` tiene data interna no presente en el XLSX.
3. **App `ingesta`:** conector `ingesta_xlsx` con mapeo + limpieza + upsert idempotente (§3.1). Backfill interno único si aplica (§3.2).
4. **Cargar la muestra** → poblar `registros_fuente`; correr 2x para confirmar 0 duplicados.
5. **Motor de dedup (Hito 2):** construir `personas_canonicas` + `cluster_links`.
6. **Servicio CNE** como señal (§5).
7. **Validar en local con volumen**, luego prod en ventana coordinada.
8. **Corte:** el bot pasa a consumir tu nueva API; `personas` deja de consumirse (no se borra).

---

## 8. Hilos abiertos

- ✅ **`id` confirmado estable y determinístico** (derivado del id de la fuente). Clave: `(fuente, id_origen)` como TEXT.
- **¿Consumir el delta del consolidador hacia tu API** (reemplazando el upload al PHP) o seguir recibiendo el JSON/XLSX en paralelo durante la coexistencia? (define el corte).
- **¿`personas` tiene data interna fuera del feed del consolidador?** (estados del bot, correcciones) → define si hay backfill único.
- **Seguridad:** anon key de Supabase hardcodeado en `chiki/scraper.py` (repo público) → mover a env y rotar; avisar al equipo.
- Token y dueño del `ve-cedula-service` (CNE).
- Tuning de Postgres local para los 240k (shared_buffers/work_mem; índices al final del backfill).
- Quién y cuándo activa el feature flag del corte del bot.

---

## 8. Hilos abiertos

- Token y dueño del `ve-cedula-service` (CNE).
- ¿El worker PHP empezará a setear `fuente`/`id_origen` para procedencia hacia adelante? (parche mínimo opcional; no bloquea.)
- Tuning de Postgres local para los 240k (shared_buffers/work_mem; índices al final del backfill).
- Cuándo y quién corta las lecturas del bot a canónicas (feature flag).
