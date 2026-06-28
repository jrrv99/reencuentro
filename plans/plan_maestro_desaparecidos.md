# Plan Maestro — Hub de centralización de desaparecidos
### Terremoto Venezuela 2026 (doblete 7.2 / 7.5, 24 de junio)

> Reemplaza los dos documentos anteriores (registro y hub). Este es el diseño cerrado de punta a punta.

---

## 1. Qué es y qué no es

**No es** un registro más. Ya existen varios (Desaparecidos Terremoto Venezuela, Venezuela Te Busca, VenApp, bots de Telegram, cuentas de Instagram, Cruz Roja). El problema es que la data está **dispersa**: una familia tiene que buscar en 5 lados y la misma persona aparece duplicada en cada uno.

**Es** un **agregador con resolución de identidades**: ingiere de todas las fuentes, deduplica entre ellas, y ofrece **un solo buscador** que muestra a cada persona una vez y **enlaza de vuelta** a cada origen. No compite con las plataformas existentes: las unifica y les manda tráfico.

### Las 3 decisiones estratégicas
1. **El tráfico real no es "billones".** ~28M habitantes + diáspora; pico de cientos de miles buscando, decenas de miles de registros. Es gratis si se cachea en el borde. Las páginas actuales se caen por no cachear, no por falta de plata.
2. **No fragmentar.** Agregar + link-back en vez de crear otro silo.
3. **El registro canónico es una *vista* construida por clustering** sobre los registros de fuente. Nunca se destruye la data cruda; si el dedup se equivoca, se re-clusteriza sin perder nada.

### Modelo de acceso — quién se registra
**El público NO se registra. Solo las instituciones.** Decisión deliberada, por fricción y por seguridad:
- **Fricción:** una familia en pánico no puede toparse con "crea una cuenta, verifica tu correo". Buscar y reportar debe ser **anónimo y de un toque**.
- **Seguridad:** no guardar cuentas del público = no existe una base de familias-de-víctimas que filtrar o explotar. Menos PII almacenada, menos superficie de ataque (importa en el contexto VE).

La línea es nítida: **te registras solo si vas a *escribir verdad autoritativa* sobre otros.**
- **Público (familias, cualquiera)** → sin cuenta. Busca, reporta, marca "lo encontré". Anónimo, con captcha + rate limit como barrera.
- **Responder (institución)** → se registra en su workspace; tiene poder de estado autoritativo + búsqueda por cara → exige identidad y auditoría.
- **Partner oficial** → registrado y validado.

> ⚠️ **"Registrar" en este doc es ambiguo a propósito** — cuidado: registrar *una persona desaparecida* (lo hace el público, sin cuenta) ≠ registrarse *como usuario* (solo responders). El §6 "registra directo en el hub" se refiere a lo primero.

> **Contacto de notificación (no es cuenta):** el público puede dejar **opcionalmente** un correo/teléfono *solo para recibir el aviso* cuando aparezca su persona. Se guarda privado, nunca público, y no tiene login. Es un dato de notificación, no un registro. Sin él, no hay a quién avisar — y la notificación es el corazón de la plataforma.

> **El reporte anónimo exige anti-abuso más fuerte** (no hay cuenta detrás): captcha (Turnstile) + rate limit por IP + dedup + cola de moderación. Un troll mete ruido, pero nada es destructivo y todo es reversible.

---

## 2. Stack (lo que Ricardo ya tiene/planea)

| Pieza | Tecnología |
|---|---|
| Core API + dedup + admin | Django / DRF |
| Jobs de ingesta y matching | Celery + Celery Beat |
| Store canónico + fuzzy de texto | PostgreSQL (`pg_trgm`, `unaccent`) |
| Búsqueda por cara | **pgvector** (embeddings 512-D) |
| Caché + broker | Redis |
| Orquestar conectores/webhooks | n8n |
| Extraer datos de posts en texto libre | Ollama (LLM local) |
| Buscador público (lectura masiva) | Next.js en Vercel/Cloudflare |
| Borde / caché / rate-limit | Cloudflare |
| Infra | Coolify@Contabo (dev) → Hetzner (prod) |

