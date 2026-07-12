"""Enums (TextChoices) de la app personas. Importar desde aquí, no repetir strings.

Convención del proyecto: SIEMPRE usar estas clases en vez de strings literales.
  Bien:  metodo=MetodoCluster.CEDULA
  Mal:   metodo="cedula"
"""
from django.db import models


class TipoRegistro(models.TextChoices):
    BUSCADO = "buscado", "Buscado"
    ENCONTRADO = "encontrado", "Encontrado"


class EstadoRep(models.TextChoices):
    SIN_CONTACTO = "sin_contacto", "Sin contacto"
    ENCONTRADO_VIVO = "encontrado_vivo", "Encontrado vivo"
    HERIDO = "herido", "Herido"
    HOSPITALIZADO = "hospitalizado", "Hospitalizado"
    REFUGIADO = "refugiado", "Refugiado"
    FALLECIDO = "fallecido", "Fallecido"


class TipoFuente(models.TextChoices):
    FAMILIAR = "familiar", "Familiar"
    RESCATISTA = "rescatista", "Rescatista"
    HOSPITAL = "hospital", "Hospital"
    CLINICA = "clinica", "Clínica"
    OFICIAL = "oficial", "Oficial"
    PARTNER = "partner", "Partner"


class CedulaEstado(models.TextChoices):
    CONFIRMADA = "confirmada", "Confirmada"
    CONFLICTO = "conflicto", "Conflicto"
    SIN_CONFIRMAR = "sin_confirmar", "Sin confirmar"


class CedulaConfirmadaPor(models.TextChoices):
    RESPONDER = "responder", "Responder"
    OFICIAL = "oficial", "Oficial"
    CNE = "cne", "CNE"
    CONSENSO = "consenso", "Consenso"


class MetodoCluster(models.TextChoices):
    BOOTSTRAP = "bootstrap", "Bootstrap"
    CEDULA = "cedula", "Cédula"
    PHASH = "phash", "pHash"
    FUZZY = "fuzzy", "Fuzzy"
    CARA = "cara", "Cara"
    LLM = "llm", "LLM"
    MANUAL = "manual", "Manual"
    USUARIO = "usuario", "Usuario"


class AutorTipo(models.TextChoices):
    FAMILIAR = "familiar", "Familiar"
    RESPONDER = "responder", "Responder"
    OFICIAL = "oficial", "Oficial"
    SISTEMA = "sistema", "Sistema"
