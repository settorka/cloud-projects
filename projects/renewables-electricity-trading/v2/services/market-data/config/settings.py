import os
import re
from app.configuration import load_configuration, integer

load_configuration()

SERVICE = "market-data"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = False
ALLOWED_HOSTS = os.environ["ALLOWED_HOSTS"].split(",")
DB_PREFIX = SERVICE.upper().replace("-", "_")
DB_SCHEMA = os.getenv("DB_SCHEMA") or os.environ[f"{DB_PREFIX}_DB_SCHEMA"]
if not re.fullmatch(r"[a-z_][a-z0-9_]*", DB_SCHEMA):
    raise ValueError("Invalid DB_SCHEMA identifier")
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    "rest_framework.authtoken",
    "app",
]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "app.observability.RequestMetrics"]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.getenv("DB_USER") or os.environ[f"{DB_PREFIX}_DB_USER"],
        "PASSWORD": os.getenv("DB_PASSWORD") or os.environ[f"{DB_PREFIX}_DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "options": f"-c search_path={DB_SCHEMA} -c lock_timeout={integer('DB_LOCK_TIMEOUT_MS')} -c statement_timeout={integer('DB_STATEMENT_TIMEOUT_MS')}"
        },
        "TEST": {"NAME": "test_market_data"},
    }
}
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": integer("API_PAGE_SIZE", 1, 1000),
    "DEFAULT_RENDERER_CLASSES": ["app.rendering.FinancialRenderer"],
    "EXCEPTION_HANDLER": "app.common.exception_handler",
}
DATA_UPLOAD_MAX_MEMORY_SIZE = integer("HTTP_MAX_BODY_BYTES")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "app.observability.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}
