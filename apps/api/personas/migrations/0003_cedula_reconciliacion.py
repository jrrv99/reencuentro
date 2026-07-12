# Migración aditiva — reconciliación de cédula (plan §2.2, §5).
#
# Cambios:
# 1. Quita el unique parcial sobre registros_fuente.cedula (la cédula se repite entre
#    fuentes; eso ES el duplicado que detecta el motor de dedup).
# 2. Agrega cedula_norm como columna GENERATED STORED (solo dígitos).
# 3. Agrega índice btree idx_rf_cedula en cedula_norm (no unique, para bloqueo de dedup).
# 4. Agrega content_hash en registros_fuente (sha256 del registro crudo; idempotencia).
# 5. Agrega cedula_estado + cedula_confirmada_por en personas_canonicas (matriz §5).

import django.db.models.functions.comparison
import personas.functions
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personas", "0002_initial"),
    ]

    operations = [
        # 1. Quitar unique parcial sobre cedula
        migrations.RemoveConstraint(
            model_name="registrofuente",
            name="idx_rf_cedula",
        ),
        # 2. Agregar cedula_norm generada (regexp_replace es IMMUTABLE en Postgres)
        migrations.AddField(
            model_name="registrofuente",
            name="cedula_norm",
            field=models.GeneratedField(
                db_persist=True,
                expression=personas.functions.RegexpReplace(
                    django.db.models.functions.comparison.Coalesce(
                        "cedula", models.Value("")
                    ),
                    models.Value("\\D"),
                    models.Value(""),
                    models.Value("g"),
                ),
                output_field=models.TextField(),
            ),
        ),
        # 3. Índice btree en cedula_norm (no unique)
        migrations.AddIndex(
            model_name="registrofuente",
            index=models.Index(fields=["cedula_norm"], name="idx_rf_cedula"),
        ),
        # 4. content_hash para idempotencia de ingesta
        migrations.AddField(
            model_name="registrofuente",
            name="content_hash",
            field=models.TextField(blank=True, null=True),
        ),
        # 5a. cedula_estado en personas_canonicas
        migrations.AddField(
            model_name="personacanonica",
            name="cedula_estado",
            field=models.TextField(
                db_default=models.Value("sin_confirmar"),
                help_text="confirmada | conflicto | sin_confirmar",
            ),
        ),
        # 5b. cedula_confirmada_por en personas_canonicas
        migrations.AddField(
            model_name="personacanonica",
            name="cedula_confirmada_por",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="responder | oficial | cne | consenso",
            ),
        ),
    ]
