# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Early Fase 0.** First milestone landed: the monorepo skeleton (`apps/api/` Django project
with `config/` + the five apps registered), `infra/` compose (Postgres+pgvector & Redis),
the `personas` app reproducing the plan §3 schema (with extensions, the generated
`nombre_norm`, GIN-trigram / HNSW / partial-unique indexes), and a read-only, privacy-filtered
`GET /api/v1/personas` with OpenAPI docs. Still **not built**: ingest connectors, the dedup
engine, the face stack (`identidad`), instituciones/responders, the Next.js frontend.
**The plan is the source of truth** for architecture and constraints — read it before building,
and keep it in sync if the design changes. See `## Commands` for how to run things.

## What this is

`reencuentro` is an **aggregator with identity resolution** for missing persons after the 2026 Venezuela earthquake. It is **not** another registry. It ingests from existing registries/sources, deduplicates people across them, and exposes a **single search** that shows each person once and **links back** to every origin source. It unifies existing platforms and sends them traffic — it does not compete with or replace them.

## Stack (planned)

| Concern | Tech |
|---|---|
| Core API + dedup + admin | Django / DRF (`drf-spectacular` for OpenAPI, `django-filter`, `simplejwt`) |
| Ingest & matching jobs | Celery + Celery Beat |
| Canonical store + text fuzzy | PostgreSQL (`pg_trgm`, `unaccent`) |
| Face search | **pgvector**, 512-D embeddings, HNSW + cosine (`<=>`) |
| Cache + broker | Redis |
| Connector/webhook orchestration | n8n |
| Free-text extraction from social posts | Ollama (local LLM) |
| Public search (read-heavy) | Next.js on Vercel/Cloudflare |
| Edge / cache / rate-limit | Cloudflare |
| Face stack | InsightFace (`buffalo_l`, ArcFace, ONNX) for embeddings; `imagehash` pHash for same-photo detection; `rapidfuzz` for name fuzzy |

## Intended repo layout (monorepo)

```
reencuentro/
├── apps/
│   ├── api/               # Django/DRF + Celery (the core)
│   │   ├── config/        # settings, celery, urls
│   │   ├── personas/      # registros_fuente, personas_canonicas, estado_claims, cluster_links, pares_negativos
│   │   ├── ingesta/       # Tier A/B/C connectors (Celery tasks)
│   │   ├── dedup/         # scoring + blocking + union-find
│   │   ├── identidad/     # faces (insightface+pgvector), phash, matching
│   │   └── instituciones/ # workspaces, responders, validation, auditoría
│   └── web/               # Next.js (public search + responder app)
├── infra/                 # docker-compose, Coolify config, .env templates
└── plans/                 # the master plan
```

Each Django app is an **independent module** (SiteHub philosophy): e.g. `dedup` is built and tested without touching `ingesta`. Monorepo is a deliberate choice (single builder, atomic backend+frontend changes, one CI, Coolify deploy-by-subfolder).

## Core architecture (the parts that span multiple modules)

**Raw data is never destroyed.** Three-layer identity resolution:
- `registros_fuente` — raw, one row per report per source. Crude data is canonical and immutable.
- `personas_canonicas` — the resolved entity. **It is a *view* built by clustering**, not authored data. If dedup is wrong, re-cluster without losing anything.
- `cluster_links` — which raw records are the same person (with `score`, `metodo`, `confirmado`). `pares_negativos` records "already judged NOT the same" so we never re-ask.

**One dedup engine, shared by all three systems** (`dedup/`). On insert/change of a record (via Celery): normalize → **blocking** (candidates = same zona OR same cédula OR trigram-similar name; faces compared only against this shortlist, never the whole DB) → per-pair scoring → thresholds (high = merge, medium = review queue, low = new person) → union-find clustering respecting `pares_negativos`. **Cédula match = 1.0 auto-merge. Without cédula, NEVER auto-merge** — face is a signal that surfaces candidates, never the judge (common names + facial similarity = false merges, whose cost here is atrocious).

**Estados are versioned, attributed, reversible claims** (`estado_claims`), not final truth. `personas_canonicas.estado_actual` = the most trustworthy `vigente` claim. Rollback-by-account = set `vigente=false` for all claims of an `autor_id`. This is the backbone of the trust model: identity is for **attribution and deterrence**, not for gating trust — act, but everything is attributable and undoable.

**Multi-tenant for identity/access, mono-tenant for the data.** Workspace = institution, and `institucion_id` scopes ONLY membership/permissions/auditoría. The person index (`registros_fuente`, `personas_canonicas`, `cluster_links`, face index) is **global and shared** — a doctor must match against family reports nationwide. **Do NOT use schema-per-tenant for person data.**

**The loop that justifies everything:** doctor marks "encontrado vivo en Hospital X" → `registros_fuente` row → dedup cross-matches the "buscado" (cédula or face) → `personas_canonicas` updates → **the searching family gets notified.**