---

## 3. Modelo de datos

Regla de oro: **un índice de personas, varios usos.** Buscados y encontrados son el mismo tipo de registro, diferenciados por una bandera.

### `registros_fuente` — lo crudo (1 por reporte por fuente)
```sql
create extension if not exists pg_trgm;
create extension if not exists unaccent;
create extension if not exists vector;   -- pgvector

create table registros_fuente (
  id            uuid primary key default gen_random_uuid(),
  tipo          text not null,            -- 'buscado' | 'encontrado'
  identificado  boolean default true,     -- false = encontrado sin identificar
  fuente        text not null,            -- 'dtv' | 'vtb' | 'venapp' | 'hospital_vargas' | 'ig_*'
  id_origen     text,
  url_origen    text,                     -- link de vuelta para verificar
  nombre        text,
  nombre_norm   text generated always as (lower(unaccent(regexp_replace(coalesce(nombre,''),'\s+',' ','g')))) stored,
  cedula        text,
  edad          int,
  sexo          text,
  zona          text,
  descripcion   text,                     -- ropa, tatuajes, cicatrices, rasgos
  foto_url      text,
  foto_phash    text,                     -- perceptual hash: detecta MISMA foto
  face_embedding vector(512),             -- InsightFace: detecta MISMA persona en otra foto
  estado_rep    text,                     -- sin_contacto | encontrado_vivo | herido | fallecido
  ubicacion     text,                     -- hospital/centro donde está (si encontrado)
  contacto      text,                     -- PRIVADO. Nunca público.
  tipo_fuente   text default 'familiar',  -- familiar | rescatista | hospital | oficial
  confianza     real default 1.0,         -- baja si vino de extracción LLM
  raw_payload   jsonb,
  ingested_at   timestamptz default now(),
  unique (fuente, id_origen)
);

create index idx_rf_nombre on registros_fuente using gin (nombre_norm gin_trgm_ops);
create index idx_rf_zona   on registros_fuente (zona);
create unique index idx_rf_cedula on registros_fuente (cedula) where cedula is not null;
create index idx_rf_face on registros_fuente using hnsw (face_embedding vector_cosine_ops);
```

### `personas_canonicas` — la entidad resuelta
```sql
create table personas_canonicas (
  id             uuid primary key default gen_random_uuid(),
  nombre_display text,
  cedula         text,
  zona           text,
  estado_actual  text,        -- derivado del registro más confiable/reciente
  foto_principal text,
  n_fuentes      int default 1,
  updated_at     timestamptz default now()
);
```

### `cluster_links` — qué registros son la misma persona
```sql
create table cluster_links (
  registro_id   uuid primary key references registros_fuente(id) on delete cascade,
  persona_id    uuid references personas_canonicas(id) on delete cascade,
  score         real,
  metodo        text,         -- cedula | phash | fuzzy | cara | llm | manual | usuario
  confirmado    boolean default false
);
```

### `pares_negativos` — "ya dijeron que NO son la misma"
```sql
create table pares_negativos (
  registro_a uuid references registros_fuente(id) on delete cascade,
  registro_b uuid references registros_fuente(id) on delete cascade,
  primary key (registro_a, registro_b)
);
```

