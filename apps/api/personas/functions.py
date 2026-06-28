"""Funciones SQL a medida usadas por los modelos.

`immutable_unaccent` existe porque la `nombre_norm` del plan §3 es una columna
GENERATED ALWAYS ... STORED, y Postgres exige que esas expresiones sean IMMUTABLE.
La función `unaccent(text)` de la extensión es STABLE (depende del diccionario por
defecto), así que el SQL literal del plan no migraría. La envolvemos en una función
IMMUTABLE (creada en la migración 0001) — la forma observable del esquema se mantiene.
"""
from django.db.models import Func, UUIDField


class GenRandomUUID(Func):
    """gen_random_uuid() — default de las PK uuid (núcleo de Postgres ≥13)."""

    function = "gen_random_uuid"
    output_field = UUIDField()


class ImmutableUnaccent(Func):
    """Wrapper IMMUTABLE de unaccent, apto para columnas generadas."""

    function = "immutable_unaccent"
    arity = 1


class RegexpReplace(Func):
    """regexp_replace(source, pattern, replacement, flags)."""

    function = "regexp_replace"
    arity = 4
