import os
import warnings
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PLACEHOLDER_SECRETS = {"dev-insecure-secret-key-change-me", "change-me-in-production"}

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")
if not DEBUG and SECRET_KEY in PLACEHOLDER_SECRETS:
    raise ImproperlyConfigured("Set a real DJANGO_SECRET_KEY (or DJANGO_DEBUG=true for local dev)")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if DEBUG:
    # the Vite dev server proxies /api, so its origin must pass CSRF
    CSRF_TRUSTED_ORIGINS += ["http://localhost:5173", "http://127.0.0.1:5173"]

ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "true").lower() == "true"

if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    # TLS is terminated by the reverse proxy
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "true").lower() == "true"
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "accounts",
    "workspaces",
    "papers",
    "chat",
    "usage",
]

MIDDLEWARE = [
    "config.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    MIDDLEWARE.append("config.middleware.ContentSecurityPolicyMiddleware")

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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "research_copilot"),
        "USER": os.environ.get("POSTGRES_USER", "research_copilot"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "research_copilot"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# silence WhiteNoise's missing-directory warning before collectstatic
warnings.filterwarnings("ignore", message="No directory at")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# output of `npm run build` in frontend/
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Celery ---
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BEAT_SCHEDULE = {
    "fail-stuck-papers": {"task": "papers.tasks.fail_stuck_papers", "schedule": 600.0},
}
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"

# --- Research Copilot app config ---
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
EMBEDDING_DIM = 384

# auto = real providers with keys, demo = offline canned answers
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

RAG_CHUNK_SIZE = 800
RAG_CHUNK_OVERLAP = 120
RAG_RETRIEVAL_K = 8
RAG_CANDIDATES = 24  # per retriever (vector, keyword), before fusion
RAG_RRF_K = 60
RAG_MAX_CHUNKS_PER_PAPER = 3
RAG_HISTORY_MESSAGES = 6  # prior turns shown to the rewrite/synthesize prompts
RAG_MAX_RETRIES = 3

DAILY_QUESTION_QUOTA = int(os.environ.get("DAILY_QUESTION_QUOTA", "50"))

REST_FRAMEWORK = {
    # rate limits are per process (local-memory cache)
    "DEFAULT_THROTTLE_RATES": {"auth": "10/min", "question": "20/min", "search": "20/min"},
    "EXCEPTION_HANDLER": "api.exceptions.api_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "config.jsonlog.RequestIdFilter"}},
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
        "json": {"()": "config.jsonlog.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain" if DEBUG else "json",
            "filters": ["request_id"],
        }
    },
    "loggers": {
        name: {"handlers": ["console"], "level": "INFO", "propagate": False}
        for name in ("agent", "api", "papers", "chat", "django.request")
    },
}

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    # Django and Celery integrations are enabled automatically
    sentry_sdk.init(dsn=SENTRY_DSN, send_default_pii=False, traces_sample_rate=0.0)