### Instituciones, responders y auditoría (Sistema 3)
```sql
-- Workspace = institución. Solo gobierna acceso; la data de personas es global.
create table instituciones (
  id        uuid primary key default gen_random_uuid(),
  nombre    text not null,
  tipo      text,             -- hospital | rescate | oficial
  estado    text default 'provisional',  -- provisional | verificado
  validada_por text,          -- partner | dominio_correo | manual
  correo_dominio text,        -- para validación por dominio institucional
  admin_id  uuid,
  created_at timestamptz default now()
);

create table responders (
  id            uuid primary key default gen_random_uuid(),
  institucion_id uuid references instituciones(id),
  nombre        text,
  cedula        text,
  correo        text,
  rol           text,         -- responder | admin_institucion | partner_oficial
  identidad_verificada boolean default false,  -- selfie-vs-cédula (solo roles sensibles)
  face_embedding vector(512), -- opcional, p/ login con cara; cédula cruda NO se guarda
  token         text,
  activo        boolean default true,
  invited_at    timestamptz default now()
);

create table auditoria (
  id          uuid primary key default gen_random_uuid(),
  responder_id uuid references responders(id),
  accion      text,           -- busqueda_cara | marca_estado | identifica | ...
  registro_id uuid,
  detalle     jsonb,
  ip          text,
  created_at  timestamptz default now()
);

-- Estados como claims versionados/atribuidos/reversibles (base del modelo de confianza)
create table estado_claims (
  id           uuid primary key default gen_random_uuid(),
  persona_id   uuid references personas_canonicas(id) on delete cascade,
  estado       text not null,   -- sin_contacto | encontrado_vivo | herido | fallecido
  ubicacion    text,
  autor_tipo   text,            -- familiar | responder | oficial | sistema
  autor_id     uuid,            -- responder_id o registro_fuente que lo originó
  corrobora_a  uuid,            -- otro claim que confirma (p/ fallecido)
  vigente      boolean default true,   -- false = revertido/superado
  disputado    boolean default false,  -- la familia lo objetó
  created_at   timestamptz default now()
);
create index idx_claims_persona on estado_claims (persona_id, vigente);
-- estado_actual de personas_canonicas = claim vigente más confiable.
-- Rollback por cuenta = marcar vigente=false en todos los claims de un autor_id.
```

---

## 4. Ingesta híbrida (3 tiers)

Cada conector es una **tarea Celery** aislada, con su manejo de errores, que escribe a `registros_fuente`. Celery Beat re-corre incremental cada N minutos.

- **Tier A — Cooperación:** fuentes que aceptan exportar → consumes su CSV/JSON/PFIF. Lo más limpio.
- **Tier B — Scraping:** sitios sin API → parser por sitio (requests/Playwright). Frágil; se rompe cuando cambian → presupuestar mantenimiento; prioridad = mover a Tier A.
- **Tier C — Social + LLM:** Instagram/X/Telegram en texto libre → Ollama extrae JSON (`nombre, edad, zona, estado`) → entra con `confianza` baja y bandera de revisión. n8n orquesta el polling.

---

## 5. Motor de deduplicación (el corazón compartido de todo)

Corre en Celery cuando entra/cambia un registro. **Es el mismo motor para los 3 sistemas**; solo cambia, al final, si pregunta a un usuario o manda a una cola.

1. **Normalizar:** `unaccent` + minúsculas + colapsar espacios (ya en `nombre_norm`).
2. **Bloqueo (evita O(n²)):** candidatos = misma `zona` **o** misma cédula **o** nombre trigram-similar. La cara se compara **solo contra ese shortlist**, no contra toda la DB.
3. **Scoring por par:**
   - Cédula igual → 1.0 (auto).
   - Misma foto (`phash` igual) → señal fortísima.
   - Si no → `score = 0.5·fuzz(nombre) + 0.2·edad(±3) + 0.2·(zona) + 0.1·(1 − dist_cara)`
4. **Umbrales:**
   - alto → link/merge,
   - medio → **cola de revisión** (Ollama puede pre-opinar),
   - bajo → persona nueva.
5. **Clustering:** union-find sobre los links. Respeta `pares_negativos`.

> **La cara es una señal, no el juez.** "María Pérez" es comunísimo; dos distintas que se parezcan darían merge falso. Por eso, sin cédula, nunca se fusiona automático.

---

## 6. Sistema 1 — Dedup de personas en búsqueda (interactivo)

Para quien **registra directo en el hub**. Patrón estilo Google Person Finder: atrapar el duplicado *antes* de que ensucie la base.

