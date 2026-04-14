from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    raw = config(name, default=str(default))
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)

SECRET_KEY = config("SECRET_KEY", default="django-insecure-pigly-dev-key")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost,testserver", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "core",
    "users",
    "assistant",
    "history",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_context",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("ru", "Russian"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = config("TIME_ZONE", default="UTC")

USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

AUTH_USER_MODEL = "users.User"
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:landing"
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_ADAPTER = "users.adapters.PiglyAccountAdapter"
SOCIALACCOUNT_ADAPTER = "users.adapters.PiglySocialAccountAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
ACCOUNT_MESSAGES = False

GOOGLE_OAUTH_CLIENT_ID = config("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = config("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_AUTH_ENABLED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    }
}
if GOOGLE_AUTH_ENABLED:
    SOCIALACCOUNT_PROVIDERS["google"]["APPS"] = [
        {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "key": "",
        }
    ]

SITE_NAME = "Pigly"
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Pigly <no-reply@pigly.app>")
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

EXTENSION_INSTALL_URL = config("EXTENSION_INSTALL_URL", default="#")
EXTENSION_TOKEN_PREFIX = "pigly_"
TURNSTILE_SITE_KEY = config("TURNSTILE_SITE_KEY", default="")
TURNSTILE_SECRET_KEY = config("TURNSTILE_SECRET_KEY", default="")
NOWPAYMENTS_API_KEY = config("NOWPAYMENTS_API_KEY", default="")
NOWPAYMENTS_IPN_SECRET = config("NOWPAYMENTS_IPN_SECRET", default="")
NOWPAYMENTS_API_BASE_URL = config("NOWPAYMENTS_API_BASE_URL", default="https://api.nowpayments.io").rstrip("/")
WEB3_PAYMENT_RECEIVER_ADDRESS = config("WEB3_PAYMENT_RECEIVER_ADDRESS", default="")
WEB3_ETHEREUM_RPC_URL = config("WEB3_ETHEREUM_RPC_URL", default="https://ethereum.publicnode.com")
WEB3_BASE_RPC_URL = config("WEB3_BASE_RPC_URL", default="https://mainnet.base.org")
WEB3_ARBITRUM_RPC_URL = config("WEB3_ARBITRUM_RPC_URL", default="https://arb1.arbitrum.io/rpc")
WEB3_ABSTRACT_RPC_URL = config("WEB3_ABSTRACT_RPC_URL", default="https://api.mainnet.abs.xyz")

AUTH_RATE_LIMITS = {
    "login_ip": (100, 10 * 60),
    "login_email": (8, 10 * 60),
    "register_ip": (50, 60 * 60),
    "register_email": (5, 60 * 60),
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pigly-local-cache",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