### The three identity systems (all share the dedup engine)
1. **Interactive dedup on registration** — Google Person Finder style; catch the duplicate before it dirties the DB. Generous threshold (a human is deciding live). Same-photo → pHash; other photo of same person → face embedding → review.
2. **Reverse face search of found persons** — responder photographs an unidentified person, searches against the missing. High recall / low threshold (~15 candidates; injured faces degrade). **Verified responders only, every query audited. The public NEVER uploads a face to search** (that would be surveillance). No facial recognition of the deceased — that's forensic (Cruz Roja territory); focus is 100% on the living.
3. **Responders + found-person capture** — the trusted input layer. Identify in order: cédula → name → face (last resort, minimize biometric use). "No identificado" enters with photo/embedding and auto-matches when a family later uploads a photo.

### Ingest is hybrid (3 tiers), each connector an isolated Celery task
- **Tier A** — cooperation: consume CSV/JSON/PFIF exports. Cleanest; the goal is to move everything here.
- **Tier B** — scraping (requests/Playwright per site). Fragile, breaks on site changes → budget maintenance.
- **Tier C** — social free-text → Ollama extracts JSON → enters with low `confianza` + review flag. n8n orchestrates polling.

## Hard constraints — red lines (non-negotiable, enforce in code)

- **Public never authenticates.** Search/report/"I found them" is anonymous and one-touch. You register an account ONLY to write authoritative truth about others (responders/institutions). Anti-abuse for anonymous reports = Turnstile captcha + per-IP rate limit + dedup + moderation queue.
- **`contacto` (family contact) is PRIVATE, always.** Never exposed in any public serializer; responders never see it (the system notifies the family). Optional notification contact is stored privately, has no login, is never public.
- **Public serializers expose ONLY:** nombre, zona, approx edad, estado, last-seen, links to sources. **Never** `contacto`, raw cédula, responder identity, or `face_embedding`. Never a bulk endpoint that dumps photos/embeddings.
- **`fallecido`** is gated: behind workspace validation, requires corroboration (verified institution + a second contribution or official source); a single account cannot mark anyone dead. Provisional workspaces have `fallecido` **blocked**.
- **Biometrics are a last resort** (cédula/name first). When verifying strong identity (selfie-vs-cédula), store only the match result + embedding and **discard the raw cédula image**.
- **We are NOT official.** Say so clearly; provide a correction/takedown path; minimize public PII.

## Access rings (API auth)
- **Public read** (search) → simple API key + strong throttling + privacy filter. Read-only.
- **Ingest** (cooperating sources) → per-source token.
- **Responder actions** → JWT (`simplejwt`) + role gate.

API is versioned `/api/v1/` from day one. Throttle at DRF **and** Cloudflare; edge-cache reads — the existing platforms fall over because they don't cache, not for lack of money.

## Conventions

- Project language is **Spanish** — plan, README, table/column names (`registros_fuente`, `personas_canonicas`, `nombre_norm`, etc.) and domain vocabulary are Spanish. Match it.
- Build by **Fase 0 first** (per the plan §12): canonical schema + connectors for the 2 big sources + cédula/text dedup + read-only unified search with link-back. That alone resolves ~70% of the pain.

## Commands

The Django backend lives in `apps/api/`. All `manage.py` commands need the DB/Redis
env vars loaded; source `infra/.env` first (it carries the host ports — they default
to 5432/6379 but the committed `.env.example` may have been overridden locally if those
ports were taken).

```bash
# 1. Infra: Postgres (pgvector) + Redis. Only DB + broker; the API runs locally.
cd infra && cp -n .env.example .env && docker compose up -d && cd ..

# 2. Python env (base deps only; the InsightFace face stack is requirements-faces.txt,
#    deferred until the `identidad` milestone — heavy ONNX build, not needed yet).
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt

# From apps/api/, load env once per shell, then run manage.py:
cd apps/api && set -a && . ../../infra/.env && set +a

apps/api/.venv/bin/python manage.py migrate          # apply migrations
apps/api/.venv/bin/python manage.py runserver         # dev server → http://127.0.0.1:8000
apps/api/.venv/bin/python manage.py test              # run the test suite
apps/api/.venv/bin/python manage.py makemigrations --check --dry-run   # CI: fail on model drift
apps/api/.venv/bin/ruff check apps/api                # lint + import order
```

Key URLs (under `/api/v1/`): `personas/` (public search), `schema/` (OpenAPI),
`docs/` (Swagger UI), `redoc/`.

> **Schema note:** `registros_fuente.nombre_norm` is a STORED generated column. Postgres
> requires IMMUTABLE functions there, but `unaccent()` is STABLE — so migration
> `personas/0001_extensions.py` creates an `immutable_unaccent()` wrapper. Don't replace it
> with bare `unaccent()` or migrations break. (Also why the public search filter uses the
> `__unaccent` lookup — accent-insensitive search is the whole point.)