**Chequeo progresivo:**
1. Al escribir nombre + zona → candidatos por texto al instante: *"Ya hay 3 'María Pérez' en Carabobo."*
2. Al subir la foto → re-rankea **esos** candidatos por similitud de cara.

**Lo que ve el usuario:** 1–3 candidatos con foto + nombre + zona + edad + última vez visto. Nunca el contacto del que reportó. Mensaje: *"Es posible que esta sea la persona que intentas registrar."*

**Decisión del usuario:**
- *"Sí, es la misma"* → no crea registro nuevo; suma su foto/avistamiento/contacto al existente (`cluster_link` confirmado por usuario). Gana todo el sistema.
- *"No, es otra"* → crea registro nuevo **y** guarda el `par_negativo` (no volver a preguntar).

**Dos sub-casos de foto (la distinción clave):**
- Amigo sube la **misma foto** → `phash` → casi seguro duplicado.
- Amigo sube **otra foto** de la misma persona → embedding de cara → candidato a revisión.

**Umbral generoso aquí:** como hay un humano decidiendo en el acto, se muestran más candidatos (más recall). Mostrar uno de más es gratis. El umbral conservador se reserva para el merge automático de la data ingerida.

---

## 7. Sistema 2 — Búsqueda inversa por cara de encontrados

La misma consulta, al revés: un responder tiene a alguien sin identificar, toma foto, busca contra los buscados.

- **Recall alto / umbral bajo:** devuelve ~15 candidatos, no 2. La cara de un herido se degrada (hinchazón, golpes) → mejor que un humano descarte de más.
- **Cerrado a responders verificados** (Sistema 3). El público **nunca** sube una cara para buscar (sería vigilancia). Cada consulta se **audita**.
- **Confirmación humana siempre**, cruzando ropa, tatuajes, cicatrices, documentos.

**Fallecidos:** por la naturaleza del siniestro la cara casi no sirve (trauma facial). **No se incluye reconocimiento facial de muertos**: eso es forense (tatuajes, ropa, documentos, ADN) y territorio de Cruz Roja. Foco 100% en los **vivos**; para fallecidos, coordinar/enlazar con Cruz Roja.

---

## 8. Sistema 3 — Personal capacitado (responders) + captura de encontrados

La **capa de entrada confiable**: sin esto, el Sistema 2 no tiene quién lo alimente con data válida.

### Parte A — Registro de instituciones (modelo multi-workspace)

Cada **workspace = una institución** (clínica, hospital, organización). Los miembros del workspace son los responders. El admin del workspace mete a su gente porque sabe quién trabaja ahí: **ese vouching es la verificación base** (se verifican instituciones, no individuos).

#### ⚠️ Corrección crítica: el tenant es solo para acceso, NO para la data
En un SaaS normal (y en SiteHub con `django-tenants` schema-per-tenant) cada workspace está aislado. **Aquí eso sería fatal:** el punto es que un doctor de un hospital matchee contra reportes de familias de todo el país y contra encontrados de otros hospitales. Por lo tanto:

- **Global / compartido entre todos los workspaces:** el índice de personas (`registros_fuente`, `personas_canonicas`, `cluster_links`, índice de caras). Una sola base.
- **Scoped al workspace:** membresía, permisos, auditoría.

→ **Multi-tenant para identidad/acceso, mono-tenant para la data.** NO usar schema-per-tenant para las personas: schema único compartido con `institucion_id` solo en las tablas de acceso.

#### Datos de los miembros — escalonados (no todo de entrada)
- **Siempre (fricción baja):** nombre + cédula (número) + correo + rol. Suficiente para que el admin lo agregue y empiece a capturar data **no destructiva** (identificar, marcar vivo, ubicación). En emergencia, onboarding en minutos.
- **Solo para acciones sensibles** (`fallecido`, partner oficial): identidad fuerte → foto de cédula y/o cara.

