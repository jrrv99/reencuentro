"""Settings de Django para apps/api (el core de reencuentro).

Lee configuración del entorno (las mismas vars de infra/.env). Sin dependencias de
dotenv: en local exporta las vars o usa los defaults, que coinciden con
infra/docker-compose.yml.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# --- Seguridad / debug ---------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-inseguro-cambiar-en-prod")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip()
    for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# --- Apps ----------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # operaciones de extensión, índices GIN, etc.
    # Terceros
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    # Apps del proyecto (cada una un módulo independiente — filosofía SiteHub).
    "personas",
    "ingesta",
    "dedup",
    "identidad",
    "instituciones",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Base de datos (Postgres + pgvector) ---------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "reencuentro"),
        "USER": env("POSTGRES_USER", "reencuentro"),
        "PASSWORD": env("POSTGRES_PASSWORD", "reencuentro"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery + Redis ------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- Password validation -------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n ----------------------------------------------------------------------
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Caracas"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# --- DRF -----------------------------------------------------------------------
# Versionado /api/v1/ desde el día uno (URLPathVersioning).
# Lectura pública = read-only + throttling fuerte + privacy-filter en el serializer.
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Throttling en DRF; en prod además se throttlea en Cloudflare.
        "anon": "120/min",
        "busqueda": "60/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "reencuentro API",
    "DESCRIPTION": (
        "Agregador con resolución de identidades para personas desaparecidas "
        "(terremoto Venezuela 2026). NO oficial. Los serializers públicos nunca "
        "exponen contacto, cédula cruda, identidad de responders ni embeddings."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- CORS ----------------------------------------------------------------------
# El buscador público (Next.js) consume la API desde otro origen.
CORS_ALLOW_ALL_ORIGINS = DEBUG
