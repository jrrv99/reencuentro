"""Modelo de datos — reproduce el esquema SQL del plan §3.

Regla de oro: un índice de personas, varios usos. Buscados y encontrados son el
mismo tipo de registro, diferenciados por la bandera `tipo`.

Tres capas de resolución de identidad:
  - RegistroFuente   → lo crudo, 1 por reporte por fuente. Canónico e INMUTABLE.
  - PersonaCanonica  → la entidad resuelta. Es una *vista* construida por clustering.
  - ClusterLink      → qué registros crudos son la misma persona (con score/método).
  - ParNegativo      → "ya se juzgó que NO son la misma" (no volver a preguntar).
  - EstadoClaim      → estados como claims versionados, atribuidos y reversibles.
"""
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Value
from django.db.models.functions import Coalesce, Lower, Now
from pgvector.django import HnswIndex, VectorField

from .choices import (
    AutorTipo,
    CedulaConfirmadaPor,
    CedulaEstado,
    EstadoRep,
    MetodoCluster,
    TipoFuente,
    TipoRegistro,
)
from .functions import GenRandomUUID, ImmutableUnaccent, RegexpReplace


class RegistroFuente(models.Model):
    """Lo crudo: una fila por reporte por fuente. Nunca se destruye."""

    id = models.UUIDField(
        primary_key=True, db_default=GenRandomUUID(), editable=False
    )
    tipo = models.TextField(choices=TipoRegistro.choices)
    identificado = models.BooleanField(
        db_default=Value(True), help_text="false = encontrado sin identificar"
    )
    fuente = models.TextField(
        help_text="'dtv' | 'vtb' | 'venapp' | 'hospital_vargas' | 'ig_*'"
    )
    id_origen = models.TextField(null=True, blank=True)
    url_origen = models.TextField(
        null=True, blank=True, help_text="link de vuelta para verificar"
    )
    nombre = models.TextField(null=True, blank=True)
    # Columna generada STORED: unaccent + minúsculas + colapsar espacios.
    # Usa immutable_unaccent (ver functions.py / migración 0001).
    nombre_norm = models.GeneratedField(
        expression=Lower(
            ImmutableUnaccent(
                RegexpReplace(
                    Coalesce("nombre", Value("")),
                    Value(r"\s+"),
                    Value(" "),
                    Value("g"),
                )
            )
        ),
        output_field=models.TextField(),
        db_persist=True,
    )
    cedula = models.TextField(null=True, blank=True)
    # Columna generada STORED: solo dígitos. regexp_replace es IMMUTABLE en Postgres.
    # Sin unique: la misma cédula puede aparecer en varias fuentes (es el duplicado a detectar).
    cedula_norm = models.GeneratedField(
        expression=RegexpReplace(
            Coalesce("cedula", Value("")),
            Value(r"\D"),
            Value(""),
            Value("g"),
        ),
        output_field=models.TextField(),
        db_persist=True,
    )
    edad = models.IntegerField(null=True, blank=True)
    sexo = models.TextField(null=True, blank=True)
    zona = models.TextField(null=True, blank=True)
    descripcion = models.TextField(
        null=True, blank=True, help_text="ropa, tatuajes, cicatrices, rasgos"
    )
    foto_url = models.TextField(null=True, blank=True)
    foto_phash = models.TextField(
        null=True, blank=True, help_text="perceptual hash: detecta MISMA foto"
    )
    face_embedding = VectorField(
        dimensions=512,
        null=True,
        blank=True,
        help_text="InsightFace: detecta MISMA persona en otra foto",
    )
    estado_rep = models.TextField(
        null=True, blank=True, choices=EstadoRep.choices
    )
    ubicacion = models.TextField(
        null=True, blank=True, help_text="hospital/centro donde está (si encontrado)"
    )
    # LÍNEA ROJA: contacto de la familia. PRIVADO. Nunca en un serializer público.
    contacto = models.TextField(null=True, blank=True)
    tipo_fuente = models.TextField(
        choices=TipoFuente.choices,
        db_default=Value(TipoFuente.FAMILIAR),
    )
    confianza = models.FloatField(
        db_default=Value(1.0), help_text="baja si vino de extracción LLM"
    )
    raw_payload = models.JSONField(null=True, blank=True)
    # sha256 del registro crudo (mismas columnas que usa el consolidador, excluyendo
    # fecha_actualizacion). Permite clasificar sin_cambio/actualizado en cada corrida.
    content_hash = models.TextField(null=True, blank=True, db_index=False)
    ingested_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "registros_fuente"
        constraints = [
            models.UniqueConstraint(
                fields=["fuente", "id_origen"], name="uniq_fuente_id_origen"
            ),
            # SIN unique sobre cedula: la misma cédula se repite entre fuentes
            # (ES el duplicado que detectamos) y puede tener typos.
        ]
        indexes = [
            GinIndex(
                name="idx_rf_nombre",
                fields=["nombre_norm"],
                opclasses=["gin_trgm_ops"],
            ),
            models.Index(name="idx_rf_zona", fields=["zona"]),
            # btree en cedula_norm para bloqueo de dedup (no unique).
            models.Index(name="idx_rf_cedula", fields=["cedula_norm"]),
            HnswIndex(
                name="idx_rf_face",
                fields=["face_embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.nombre or '(sin nombre)'} [{self.fuente}/{self.tipo}]"


class PersonaCanonica(models.Model):
    """La entidad resuelta. Es una *vista* construida por clustering, no data autorada.
    Si el dedup se equivoca, se re-clusteriza sin perder nada."""

    id = models.UUIDField(
        primary_key=True, db_default=GenRandomUUID(), editable=False
    )
    nombre_display = models.TextField(null=True, blank=True)
    cedula = models.TextField(null=True, blank=True)
    cedula_estado = models.TextField(
        choices=CedulaEstado.choices,
        db_default=Value(CedulaEstado.SIN_CONFIRMAR),
    )
    cedula_confirmada_por = models.TextField(
        null=True, blank=True, choices=CedulaConfirmadaPor.choices
    )
    zona = models.TextField(null=True, blank=True)
    estado_actual = models.TextField(
        null=True, blank=True, choices=EstadoRep.choices,
        help_text="derivado del claim vigente más confiable"
    )
    foto_principal = models.TextField(null=True, blank=True)
    n_fuentes = models.IntegerField(db_default=Value(1))
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "personas_canonicas"

    def __str__(self):
        return self.nombre_display or f"persona {self.id}"


class ClusterLink(models.Model):
    """Qué registro crudo pertenece a qué persona canónica (con score, método, etc.).
    Guarda `metodo` y autoría para permitir rollback por cuenta."""

    registro = models.OneToOneField(
        RegistroFuente,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="registro_id",
        related_name="cluster_link",
    )
    persona = models.ForeignKey(
        PersonaCanonica,
        on_delete=models.CASCADE,
        db_column="persona_id",
        null=True,
        blank=True,
        related_name="links",
    )
    score = models.FloatField(null=True, blank=True)
    metodo = models.TextField(null=True, blank=True, choices=MetodoCluster.choices)
    confirmado = models.BooleanField(db_default=Value(False))

    class Meta:
        db_table = "cluster_links"

    def __str__(self):
        return f"{self.registro_id} → {self.persona_id} ({self.metodo})"


class ParNegativo(models.Model):
    """"Ya dijeron que NO son la misma". El dedup respeta esto al clusterizar."""

    pk = models.CompositePrimaryKey("registro_a", "registro_b")
    registro_a = models.ForeignKey(
        RegistroFuente,
        on_delete=models.CASCADE,
        db_column="registro_a",
        related_name="+",
    )
    registro_b = models.ForeignKey(
        RegistroFuente,
        on_delete=models.CASCADE,
        db_column="registro_b",
        related_name="+",
    )

    class Meta:
        db_table = "pares_negativos"

    def __str__(self):
        return f"{self.registro_a_id} ≠ {self.registro_b_id}"


class EstadoClaim(models.Model):
    """Estados como claims versionados, atribuidos y reversibles — no verdad final.

    autor_tipo discrimina qué FK de autor está poblado:
      RESPONDER → autor_responder (FK a instituciones.Responder)
      FAMILIAR  → autor_registro  (FK a RegistroFuente que originó el claim)
      SISTEMA   → ambos null

    corrobora apunta a otro claim que sirve como segundo testimonio.
    Requerido para marcar fallecido (plan §11).

    Rollback por cuenta = vigente=False en todos los claims del mismo autor.
    """

    id = models.UUIDField(
        primary_key=True, db_default=GenRandomUUID(), editable=False
    )
    persona = models.ForeignKey(
        PersonaCanonica,
        on_delete=models.CASCADE,
        db_column="persona_id",
        related_name="claims",
    )
    estado = models.TextField(choices=EstadoRep.choices)
    ubicacion = models.TextField(null=True, blank=True)
    autor_tipo = models.TextField(
        null=True, blank=True, choices=AutorTipo.choices
    )
    autor_responder = models.ForeignKey(
        "instituciones.Responder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claims",
        db_column="autor_responder_id",
    )
    autor_registro = models.ForeignKey(
        RegistroFuente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claims_autorados",
        db_column="autor_registro_id",
    )
    corrobora = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corroborado_por",
        db_column="corrobora_id",
    )
    vigente = models.BooleanField(
        db_default=Value(True), help_text="false = revertido/superado"
    )
    disputado = models.BooleanField(
        db_default=Value(False), help_text="la familia lo objetó"
    )
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "estado_claims"
        indexes = [
            models.Index(
                name="idx_claims_persona", fields=["persona", "vigente"]
            ),
        ]

    def __str__(self):
        return f"{self.estado} ({'vigente' if self.vigente else 'superado'})"