> **Por qué no KYC pesado a todos:** acumular documentos de identidad + biometría de cientos de responders en plena crisis es un blanco de filtración serio (quién trabaja en qué hospital + sus cédulas). Pedirlo solo donde el riesgo de la acción lo justifique.

> **Truco de liability (reusa el stack de caras):** al verificar identidad fuerte, corre el match selfie-vs-foto-de-cédula con InsightFace, guarda solo el resultado + embedding, y **descarta la imagen cruda de la cédula.** Verificas sin retener el documento.

#### Niveles de acceso
- **público** → solo busca por nombre; nunca registra encontrados ni busca por cara.
- **responder de institución** → registra encontrados, busca por cara.
- **admin_institucion** → gestiona los miembros de su workspace.
- **partner oficial** (Cruz Roja, Protección Civil).

#### Flujo de alta y validación (el "dial")
1. Cualquiera crea un workspace → estado **provisional**. El creador es `admin_institucion`.
2. Provisional: su gente captura **no destructivo** (identificar, vivo, ubicación). `fallecido` **bloqueado**.
3. **Validación → verificado:** por vouch de un partner (Cruz Roja/Protección Civil confirma que es real), por dominio de correo institucional, o por revisión manual. Desbloquea acciones sensibles.
4. El admin invita por correo (magic link) → el miembro pone su clave → completa identidad si su rol lo exige.

Arrancar permisivo para **captura** las primeras horas; `fallecido` **siempre** detrás de validación.

> **Branch** (redes con varias sedes) → diferido. v1 plano: workspace = una institución.

### Parte B — Cómo registra (el doctor con 30 pacientes)
Rápido y **tolerante a offline** (el wifi del hospital se cae). Por paciente:
1. **Identificar** en orden de preferencia:
   - **Cédula** (rápido y exacto) → match exacto.
   - **Nombre** (si está consciente) → texto.
   - **Cara** (solo inconsciente sin documentos) → top-K para confirmar visual. La cara es **último recurso** → minimiza uso del dato biométrico.
2. **Confirmar**: elige del shortlist o marca **"no identificado"**.
3. **Registrar**: vivo / herido / fallecido + hospital/centro + notas (consciente/inconsciente).

El **"no identificado"** entra al índice con su foto/embedding y **se cruza automáticamente** cuando después una familia sube una foto. Así se conectan los tres sistemas: el encontrado-sin-identificar de hoy se resuelve con el reporte de mañana.

### Parte C — Barreras (la capa de más poder)
- **Auditoría total** de cada acción (quién, qué, cuándo, desde dónde).
- **Los responders NO ven los contactos de las familias.** Registran estado; el sistema notifica a la familia. Evita cosecha de teléfonos.
- **`fallecido`** con doble confirmación o restringido a nivel oficial.
- Un estado de **responder/hospital pisa al "sin contacto"** de un familiar (`tipo_fuente` más confiable).

### Parte D — Modelo de confianza (el cómo de la validación)

**Premisa que lo cambia todo: no intentes verificar que la persona sea *confiable*. No se puede.** La cédula y el selfie no prueban que alguien sea buena persona — prueban *quién es*. Su función no es filtrar confianza, sino hacer cada acción **atribuible, con consecuencias y reversible**. Pasas de *"demuéstrame que eres confiable antes de actuar"* a *"actúa, pero todo queda a tu nombre y se puede deshacer"*. Dejas de hacer de portero.

**Valida fuerte solo el poder peligroso, no a todos para todo.** Casi todo lo que hace un responder es de bajo daño y se auto-corrige (marcar "vivo en Hospital X" lo corrige la familia si está mal). Lo único de verdad peligroso es `fallecido`. Entonces la identidad fuerte (selfie-vs-cédula) **solo desbloquea ese 5%**. El problema deja de ser "validar a miles" y pasa a ser "validar a los pocos que necesitan ese poder".

