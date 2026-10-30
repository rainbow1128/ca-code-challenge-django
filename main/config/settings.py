"""Settings for the main (content) service.

The main service owns brands, reviews, industries and reviewer profiles.
It does not store passwords or roles (those live in the auth service), so
django.contrib.auth is deliberately not installed.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("POSTGRES_HOST", "main-db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "NAME": os.environ.get("POSTGRES_DB", "main"),
        "USER": os.environ.get("POSTGRES_USER", "main"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
# main/static/css/main.css is compiled from frontend/scss (not committed).
STATICFILES_DIRS = [BASE_DIR / "static"]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Public API for now. Authentication comes from the auth service in a later
    # step; there is no django.contrib.auth here, so no anonymous user object.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

# WordPress source database, read only by the import_wp command. Not a Django
# DATABASES alias on purpose: the ORM, migrate and the running site never see it.
WP_SOURCE = {
    "host": os.environ.get("WP_DB_HOST", "db"),
    "port": int(os.environ.get("WP_DB_PORT", "3306")),
    "database": os.environ.get("WP_DB_NAME", "wp"),
    "user": os.environ.get("WP_DB_USER", "wp"),
    "password": os.environ.get("WP_DB_PASSWORD", ""),
    "table_prefix": os.environ.get("WP_TABLE_PREFIX", "wp_"),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
