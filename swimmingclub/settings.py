from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-me-in-production')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost 127.0.0.1').split()

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'crispy_forms',
    'crispy_bootstrap5',
    # Project apps
    'accounts',
    'swimmers',
    'groups',
    'training',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'swimmingclub.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'swimmingclub.context_processors.branding',
                'swimmingclub.context_processors.i18n',
            ],
        },
    },
]

WSGI_APPLICATION = 'swimmingclub.wsgi.application'
ASGI_APPLICATION = 'swimmingclub.asgi.application'

# Channels – uses Redis when REDIS_URL is set, falls back to in-memory for SQLite dev.
_redis_url = os.environ.get('REDIS_URL', '')
CHANNEL_LAYERS = {
    'default': (
        {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_redis_url]},
        }
        if _redis_url else
        {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    )
}

DATABASES = {
    'default': {
        'ENGINE': (
            'django.db.backends.postgresql'
            if os.environ.get('DB_HOST')
            else 'django.db.backends.sqlite3'
        ),
        'NAME':     os.environ.get('DB_NAME',     str(BASE_DIR / 'db.sqlite3')),
        'USER':     os.environ.get('DB_USER',     ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST':     os.environ.get('DB_HOST',     ''),
        'PORT':     os.environ.get('DB_PORT',     '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Branding ──────────────────────────────────────────────────────────────────
APP_NAME = 'LaneKit'
ORGANISATION_NAME = os.environ.get('ORGANISATION_NAME', 'My Swimming Club')

# Default UI language – must be a code present in locale/registry.py LANGUAGES.
# Users can switch per-session via the navbar language picker.
DEFAULT_LANGUAGE = os.environ.get('DEFAULT_LANGUAGE', 'de')

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'


DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', f'info@{APP_NAME.lower()}.com')

# DEBUG: emails get printed into console
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Required when running behind an HTTPS reverse proxy
_domain = os.environ.get('DOMAIN', '')
if _domain:
    CSRF_TRUSTED_ORIGINS = [f'https://{_domain}', f'https://www.{_domain}']
    USE_X_FORWARDED_HOST = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