**Bootstrapping de instituciones (no una por una en frío):**
- **Ancla humanitaria:** enchufarse a un partner creíble (Cruz Roja / su programa de Restablecimiento del Contacto entre Familiares). Ellos validan su red y tú **heredas** esa confianza. Resuelve el grueso con una sola alianza.
- **Lista pública finita:** los hospitales de Carabobo, La Guaira, Caracas y Aragua son decenas, no miles, y son conocidos. Pre-cargarlos desde data pública; el resto entra provisional.
- **Dominio de correo institucional + llamada al número público** del hospital para confirmar al admin.
- **Cross-vouch:** una institución verificada avala a otra.

**Delega la validación hacia abajo (clave siendo una sola persona):** el partner valida su red → el `admin_institucion` valida a *sus* miembros (él sabe quién trabaja ahí, esa *es* la verificación) → tú solo manejas las anclas raíz y los abusos.

**Red de seguridad (hace que un infiltrado no haga daño real):**
- **Nada es destructivo:** cada acción es un *claim* versionado y atribuido, no una verdad final.
- **`fallecido` requiere corroboración:** institución verificada + segundo aporte o fuente oficial. Un solo malicioso no puede marcar muerto a nadie.
- **Detección de anomalías:** una cuenta que marca 40 personas en 10 min se congela y se revisa.
- **La familia puede disputar** cualquier estado sobre su persona.
- **Rollback por cuenta:** si una resulta podrida, se deshace de un golpe *todo* lo que hizo (por eso `cluster_link` guarda `metodo` y autor).

> La identidad es para **atribuir y disuadir**, no para confiar. El diseño aguanta igual ante el malicioso *y* ante el error honesto — que en catástrofe será mucho más común. Ningún sistema elimina el riesgo: lo acota y lo hace reversible. Qué tan estricto se arranca es una perilla movible en caliente.

---

## 9. El loop que cierra todo

```
Doctor marca "encontrado vivo en Hospital X"
   → registro_fuente (tipo=encontrado, estado=encontrado_vivo, ubicacion=Hospital X)
   → motor de dedup lo cruza con el "buscado" (cédula o cara)
   → persona_canonica se actualiza a "encontrado_vivo"
   → la familia que buscaba RECIBE LA NOTIFICACIÓN
```
Ese es el momento para el que existe toda la plataforma.

---

## 10. Stack de reconocimiento facial

- **Embedding:** InsightFace (`buffalo_l`, ArcFace, ONNX) → vector 512-D. (DeepFace para prototipar rápido, luego migrar.)
- **Misma foto:** perceptual hash (`imagehash`) — barato, casi 100%, detecta reposteos.
- **Almacenamiento/búsqueda:** pgvector con índice HNSW, similitud de coseno (`<=>`), que además sirve de capa de bloqueo.
- **Cómputo:** generar embeddings en lote vía Celery. CPU lento pero viable; GPU vuela.

**Verdades duras:** sin cédula el match nunca es perfecto; la cara siempre **surfacea candidatos, no decide**; el costo de un falso positivo aquí es atroz (decirle a una familia que apareció su persona por error) → verificación humana + link-back, siempre.

---

## 11. Riesgos y líneas rojas (no opcionales)

- **Contactos privados, siempre.** Exponerlos habilita estafas/extorsión (riesgo real en VE).
- **`fallecido` con moderación.** Un falso reporte de muerte propagado es devastador.
- **Búsqueda por cara solo para responders verificados + auditada.** Nunca pública.
- **Biometría como último recurso** (cédula/nombre primero).
- **Eres NO oficial.** Dilo claro; ten ruta de corrección/takedown. Minimiza PII pública.
- **Scraping se rompe** → mantenimiento constante; migrar fuentes a cooperación.

---

## 12. Plan por fases

**Fase 0 — Días (resuelve ~70% del dolor):** esquema canónico + conectores de las 2 fuentes grandes (scraping si no cooperan) + dedup por cédula y fuzzy de texto + buscador unificado read-only con link-back.

**Fase 1:** capa de foto (pHash + embeddings InsightFace/pgvector) + Sistema 1 interactivo + cola de revisión + Cloudflare cache + conector social con Ollama.

