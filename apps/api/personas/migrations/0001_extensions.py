"""Extensiones de Postgres + función immutable_unaccent.

pg_trgm  → índice GIN trigram para fuzzy de nombre.
unaccent → normalización de acentos.
vector   → pgvector (embeddings de cara, índice HNSW).

immutable_unaccent: unaccent(text) es STABLE y Postgres no la admite en una columna
GENERATED ALWAYS ... STORED (exige IMMUTABLE). La envolvemos en una función IMMUTABLE
para que `registros_fuente.nombre_norm` (migración 0002) pueda generarse. La forma
observable del esquema del plan §3 se mantiene.
"""
from django.contrib.postgres.operations import (
    CreateExtension,
    TrigramExtension,
    UnaccentExtension,
)
from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),  # pg_trgm
        UnaccentExtension(),  # unaccent
        VectorExtension(),  # vector (pgvector)
        migrations.RunSQL(
            sql=(
                "CREATE OR REPLACE FUNCTION immutable_unaccent(text) "
                "RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS "
                "$$ SELECT unaccent('unaccent', $1) $$;"
            ),
            reverse_sql="DROP FUNCTION IF EXISTS immutable_unaccent(text);",
        ),
    ]