**Fase 2:** Sistema 3 (responders/instituciones + captura + notificación) + Sistema 2 (búsqueda inversa por cara) + admin de merge/split + pitch de cooperación + formato compartido (PFIF) + tolerancia offline.

---

## 13. Cooperación (porque la data es híbrida)

Mensaje a los dueños de las 2–3 plataformas grandes:
> *"Monto un meta-buscador neutral que **enlaza de vuelta a ustedes y les manda tráfico**, no los reemplaza. Solo necesito un export read-only (CSV/JSON) o permiso para indexar. El dedup entre fuentes nos ayuda a todos."*

Énfasis: link-back, crédito, sin monetización, no oficial. Eso baja la resistencia.

---

## 14. Estructura del proyecto y arranque

**Decisión: monorepo.** Una persona construyendo rápido → cambios atómicos backend+frontend, una sola CI, deploy por subcarpeta en Coolify. (Polyrepo solo cobra impuesto de sincronización.)

### Árbol del repo (`reencuentro`)
```
reencuentro/
├── apps/
│   ├── api/               # Django/DRF + Celery (el core)
│   │   ├── config/        # settings, celery, urls
│   │   ├── personas/      # registros_fuente, canonicas, claims, links, negativos
│   │   ├── ingesta/       # conectores Tier A/B/C (tareas Celery)
│   │   ├── dedup/         # motor de scoring + bloqueo + union-find
│   │   ├── identidad/     # caras (insightface+pgvector), phash, matching
│   │   └── instituciones/ # workspaces, responders, validación, auditoría
│   └── web/               # Next.js (buscador público + app de responders)
├── infra/                 # docker-compose, configs Coolify, .env templates
└── docs/                  # este plan
```
Cada app de Django es un **módulo independiente** (filosofía SiteHub): el dedup se construye y testea sin tocar la ingesta.

> **Separar solo si:** el servicio de caras necesita GPU/escalado propio → `apps/faces/` desplegado aparte, pero **dentro del mismo repo**. No en v1.

### Paquetes base
```bash
pip install django djangorestframework drf-spectacular django-filter \
  djangorestframework-simplejwt celery redis "psycopg[binary]" pgvector \
  django-cors-headers rapidfuzz insightface imagehash
```

### APIs públicas (la estrategia del agregador hecha realidad)
DRF + `drf-spectacular` (OpenAPI auto). Versionado `/api/v1/` desde el día uno.

**Regla crítica de privacidad:** el serializer público **nunca** expone `contacto`, identidad de responders, cédula cruda ni `face_embedding`. Solo: nombre, zona, edad aprox, estado, última vez visto, links a fuentes.

**Tres anillos de acceso:**
- **Lectura pública** (búsqueda) → API key simple + throttling fuerte + privacy-filter. Read-only.
- **Ingesta** (fuentes que cooperan) → token por fuente.
- **Acciones de responder** → JWT (`simplejwt`) + gate por rol.

**Endpoints base:**
```
GET  /api/v1/personas?nombre=&zona=&estado=   # búsqueda (throttled, filtrada)
GET  /api/v1/personas/{id}                    # detalle + links a fuentes
POST /api/v1/reportes                         # registrar (captcha + rate limit)
GET  /api/v1/export?format=pfif               # interop
POST /api/v1/encontrados                      # responder marca estado (auth)
```
Obligatorio: `django-filter` + paginación, CORS, throttling DRF **y** Cloudflare, caché de borde sobre lectura. Nunca un endpoint que vuelque fotos/embeddings en masa.

> El README vivo y el detalle de setup van en el **repo**, no aquí. Este plan solo da lo necesario para entender y arrancar.

---

### Estado del diseño
**Cerrado de punta a punta.** Ingesta híbrida, dedup entre fuentes, los 3 sistemas de identidad, el modelo multi-workspace para instituciones, y el loop de notificación. Listo para empezar a construir por la Fase 0.
